"""Track delivery truthfully. Telegram sync observes existing posts and sends no copies."""
import datetime
import hashlib
import json
import logging
from typing import Optional
import aiohttp
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from bot.config import Settings
from bot.db.models import DzenPost
from bot.db.repositories import Repository
from bot.services.social_editorial import moscow_today

logger = logging.getLogger(__name__)


class DzenPublisher:
    def __init__(self, session_factory, settings: Settings, http_session=None, tmdb_client=None, bot=None):
        self.session_factory, self.settings = session_factory, settings
        self.http_session, self.tmdb_client, self.bot = http_session, tmdb_client, bot
        self._owns_http_session = False

    def is_configured(self):
        return bool(self.settings.DZEN_POSTING_ENABLED)

    async def _get_http_session(self):
        if self.http_session is None or self.http_session.closed:
            self.http_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
            self._owns_http_session = True
        return self.http_session

    async def close(self):
        if self._owns_http_session and self.http_session:
            await self.http_session.close()

    def get_poster_url(self, poster_path_or_url):
        if not poster_path_or_url or poster_path_or_url.startswith(('https://', 'http://')):
            return poster_path_or_url
        return self.settings.TMDB_IMAGE_BASE_URL.rstrip('/') + '/' + poster_path_or_url.lstrip('/')

    async def can_publish_now(self, repo):
        last = await repo.get_last_published_dzen_post()
        if not last or not last.published_at:
            return True
        elapsed = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - last.published_at).total_seconds()
        return elapsed >= self.settings.DZEN_MIN_POST_INTERVAL_MINUTES * 60

    async def _send_to_dzen(self, title, text, poster_url=None, post_type='news'):
        mode = self.settings.DZEN_SYNC_MODE
        if mode == 'telegram_sync':
            return {'success': False, 'error': 'shared_channel_only', 'mode': mode,
                    'note': 'Sync observes the existing Telegram post; a second channel post is forbidden.'}
        if mode == 'rss':
            return {'success': True, 'delivery_status': 'prepared', 'mode': mode,
                    'note': 'Draft prepared in the journal. The website RSS feed is separate; native publication is not confirmed.'}
        if mode != 'webhook' or not self.settings.DZEN_WEBHOOK_URL:
            return {'success': False, 'error': 'unsupported_or_unconfigured_delivery', 'mode': mode}
        session = await self._get_http_session()
        try:
            payload = dict(title=title, text=text, poster_url=poster_url,
                           post_type=post_type, channel_id=self.settings.DZEN_CHANNEL_ID)
            async with session.post(self.settings.DZEN_WEBHOOK_URL, json=payload) as response:
                if response.status not in (200, 201, 202):
                    return {'success': False, 'error': f'HTTP {response.status}'}
                data = await response.json()
                if data.get('success') is False:
                    return {'success': False, 'error': 'gateway_rejected'}
                ident = data.get('publication_id') or data.get('id')
                confirmed = data.get('status') == 'published' and bool(ident)
                return {'success': True, 'publication_id': str(ident) if ident else None,
                        'delivery_status': 'published' if confirmed else 'submitted', 'mode': mode}
        except Exception as exc:
            # No credential-bearing URLs or response bodies in logs.
            logger.warning('Dzen delivery failed: %s', type(exc).__name__)
            return {'success': False, 'error': type(exc).__name__}

    async def observe_channel_post(self, post, message_id, repo):
        """Persist the original Telegram ID without claiming native Dzen publication."""
        if not self.is_configured() or self.settings.DZEN_SYNC_MODE != 'telegram_sync':
            return
        digest = hashlib.sha256(f'telegram-sync:{self.settings.TELEGRAM_CHANNEL_ID}:{message_id}'.encode()).hexdigest()
        await repo.record_dzen_post(digest, post.title, post.event_type, post_type=post.post_type,
                                   tmdb_id=post.tmdb_id, media_type=post.media_type,
                                   post_text=post.post_text, poster_path=post.poster_path,
                                   dzen_publication_id=f'tg_sync:{message_id}', status='forwarded')

    async def _deliver_record(self, post_id):
        async with self.session_factory() as session:
            claim = await session.execute(update(DzenPost).where(
                DzenPost.id == post_id, DzenPost.status == 'pending').values(status='sending'))
            await session.commit()
            if claim.rowcount != 1:
                return False
            post = await session.get(DzenPost, post_id)
            result = await self._send_to_dzen(post.title, post.post_text or post.title,
                                              self.get_poster_url(post.poster_path), post.post_type)
            post.status = result.get('delivery_status', 'submitted') if result.get('success') else 'failed'
            post.dzen_publication_id = result.get('publication_id')
            if result.get('success'):
                post.published_at = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
            await session.commit()
            return bool(result.get('success'))

    async def publish_event(self, title, media_type='movie', event_type='announced', tmdb_id=None,
                            season_number=None, air_date=None, genres=None, network=None,
                            overview=None, poster_path=None, trailer_url=None, force=False,
                            episode_number=None, source_url=None):
        if not self.is_configured():
            return None
        if self.settings.DZEN_SYNC_MODE == 'telegram_sync':
            logger.info('Dzen uses the existing Telegram stream; separate event skipped.')
            return None
        from bot.services.dzen_publisher import format_dzen_post_text
        from bot.services.channel import generate_event_fingerprint
        fingerprint = generate_event_fingerprint(tmdb_id, media_type, event_type, season_number,
                                                 air_date.isoformat() if air_date else 'nodate')
        text = format_dzen_post_text(title, media_type, event_type, season_number, air_date, network,
                                     overview, genres, trailer_url=trailer_url,
                                     site_url=self.settings.SITE_BASE_URL, bot_username=self.settings.BOT_USERNAME,
                                     tmdb_id=tmdb_id, episode_number=episode_number, source_url=source_url)
        async with self.session_factory() as session:
            repo = Repository(session)
            if await repo.is_dzen_post_exists(fingerprint):
                return None
            try:
                post = await repo.record_dzen_post(fingerprint, title, event_type, tmdb_id=tmdb_id,
                                                   media_type=media_type, post_text=text,
                                                   poster_path=poster_path, status='pending')
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return None
            ident = post.id
            can_send = force or (self.settings.DZEN_AUTO_PUBLISH and await self.can_publish_now(repo))
        if can_send:
            await self._deliver_record(ident)
        async with self.session_factory() as session:
            return await session.get(DzenPost, ident)

    async def _create_digest(self, start, end, weekly, force):
        if not self.is_configured() or self.settings.DZEN_SYNC_MODE == 'telegram_sync':
            return None
        from bot.services.channel import ChannelPublisher, generate_event_fingerprint
        from bot.services.dzen_publisher import format_dzen_daily_digest, format_dzen_weekly_digest
        async with self.session_factory() as session:
            repo = Repository(session)
            tracked = await repo.get_items_releasing_between(start, end)
            items = [{'title': i.title, 'media_type': i.media_type, 'tmdb_id': i.tmdb_id,
                      'network': i.network, 'poster_path': i.poster_path,
                      'release_date': (i.next_air_date or i.custom_date).isoformat(),
                      'date_str': (i.next_air_date or i.custom_date).strftime('%d.%m.%Y'),
                      'tag': 'премьера фильма' if i.media_type == 'movie' else
                             f'старт {i.next_season_number} сезона' if i.next_season_number else 'новый сериал'} for i in tracked]
            validator = ChannelPublisher(self.session_factory, self.settings, self.bot, self.tmdb_client)
            items = await validator.enrich_digest_items(items, start, end)
            if len(items) < (2 if weekly else 1):
                return None
            kind = 'weekly_digest' if weekly else 'daily_digest'
            fingerprint = generate_event_fingerprint(None, None, kind, extra_key=f'dzen:v2:{start}')
            if await repo.is_dzen_post_exists(fingerprint):
                return None
            label = f'{start:%d.%m.%Y} – {end:%d.%m.%Y}' if weekly else f'{start:%d.%m.%Y}'
            text = (format_dzen_weekly_digest if weekly else format_dzen_daily_digest)(items, label, self.settings.SITE_BASE_URL, self.settings.BOT_USERNAME)
            post = await repo.record_dzen_post(fingerprint, f'Премьеры: {label}', kind,
                                               post_type=kind, post_text=text, status='pending')
            await session.commit()
            ident = post.id
            can_send = force or (self.settings.DZEN_AUTO_PUBLISH and await self.can_publish_now(repo))
        if can_send:
            await self._deliver_record(ident)
        async with self.session_factory() as session:
            return await session.get(DzenPost, ident)

    async def create_daily_digest(self, target_date=None, force=False):
        target = target_date or moscow_today()
        return await self._create_digest(target, target, False, force)

    async def create_weekly_digest(self, start_date=None, force=False):
        start = start_date or moscow_today()
        return await self._create_digest(start, start + datetime.timedelta(days=6), True, force)

    async def publish_pending_queue(self):
        if not self.is_configured() or not self.settings.DZEN_AUTO_PUBLISH or self.settings.DZEN_SYNC_MODE == 'telegram_sync':
            return 0
        async with self.session_factory() as session:
            repo = Repository(session)
            if not await self.can_publish_now(repo):
                return 0
            pending = await repo.get_pending_dzen_posts()
            ident = pending[0].id if pending else None
        return int(await self._deliver_record(ident)) if ident else 0

    async def publish_test_post(self):
        # A connectivity check must not pollute the production Telegram stream.
        return {'title': 'Тестовое подключение Дзена',
                'result': {'success': False, 'error': 'production_test_disabled',
                           'note': 'Use preview and inspect the final Dzen channel; no test post was sent.'},
                'mode': self.settings.DZEN_SYNC_MODE, 'enabled': self.is_configured()}
