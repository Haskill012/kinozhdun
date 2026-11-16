"""Reviewed, repeatable three-year catalogue backfill without historical news.

Run with --apply locally or --remote --apply against the existing site container.
Remote output is saved as a reviewable manifest; existing complete cards are preserved.
"""
import argparse
import asyncio
import json
import re
import sqlite3
import subprocess
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path

ROOT = Path('/app') if Path('/app/website').exists() else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Established shows with new seasons in the window are checked using season dates.
SERIES = [93405, 119051, 66732, 95396, 94997, 108978, 100088, 136315,
          84773, 1396, 76479, 71712, 110492, 1399, 126308, 202555, 156902,
          87083, 194764, 157744, 118642, 157369, 229711, 250923]
BLOCKBUSTERS = {
    2024: ['Inside Out 2', 'Deadpool & Wolverine', 'Moana 2', 'Despicable Me 4',
           'Wicked', 'Mufasa: The Lion King', 'Dune: Part Two',
           'Godzilla x Kong: The New Empire', 'Kung Fu Panda 4', 'Sonic the Hedgehog 3',
           'Venom: The Last Dance', 'Gladiator II', 'Beetlejuice Beetlejuice',
           'Bad Boys: Ride or Die', 'Kingdom of the Planet of the Apes',
           'Twisters', 'It Ends with Us', 'Alien: Romulus', 'The Wild Robot'],
    2025: ['Ne Zha 2', 'Zootopia 2', 'Avatar: Fire and Ash', 'Lilo & Stitch',
           'A Minecraft Movie', 'Jurassic World Rebirth', 'How to Train Your Dragon',
           'F1', 'Superman', 'Mission: Impossible - The Final Reckoning',
           'Wicked: For Good', 'The Fantastic Four: First Steps',
           'The Conjuring: Last Rites', 'Captain America: Brave New World',
           'The Housemaid', 'Thunderbolts*', 'Sinners', 'Final Destination Bloodlines',
           'Weapons', 'KPop Demon Hunters'],
    2026: ['Spider-Man: Brand New Day', 'The Odyssey', 'Toy Story 5', 'Michael',
           'The Super Mario Galaxy Movie', 'The Devil Wears Prada 2',
           'Project Hail Mary', 'Minions & Monsters', 'Obsession', 'Backrooms',
           'Hoppers', 'The Mandalorian and Grogu', 'Moana', 'Disclosure Day',
           'Wuthering Heights', 'Scream 7', 'Mortal Kombat II', 'Supergirl'],
}


def recent(media, detail, lower, upper):
    from website.editor import valid_date
    values = [detail.get('release_date') if media == 'movie' else detail.get('first_air_date')]
    if media == 'tv':
        values.extend(s.get('air_date') for s in detail.get('seasons') or []
                      if (s.get('season_number') or 0) > 0)
        values.append((detail.get('last_episode_to_air') or {}).get('air_date'))
    return any(lower <= value <= upper for raw in values if (value := valid_date(raw)))


async def collect():
    import aiohttp
    from website.__main__ import configuration
    from website.content import Store
    from website.editor import Editor, today, error_text
    from website.audience import audience_metadata, exclusion_reason
    cfg = configuration()
    assert cfg['api_key'], 'TMDB key is not configured'
    store = Store(cfg['database'])
    editor = Editor(store, cfg)
    upper = today().isoformat()
    lower = date(today().year - 2, 1, 1).isoformat()
    candidates, curated, errors, skipped = {}, set(), [], []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=35), trust_env=True) as session:
        editor.session = session
        for year in range(today().year - 2, today().year + 1):
            start, end = f'{year}-01-01', min(f'{year}-12-31', upper)
            for media in ('movie', 'tv'):
                for order in ('popularity.desc', 'vote_count.desc', 'vote_average.desc'):
                    for page in (1, 2):
                        field = 'primary_release_date' if media == 'movie' else 'first_air_date'
                        params = {field + '.gte': start, field + '.lte': end,
                                  'sort_by': order, 'page': page, 'include_adult': 'false',
                                  'vote_count.gte': 300 if media == 'movie' else 100,
                                  'vote_average.gte': 6 if media == 'movie' else 7}
                        if media == 'tv':
                            params['without_genres'] = '10763,10764,10767,10766'
                        try:
                            result = await editor.fetch('/discover/' + media, **params)
                            for row in result.get('results') or []:
                                candidates[(media, row['id'])] = row
                        except Exception as exc:
                            errors.append({'query': f'{media}:{year}:{order}:{page}', 'error': error_text(exc)})
            # Russian releases often have fewer votes in the global catalogue.
            for media in ('movie', 'tv'):
                field = 'primary_release_date' if media == 'movie' else 'first_air_date'
                result = await editor.fetch('/discover/' + media, **{
                    field + '.gte': start, field + '.lte': end, 'with_original_language': 'ru',
                    'sort_by': 'popularity.desc', 'vote_count.gte': 20,
                    'include_adult': 'false', 'without_genres': '10763,10764,10767,10766'})
                for row in result.get('results') or []:
                    candidates[(media, row['id'])] = row
        # Match original titles AND year, never blindly take the first search result.
        normalize = lambda value: re.sub(r'[^\w]', '', (value or '').casefold())
        for year, names in BLOCKBUSTERS.items():
            for name in names:
                result = await editor.fetch('/search/movie', query=name, year=year, include_adult='false')
                matches = [r for r in result.get('results') or []
                           if (r.get('release_date') or '')[:4] == str(year)
                           and normalize(name) in (normalize(r.get('title')), normalize(r.get('original_title')))]
                if matches:
                    row = max(matches, key=lambda r: r.get('vote_count') or 0)
                    candidates[('movie', row['id'])] = row
                    curated.add(('movie', row['id']))
                else:
                    skipped.append({'title': name, 'year': year, 'reason': 'no-exact-year-title-match'})
        for ident in SERIES:
            candidates.setdefault(('tv', ident), {})
        semaphore = asyncio.Semaphore(4)
        async def resolve(key):
            media, ident = key
            async with semaphore:
                try:
                    detail = await editor.fetch_details(media, ident)
                    metadata = audience_metadata(media, detail)
                    reason = exclusion_reason({**detail, **metadata, 'media_type': media,
                                               'key': f'{media}:{ident}'}, cfg)
                    if reason or detail.get('adult') or not detail.get('poster_path') or not detail.get('overview'):
                        skipped.append({'key': f'{media}:{ident}', 'reason': reason or 'incomplete-or-adult'})
                        return None
                    if not recent(media, detail, lower, upper):
                        return None
                    if not re.search('[А-Яа-яЁё]', detail.get('overview') or ''):
                        skipped.append({'key': f'{media}:{ident}', 'reason': 'no-russian-description'})
                        return None
                    # Curated box-office hits qualify even with a modest audience rating.
                    if key not in curated and (detail.get('vote_average') or 0) < 6:
                        return None
                    return media, detail
                except Exception as exc:
                    errors.append({'key': f'{media}:{ident}', 'error': error_text(exc)})
                    return None
        details = [entry for entry in await asyncio.gather(*(resolve(k) for k in candidates)) if entry]
    return store, editor, details, dict(window=[lower, upper], candidates=len(candidates),
                                       errors=errors, skipped=skipped)


async def main(apply=False):
    from website.content import now
    store, editor, details, report = await collect()
    before = len(store.catalog())
    added, existing, cards = [], [], []
    if apply:
        backup = Path(editor.config['database']).with_name('website-before-recent-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.db')
        with sqlite3.connect(backup) as destination:
            store.db.backup(destination)
        report['backup'] = str(backup)
    for media, detail in details:
        key = f"{media}:{detail['id']}"
        old = store.catalog_item(key)
        if old and not old.get('needs_details'):
            existing.append(key)
            cards.append(old)
            continue
        if apply:
            editor.process(media, detail, emit_news=False, publish_card=True)
            card = store.catalog_item(key)
            assert card and card.get('poster') and card.get('overview'), key
            cards.append(card)
        added.append(key)
    if apply:
        store.state('recent_catalog_backfill', json.dumps({'at': now(), 'window': report['window'], 'added': len(added)}))
    report.update(before=before, after=len(store.catalog()), added=added, existing=existing,
                  selected=len(details), selected_by_type=dict(Counter(m for m, _ in details)), cards=cards)
    store.db.close()
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--remote', action='store_true')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if args.remote:
        ssh = ['ssh', '-i', str(Path.home() / '.ssh/kinojdun_codex_deploy'),
               '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', 'root@62.217.176.12',
               'docker exec -i kinozhdun_site python -' + (' --apply' if args.apply else '')]
        run = subprocess.run(ssh, input=Path(__file__).read_text(encoding='utf-8'),
                             text=True, encoding='utf-8', capture_output=True, timeout=1200)
        if run.returncode:
            print(run.stderr[-2500:])
            sys.exit(run.returncode)
        report = json.loads(run.stdout)
        out = ROOT / 'diagnostics/recent-catalog-2026-10-07'
        out.mkdir(parents=True, exist_ok=True)
        (out / ('import.json' if args.apply else 'preview.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k: v for k, v in report.items() if k not in ('cards', 'added', 'existing', 'skipped')}, ensure_ascii=False, indent=2))
    else:
        asyncio.run(main(args.apply))
