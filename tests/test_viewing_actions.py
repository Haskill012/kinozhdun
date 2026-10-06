import unittest
from datetime import date
from unittest.mock import patch
from shared.viewing import viewing_state
from website.home_state import watch_label, event_state, waiting
from bot.utils.formatting import format_shared_item_prompt
from bot.keyboards.inline import shared_item_recipient_keyboard


class ViewingActionsTests(unittest.TestCase):
    current=date(2026,10,6)

    def tv(self, **kwargs):
        return dict(media_type='tv',status='Returning Series',
                    seasons=[dict(season_number=2,air_date='2026-09-01',episode_count=8)],
                    last_episode_to_air=dict(season_number=2,episode_number=8,air_date='2026-10-01'),**kwargs)

    def test_film_past_today_future_and_unknown(self):
        for raw,label in [('2026-07-31','+ Посмотреть позже'),('2026-10-06','+ Посмотреть позже'),
                          ('2026-10-07','+ Ждать премьеру'),(None,'+ Следить за выходом'),('invalid','+ Следить за выходом')]:
            with self.subTest(raw=raw):
                item=dict(media_type='movie',release_date=raw)
                self.assertEqual(viewing_state(item,self.current)['label'],label)
        self.assertEqual(viewing_state(dict(media_type='movie',status='Released'),self.current)['mode'],'save')

    def test_weekly_series_waits_for_actual_episode_not_new_season(self):
        item=self.tv(next_episode_to_air=dict(season_number=2,episode_number=7,air_date='2026-10-08'))
        item['last_episode_to_air']['episode_number']=6
        state=viewing_state(item,self.current)
        self.assertEqual((state['label'],state['season'],state['episode']),('+ Ждать серию',2,7))
        self.assertEqual(state['status'],'Сезон выходит')

    def test_premiere_first_season_and_returning_season(self):
        for number,label in [(1,'+ Ждать премьеру'),(3,'+ Ждать сезон')]:
            item=self.tv(next_episode_to_air=dict(season_number=number,episode_number=1,air_date='2026-10-09'))
            self.assertEqual(viewing_state(item,self.current)['label'],label)

    def test_today_episode_does_not_claim_all_episodes_are_available(self):
        item=self.tv(next_episode_to_air=dict(season_number=2,episode_number=8,air_date='2026-10-06'))
        state=viewing_state(item,self.current)
        self.assertEqual(state['label'],'+ Следить за сериями')
        self.assertNotIn('Все серии',state['status'])

    def test_complete_season_and_batch_release_can_be_saved(self):
        for last in ('2026-10-01','2026-09-01'):
            item=self.tv();item['last_episode_to_air']['air_date']=last
            state=viewing_state(item,self.current)
            self.assertEqual(state['label'],'+ Посмотреть позже')
            self.assertEqual(state['status'],'Все серии 2-го сезона вышли')
            with patch('website.home_state.today',return_value=self.current):
                self.assertFalse(waiting(item))
                self.assertEqual(event_state(item)['headline'],state['status'])

    def test_no_next_episode_is_not_proof_of_finale(self):
        item=self.tv();item['last_episode_to_air']['episode_number']=6
        state=viewing_state(item,self.current)
        self.assertEqual(state['label'],'+ Следить за сериями')
        self.assertNotIn('Все серии',state['status'])
        item.pop('seasons')
        self.assertEqual(viewing_state(item,self.current)['label'],'+ Следить за продолжением')

    def test_future_season_and_undated_announced_season(self):
        item=self.tv()
        item['seasons'].append(dict(season_number=3,air_date='2027-01-01',episode_count=10))
        self.assertEqual(viewing_state(item,self.current)['label'],'+ Ждать сезон')
        item['seasons'][-1]['air_date']=None
        self.assertEqual(viewing_state(item,self.current)['label'],'+ Следить за продолжением')

    def test_specials_and_zero_counts_are_not_completed_seasons(self):
        item=self.tv();item['seasons'][0]['episode_count']=0
        self.assertNotEqual(viewing_state(item,self.current)['mode'],'save')
        item['seasons'][0]['season_number']=0
        self.assertNotEqual(viewing_state(item,self.current)['mode'],'save')

    def test_terminal_series_overrides_stale_future_episode(self):
        for status in ('Ended','Canceled'):
            item=self.tv();item['status']=status
            item['next_episode_to_air']=dict(season_number=3,episode_number=1,air_date='2027-01-01')
            self.assertEqual(viewing_state(item,self.current)['label'],'+ Посмотреть позже')

    def test_catalogue_and_bot_have_same_action_and_no_past_premiere_promise(self):
        item=dict(media_type='movie',release_date='2026-07-31',status='Released',title='Фильм',tmdb_id=1)
        with patch('website.home_state.today',return_value=self.current):
            self.assertEqual(watch_label(item),'+ Посмотреть позже')
            self.assertEqual(watch_label(dict(item,is_waiting=True)),'✓ В списке')
        text=format_shared_item_prompt('Фильм',item,'movie')
        self.assertIn('Посмотреть позже',text)
        self.assertNotIn('официальная дата премьеры',text)
        kb=shared_item_recipient_keyboard('movie',1,action_label=viewing_state(item,self.current)['label'])
        self.assertEqual(kb.inline_keyboard[0][0].text,'+ Посмотреть позже')
        self.assertEqual(kb.inline_keyboard[0][0].callback_data,'track_from_share:movie:1')
