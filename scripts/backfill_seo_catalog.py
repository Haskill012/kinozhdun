"""Add a reviewed batch of 500 distinct, fully localized evergreen catalogue cards.

Demand signals are TMDB votes/popularity and movie revenue, not search volumes.
Existing catalogue entries, published or queued, never consume the new-card quota.
"""
import argparse
import asyncio
import json
import re
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter
from contextlib import closing
from datetime import datetime
from itertools import zip_longest
from pathlib import Path

ROOT = Path('/app') if Path('/app/website').exists() else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TARGETS = {'movie': 320, 'tv': 180}


def interleave(lanes):
    seen, result = set(), []
    for group in zip_longest(*lanes):
        for key in group:
            if key is not None and key not in seen:
                seen.add(key)
                result.append(key)
    return result


def rejection(media, detail, config, current):
    from website.audience import audience_metadata, exclusion_reason
    from website.editor import valid_date
    from website.title_names import canonical_title
    if detail.get('adult'):
        return 'adult'
    title = canonical_title(detail.get('title') or detail.get('name') or '',
                            detail.get('original_title') or detail.get('original_name'))
    if not re.search('[А-Яа-яЁё]', title):
        return 'no-russian-title'
    if len((detail.get('overview') or '').strip()) < 120 or not re.search('[А-Яа-яЁё]', detail.get('overview') or ''):
        return 'no-substantial-russian-description'
    if not detail.get('poster_path') or not detail.get('genres'):
        return 'incomplete-artwork-or-genres'
    first = valid_date(detail.get('release_date') if media == 'movie' else detail.get('first_air_date'))
    if not first or first > current:
        return 'not-released'
    votes = int(detail.get('vote_count') or 0)
    ru = detail.get('original_language') == 'ru'
    if votes < (30 if ru else 500 if media == 'movie' else 200):
        return 'insufficient-audience-evidence'
    rating = float(detail.get('vote_average') or 0)
    gross = int(detail.get('revenue') or 0)
    if rating < 6 and not (media == 'movie' and gross >= 100_000_000 and rating >= 5):
        return 'low-rating'
    item = {**detail, **audience_metadata(media, detail), 'title': title,
            'media_type': media, 'key': f"{media}:{detail.get('id')}"}
    return exclusion_reason(item, config)


async def collect(store, config):
    import aiohttp
    from website.editor import Editor, today, error_text
    from website.content import Store
    editor = Editor(store, config)
    current = today().isoformat()
    existing = {c['key'] for c in store.catalog(False)}
    errors, skipped, evidence = [], [], {}
    lanes = {'movie': [], 'tv': []}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=40), trust_env=True) as session:
        editor.session = session
        for media in ('movie', 'tv'):
            sorts = ('revenue.desc', 'vote_count.desc', 'popularity.desc') if media == 'movie' else ('vote_count.desc', 'popularity.desc', 'vote_average.desc')
            for order in sorts:
                lane = []
                for page in range(1, 21):
                    field = 'primary_release_date' if media == 'movie' else 'first_air_date'
                    params = {'sort_by': order, 'page': page, 'include_adult': 'false',
                              field + '.lte': current, 'vote_count.gte': 500 if media == 'movie' else 200,
                              'vote_average.gte': 5 if media == 'movie' and order == 'revenue.desc' else 6}
                    if media == 'tv':
                        params['without_genres'] = '10763,10764,10767,10766'
                    try:
                        data = await editor.fetch('/discover/' + media, **params)
                        for rank, row in enumerate(data.get('results') or [], 1):
                            key = f"{media}:{row['id']}"
                            if key not in existing:
                                lane.append(key)
                                evidence.setdefault(key, []).append({'signal': order, 'position': (page - 1) * 20 + rank})
                    except Exception as exc:
                        errors.append({'query': f'{media}:{order}:{page}', 'error': error_text(exc)})
                lanes[media].append(lane)
            # Add well-known Russian projects to the pool alongside global hits.
            ru_lane = []
            for page in range(1, 5):
                data = await editor.fetch('/discover/' + media, **{
                    'sort_by': 'vote_count.desc', 'page': page, 'with_original_language': 'ru',
                    'include_adult': 'false', 'vote_count.gte': 30, 'vote_average.gte': 6,
                    ('primary_release_date' if media == 'movie' else 'first_air_date') + '.lte': current,
                    'without_genres': '10763,10764,10767,10766'})
                for row in data.get('results') or []:
                    key = f"{media}:{row['id']}"
                    if key not in existing:
                        ru_lane.append(key)
                        evidence.setdefault(key, []).append({'signal': 'russian-vote-count'})
            # Reserve a modest share for the site's primary audience.
            ordered = interleave(lanes[media])
            lanes[media] = interleave([ordered, ordered, ordered, ordered, ru_lane])
        semaphore = asyncio.Semaphore(4)
        async def resolve(key):
            media, ident = key.split(':')
            async with semaphore:
                try:
                    # Check localization and audience policy before requesting season trailers.
                    append = 'videos,alternative_titles,translations' + (',release_dates' if media == 'movie' else '')
                    detail = await editor.fetch(f'/{media}/{ident}', append_to_response=append, include_video_language='ru,en,null')
                    assert detail.get('id') == int(ident)
                    reason = rejection(media, detail, config, current)
                    if reason:
                        skipped.append({'key': key, 'reason': reason})
                        return None
                    if media == 'tv':
                        from website.trailers import official_trailers
                        detail['season_videos'] = {}
                        seasons = sorted({s['season_number'] for s in detail.get('seasons') or []
                                          if isinstance(s.get('season_number'), int) and s['season_number'] > 0}, reverse=True)
                        for number in seasons[:3]:
                            data = await editor.fetch(f'/tv/{ident}/season/{number}/videos', include_video_language='ru,en,null')
                            detail['season_videos'][number] = data.get('results') or []
                            if official_trailers(data.get('results') or []):
                                break
                    return media, detail
                except Exception as exc:
                    errors.append({'key': key, 'error': error_text(exc)})
                    return None
        selected = []
        for media, target in TARGETS.items():
            eligible = []
            ordered = lanes[media]
            for offset in range(0, len(ordered), 32):
                batch = await asyncio.gather(*(resolve(key) for key in ordered[offset:offset+32]))
                eligible.extend(entry for entry in batch if entry)
                print(f'{media}: {min(len(eligible), target)}/{target} complete cards checked', file=sys.stderr, flush=True)
                if len(eligible) >= target:
                    break
            if len(eligible) < target:
                raise RuntimeError(f'Only {len(eligible)} suitable new {media} cards; nothing published')
            selected.extend(eligible[:target])
    # Render the complete import with the production serializer in an isolated database.
    with tempfile.TemporaryDirectory() as directory:
        staging = Store(Path(directory) / 'staging.db')
        preview_editor = Editor(staging, config)
        for media, detail in selected:
            preview_editor.process(media, detail, emit_news=False, publish_card=True)
        cards = staging.catalog()
        assert len(cards) == sum(TARGETS.values())
        assert not staging.articles()
        staging.db.close()
    return cards, {'selected_by_type': dict(Counter(c['media_type'] for c in cards)),
                   'errors': errors, 'skipped': skipped, 'evidence': {c['key']: evidence[c['key']] for c in cards},
                   'source': 'TMDB revenue, vote count, popularity; no measured search-volume data',
                   'collected_at': current}


def publish(store, cards, config):
    from website.audience import exclusion_reason
    from website.content import now
    # All checks happen before the first write; preserve concurrent additions too.
    assert len(cards) == 500 and len({c['key'] for c in cards}) == 500
    for card in cards:
        assert not store.catalog_item(card['key'], False), 'Concurrent catalogue addition: ' + card['key']
        assert not exclusion_reason(card, config), card['key']
        assert card.get('overview') and card.get('poster') and card.get('first_release'), card['key']
    backup = Path(config['database']).with_name('website-before-seo-500-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.db')
    with closing(sqlite3.connect(backup)) as destination:
        store.db.backup(destination)
    news_before = store.db.execute('select count(*) from articles').fetchone()[0]
    published_at = now()
    # One transaction publishes all cards and snapshots, without touching daily quotas or news.
    with store.db:
        position = store.db.execute('select coalesce(max(position),0) from catalog').fetchone()[0]
        for index, card in enumerate(cards, 1):
            data = json.dumps({k: v for k, v in card.items() if k != 'published'}, ensure_ascii=False)
            store.db.execute('insert into catalog values (?,?,?,?,?)',
                             (card['key'], data, position + index, published_at, published_at))
            store.db.execute('insert or replace into titles values (?,?,?)', (card['key'], data, published_at))
        store.db.execute('insert or replace into state values (?,?)',
                         ('seo_catalog_backfill', json.dumps({'at': published_at, 'added': len(cards)})))
    assert store.db.execute('select count(*) from articles').fetchone()[0] == news_before
    return str(backup)


async def main(apply):
    from website.__main__ import configuration
    from website.content import Store
    cfg = configuration()
    assert cfg['api_key'], 'TMDB key is not configured'
    store = Store(cfg['database'])
    before = len(store.catalog())
    cards, report = await collect(store, cfg)
    if apply:
        report['backup'] = publish(store, cards, cfg)
    report.update(before=before, after=len(store.catalog()), added=len(cards) if apply else 0, cards=cards)
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
        ssh = ['ssh', '-i', str(Path.home() / '.ssh/kinojdun_codex_deploy'), '-o', 'BatchMode=yes',
               '-o', 'ConnectTimeout=10', 'root@62.217.176.12',
               'docker exec -i kinozhdun_site python -' + (' --apply' if args.apply else '')]
        run = subprocess.run(ssh, input=Path(__file__).read_text(encoding='utf-8'),
                             text=True, encoding='utf-8', capture_output=True, timeout=1500)
        out = ROOT / 'diagnostics/seo-catalog-500-2026-10-07'
        out.mkdir(parents=True, exist_ok=True)
        (out / 'import-log.txt').write_text(run.stderr, encoding='utf-8')
        if run.returncode:
            print(run.stderr[-3000:]);sys.exit(run.returncode)
        report = json.loads(run.stdout)
        (out / ('import.json' if args.apply else 'preview.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k: v for k, v in report.items() if k not in ('cards', 'skipped', 'evidence')}, ensure_ascii=False, indent=2))
    else:
        asyncio.run(main(args.apply))
