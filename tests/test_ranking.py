import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

from website.content import Store
from website.editor import Editor
from website.ranking import (ranked, interest_score, quality_score, relevant_date,
                             hero_selection, load_trends, refresh_trends)
from website.search import rank


class RankingTests(unittest.TestCase):
    current = date(2026, 10, 7)

    def movie(self, ident=1, **changes):
        return {**dict(key=f'movie:{ident}', id=ident, media_type='movie', title=f'Фильм {ident}',
                       first_release='2026-07-15', popularity=300, rating=8, votes=4000,
                       poster='https://image.tmdb.org/t/p/w500/p.jpg', image='https://image.tmdb.org/t/p/w1280/b.jpg'), **changes}

    def test_recent_hits_beat_legacy_series_with_extreme_popularity(self):
        mentalist = self.movie(2, key='tv:2', media_type='tv', first_release='2008-09-23',
                              season_premiere='2014-11-30', status='Ended', popularity=1_000_000)
        law = self.movie(3, key='tv:3', media_type='tv', first_release='1999-01-01',
                        season_premiere='2026-10-08', premiere_season=28, popularity=1_000_000)
        hit = self.movie()
        ordered = ranked([mentalist, law, hit], current=self.current)
        self.assertEqual(ordered[0]['key'], hit['key'])
        self.assertNotIn(law, hero_selection([law, hit, mentalist], current=self.current))

    def test_fresh_season_counts_but_weekly_episode_does_not(self):
        series = self.movie(2, key='tv:2', media_type='tv', first_release='2022-02-03',
                            season_premiere='2026-08-12', premiere_season=4)
        old = {**series, 'season_premiere': '2014-11-30', 'release_date': '2026-10-08',
               'episode': 7, 'last_episode_to_air': {'air_date': '2026-10-06'}}
        self.assertEqual(relevant_date(old, self.current), date(2022, 2, 3))
        self.assertEqual(relevant_date(series, self.current), date(2026, 8, 12))
        self.assertGreater(interest_score(series, current=self.current), interest_score(old, current=self.current))

    def test_today_trends_can_change_order_without_erasing_known_hits(self):
        a, b = self.movie(1), self.movie(2)
        self.assertEqual(ranked([b, a], current=self.current)[0]['id'], 1)
        self.assertEqual(ranked([a, b], {'movie:2': 50}, self.current)[0]['id'], 2)

    def test_rating_requires_evidence_and_shrinks_small_samples(self):
        self.assertEqual(quality_score(self.movie(votes=10, rating=10)), 0)
        self.assertLess(quality_score(self.movie(votes=50, rating=10)), quality_score(self.movie(votes=10000, rating=8.5)))

    def test_hero_changes_membership_daily_and_is_stable_within_a_day(self):
        items = [self.movie(n, popularity=300-n) for n in range(1, 15)]
        today = hero_selection(items, current=self.current)
        reversed_input = hero_selection(list(reversed(items)), current=self.current)
        tomorrow = hero_selection(items, current=self.current + timedelta(days=1))
        self.assertEqual(today, reversed_input)
        self.assertEqual(len({item['key'] for item in today}), 6)
        self.assertGreaterEqual(len({item['key'] for item in today} - {item['key'] for item in tomorrow}), 2)
        self.assertNotEqual([i['key'] for i in today], [i['key'] for i in tomorrow])
        self.assertTrue({'movie:1', 'movie:2', 'movie:3'} <= {i['key'] for i in tomorrow})
        for limit in (0, 1, 2, 3, 6):
            self.assertEqual(len(hero_selection(items, limit=limit, current=self.current)), limit)

    def test_hero_keeps_movies_released_months_ago_and_balances_media(self):
        items = [self.movie(i) for i in range(1, 12)]
        items.extend(self.movie(i, key=f'tv:{i}', media_type='tv', season_premiere='2026-09-01',
                                premiere_season=2, popularity=900) for i in range(20, 28))
        selected = hero_selection(items, current=self.current)
        self.assertEqual(len(selected), 6)
        self.assertLessEqual(sum(i['media_type'] == 'tv' for i in selected), 2)

    def test_search_exact_title_still_beats_a_hot_partial_match(self):
        exact = self.movie(title='Начало', first_release='2010-07-15', popularity=10)
        partial = self.movie(2, title='Начало истории', popularity=1000)
        self.assertLess(rank(exact, 'начало'), rank(partial, 'начало'))

    def test_invalid_source_numbers_do_not_poison_sorting(self):
        bad = self.movie(popularity='nan', votes='invalid', rating='inf', first_release='bad')
        self.assertGreater(interest_score(self.movie(), current=self.current), interest_score(bad, current=self.current))

    def test_trends_expire_and_corrupt_state_is_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)/'site.db')
            store.state('ranking_trends', json.dumps({'day': '2026-10-06', 'scores': {'movie:1': 50}}))
            self.assertEqual(load_trends(store, self.current)['movie:1'], 30)
            self.assertEqual(load_trends(store, date(2026, 10, 11)), {})
            store.state('ranking_trends', 'broken')
            self.assertEqual(load_trends(store, self.current), {})
            store.db.close()


class TrendRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_refresh_preserves_snapshot_and_success_obeys_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)/'site.db')
            editor = Editor(store, {})
            previous = json.dumps({'day': '2026-10-06', 'scores': {'movie:1': 30}})
            store.state('ranking_trends', previous)
            editor.fetch = AsyncMock(side_effect=[{'results': [{'id': 1, 'media_type': 'movie'}]}, RuntimeError('offline')])
            with self.assertRaises(RuntimeError):
                await refresh_trends(editor, force=True)
            self.assertEqual(store.state('ranking_trends'), previous)
            editor.fetch = AsyncMock(return_value={'results': [{'id': 1, 'media_type': 'movie'},
                                                               {'id': 2, 'media_type': 'person'}]})
            self.assertTrue(await refresh_trends(editor, force=True))
            self.assertEqual(json.loads(store.state('ranking_trends'))['scores'], {'movie:1': 60})
            self.assertFalse(await refresh_trends(editor))
            self.assertEqual(editor.fetch.await_count, 2)
            store.db.close()
