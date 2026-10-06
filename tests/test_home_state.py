import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from website.home_state import event_state, days_text, hero_projects, waiting, change_type, relative_time, watch_label
from website.catalog_views import streaming_home
from website.content import Store
from website.views import premiere_rows
from tests.test_website import config


class HomeStateTests(unittest.TestCase):
    def setUp(self):
        self.current = date(2026, 10, 6)
        self.item = dict(id=1, key='tv:1', media_type='tv', title='Сериал',
                         release_date='2026-10-08', season=27, episode=3,
                         popularity=50, rating=8, votes=100, status='Returning Series')

    def test_dates_and_russian_plurals(self):
        state = event_state(self.item, self.current)
        self.assertEqual(state['headline'], 'Новая серия через 2 дня')
        self.assertEqual(state['detail'], '8 октября · 27 сезон, 3 серия')
        self.assertEqual(state['label'], 'СТОИТ ДОЖДАТЬСЯ')
        for value, label in [('2026-10-06', 'СЕГОДНЯ'), ('2026-10-07', 'УЖЕ ЗАВТРА')]:
            self.assertEqual(event_state(dict(self.item, release_date=value), self.current)['label'], label)
        self.assertIn('вышла', event_state(dict(self.item, release_date='2026-10-05'), self.current)['headline'])
        for days, text in [(1, '1 день'), (2, '2 дня'), (5, '5 дней'), (11, '11 дней'), (21, '21 день'), (24, '24 дня'), (112, '112 дней')]:
            self.assertEqual(days_text(days), text)

    def test_season_premiere_is_distinct_from_next_episode(self):
        item = dict(self.item, season_premiere='2026-10-07', premiere_season=28)
        state = event_state(item, self.current)
        self.assertEqual(state['headline'], 'Новый сезон уже завтра')
        self.assertIn('28 сезон, 1 серия', state['detail'])
        past = event_state(dict(item, season_premiere='2026-09-01'), self.current)
        self.assertEqual(past['kind'], 'Новая серия')

    def test_unknown_invalid_and_distant_dates_never_claim_announcements(self):
        self.assertEqual(watch_label(self.item), '+ Ждать')
        self.assertEqual(watch_label(dict(self.item, is_waiting=True)), '✓ Жду')
        self.assertEqual(watch_label(dict(self.item, is_waiting='true')), '+ Ждать')
        for value in [None, '', 'bad', '2026-02-30']:
            state = event_state(dict(self.item, release_date=value), self.current)
            self.assertIsNone(state['date'])
            self.assertEqual(state['label'], 'СТОИТ ДОЖДАТЬСЯ')
        self.assertEqual(event_state(dict(self.item, release_date='2028-01-01'), self.current)['label'], 'СТОИТ ДОЖДАТЬСЯ')
        self.assertFalse(waiting(dict(self.item, status='Canceled', release_date=None), self.current))
        self.assertFalse(waiting(dict(self.item, release_date='2026-09-01'), self.current))

    def test_selection_is_deterministic_and_uses_reliable_rating(self):
        with patch('website.home_state.today', return_value=self.current):
            items = [dict(self.item, id=i, popularity=i * 5) for i in range(10)]
            self.assertEqual([i['id'] for i in hero_projects(items)], [i['id'] for i in hero_projects(list(reversed(items)))])
            self.assertEqual(len(hero_projects(items)), 6)
            self.assertEqual(hero_projects([]), [])
            rated = dict(self.item, id=11)
            unreliable = dict(self.item, id=12, votes=1, rating=10)
            self.assertEqual(hero_projects([unreliable, rated])[0]['id'], 11)

    def test_only_saved_changes_and_honest_status_labels(self):
        self.assertIsNone(change_type(dict(fingerprint='channel:123')))
        self.assertIsNone(change_type(dict(fingerprint='tmdb:tv:1:rumor:renewed')))
        self.assertEqual(change_type(dict(fingerprint='tmdb:tv:1:status:Returning Series'))[1], 'ИЗМЕНИЛСЯ СТАТУС')
        self.assertEqual(change_type(dict(fingerprint='tmdb:tv:1:date-removed:2026-10-08'))[1], 'ДАТА УТОЧНЯЕТСЯ')
        self.assertEqual(change_type(dict(fingerprint='tmdb:tv:1:date:2026-10-08', title='Дата изменилась'))[1], 'ИЗМЕНИЛИ ДАТУ')

    def test_relative_time_uses_moscow_date_boundary(self):
        current = datetime(2026, 10, 6, 21, 30, tzinfo=timezone.utc)
        self.assertEqual(relative_time('2026-10-06T20:00:00+00:00', current), 'Вчера')
        self.assertEqual(relative_time('2026-10-06T21:01:00+00:00', current), 'Только что')
        self.assertEqual(relative_time('bad', current), '')

    def test_empty_catalog_and_single_slide(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / 'site.db')
            self.addCleanup(store.db.close)
            try:
                cfg = config(Path(directory) / 'site.db')
                html = streaming_home(store, cfg)
                self.assertIn('Хорошее кино ещё впереди.', html)
                self.assertNotIn('Больше всего ждут', html)
                self.assertNotIn('Что изменилось', html)
                self.assertIn('Открыть бота', html)
                with patch.object(store, 'catalog', return_value=[self.item]):
                    html = streaming_home(store, cfg)
                self.assertEqual(html.count('data-slide='), 1)
                self.assertNotIn('data-direction=', html)
                self.assertIn('art-placeholder', html)
            finally:
                store.db.close()

    def test_calendar_ignores_bad_dates_and_uses_season_premiere(self):
        with patch('website.home_state.today', return_value=self.current), patch('website.views.today', return_value=self.current):
            html = premiere_rows([dict(self.item, release_date='bad'), dict(self.item, id=2, season_premiere='2026-10-07', premiere_season=28)], config('unused'))
            self.assertIn('Завтра', html)
            self.assertIn('Новый сезон · 28 сезон, 1 серия', html)
            self.assertNotIn('/title/tv/1', html)
