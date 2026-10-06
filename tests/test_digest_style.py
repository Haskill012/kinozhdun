import unittest
from datetime import date
from unittest.mock import AsyncMock, Mock
from html.parser import HTMLParser
from bot.config import Settings
from bot.services.channel import ChannelPublisher, channel_post_keyboard
from bot.services.digest_style import render_digest, telegram_text_length


class DigestStyleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.item = {"media_type": "tv", "tmdb_id": 125988, "title": "Tom & Jerry",
                     "vote_average": 8.4, "vote_count": 100, "tag": "3 сезон · 4 серия",
                     "network": "Apple TV+"}
        self.settings = Settings(TELEGRAM_BOT_TOKEN="test", TMDB_API_KEY="test")

    def test_links_rating_short_layout_and_buttons(self):
        text = render_digest([self.item], "06.10.2026")
        self.assertIn('href="https://kinojdun.ru/title/tv/125988"', text)
        self.assertIn('Tom &amp; Jerry', text)
        self.assertIn('★ 8.4/10 · TMDB', text)
        self.assertIn('3 сезон · 4 серия · Apple TV+', text)
        self.assertNotIn('└', text)
        self.assertNotIn('Не хотите', text)
        kb = channel_post_keyboard(1, 'kinojdun_bot', 'Digest', post_type='daily_digest', site_url='https://kinojdun.ru/')
        self.assertEqual(len(kb.inline_keyboard), 2)
        self.assertEqual(kb.inline_keyboard[0][0].url, 'https://kinojdun.ru/calendar')
        self.assertIn('Настроить напоминания', kb.inline_keyboard[1][0].text)

    def test_unrated_and_small_sample_honest_labels(self):
        self.assertIn('пока без оценки', render_digest([{**self.item, 'vote_count': 0}], 'Date'))
        self.assertIn('мало оценок', render_digest([{**self.item, 'vote_count': 12}], 'Date'))

    def test_caption_budget_preserves_complete_html(self):
        items = [{**self.item, 'title': 'Movie 😀 & < > ' * 20, 'network': 'N' * 35,
                  'tag': 'A' * 150} for _ in range(5)]
        text = render_digest(items, 'Date', weekly=True)
        self.assertLessEqual(telegram_text_length(text), 1000)
        self.assertEqual(text.count('<a '), text.count('</a>'))
        self.assertTrue(text.endswith('</a>'))
        HTMLParser().feed(text)

    async def test_raw_html_over_1024_still_sends_full_valid_caption(self):
        text = render_digest([{**self.item, 'title': '&' * 60} for _ in range(5)], 'Date')
        self.assertGreater(len(text), 1024)
        self.assertLess(telegram_text_length(text), 1024)
        bot = Mock(send_photo=AsyncMock(return_value=Mock(message_id=1)))
        publisher = ChannelPublisher(None, self.settings, bot)
        await publisher._send_post_to_telegram('@channel', text, '/landscape.jpg', Mock())
        self.assertEqual(bot.send_photo.await_args.kwargs['caption'], text)

    async def test_actual_episode_date_rating_backdrop_and_talk_show_filter(self):
        episode = {'season_number': 3, 'episode_number': 4, 'air_date': '2026-10-06'}
        details = {'title': 'Укрытие', 'vote_average': 8.4, 'vote_count': 100,
                   'backdrop_path': '/wide.jpg', 'next_episode_to_air': episode}
        tmdb = Mock(get_tv_details=AsyncMock(return_value=details),
                    get_tv_season=AsyncMock(return_value={'episodes': [episode]}))
        publisher = ChannelPublisher(None, self.settings, Mock(), tmdb_client=tmdb)
        enriched = await publisher.enrich_digest_items([self.item], date(2026,10,6),date(2026,10,6))
        self.assertEqual(enriched[0]['tag'], '3 сезон · 4 серия')
        self.assertEqual(enriched[0]['backdrop_path'], '/wide.jpg')
        self.assertEqual(enriched[0]['vote_average'],8.4)
        self.assertEqual(await publisher.enrich_digest_items([self.item],date(2026,10,7),date(2026,10,7)), [])
        details['type'] = 'Talk Show'
        self.assertEqual(await publisher.enrich_digest_items([self.item],date(2026,10,6),date(2026,10,6)), [])

    async def test_weekly_releases_outside_week_are_excluded(self):
        tmdb = Mock(get_movie_details=AsyncMock(return_value={
            'title':'Movie', 'release_date':'2027-01-01', 'vote_count':0}))
        publisher=ChannelPublisher(None,self.settings,Mock(),tmdb_client=tmdb)
        item={**self.item,'media_type':'movie'}
        self.assertEqual(await publisher.enrich_digest_items([item],date(2026,10,6),date(2026,10,12)),[])

    async def test_untranslated_foreign_titles_and_low_ratings_are_excluded(self):
        episode = {'season_number': 1, 'episode_number': 1, 'air_date': '2026-10-06'}
        chinese_details = {'name': '兰香如故', 'original_name': '兰香如故', 'vote_average': 7.5,
                           'vote_count': 100, 'backdrop_path': '/img.jpg', 'next_episode_to_air': episode}
        tmdb = Mock(get_tv_details=AsyncMock(return_value=chinese_details),
                    get_tv_season=AsyncMock(return_value={'episodes': [episode]}))
        publisher = ChannelPublisher(None, self.settings, Mock(), tmdb_client=tmdb)
        # Chinese title with no cyrillic/latin translation must be excluded
        res = await publisher.enrich_digest_items([{'media_type': 'tv', 'tmdb_id': 999}], date(2026, 10, 6), date(2026, 10, 6))
        self.assertEqual(res, [])

        # Low rating (e.g. 4.5 with 20 votes) must be excluded
        low_rated = {'title': 'Bad Movie', 'vote_average': 4.5, 'vote_count': 25,
                     'release_date': '2026-10-06', 'backdrop_path': '/img.jpg'}
        tmdb_movie = Mock(get_movie_details=AsyncMock(return_value=low_rated))
        pub_movie = ChannelPublisher(None, self.settings, Mock(), tmdb_client=tmdb_movie)
        res_movie = await pub_movie.enrich_digest_items([{'media_type': 'movie', 'tmdb_id': 888}], date(2026, 10, 6), date(2026, 10, 6))
        self.assertEqual(res_movie, [])
