import unittest
from website.social_images import social_image_url, NAME


class SocialImageTests(unittest.TestCase):
    def test_tmdb_image_gets_own_domain(self):
        self.assertEqual(social_image_url('https://kinojdun.ru', 'https://image.tmdb.org/t/p/w1280/Ab123.jpg'),
                         'https://kinojdun.ru/social-image/Ab123.jpg')

    def test_untrusted_hosts_and_paths_stay_unchanged(self):
        for source in ['https://image.tmdb.org.evil/t/p/w1280/a.jpg',
                       'https://image.tmdb.org/other/a.jpg', 'http://image.tmdb.org/t/p/w1280/a.jpg']:
            self.assertEqual(social_image_url('https://kinojdun.ru', source), source)

    def test_invalid_names_cannot_be_cache_paths(self):
        for name in ['../secret.jpg', 'a.png', 'a.jpg/other', 'a.jpg\n']:
            self.assertIsNone(NAME.fullmatch(name))
