from apscheduler.schedulers.asyncio import AsyncIOScheduler
from max_bot.scheduler import check_updates_job, check_reminders_job, check_episode_reminders_job


def setup_scheduler(client, session_factory, tmdb, settings):
    scheduler = AsyncIOScheduler(timezone='Europe/Moscow')
    scheduler.add_job(check_updates_job, 'interval', hours=settings.CHECK_INTERVAL_HOURS,
                      args=[client,session_factory,tmdb,settings], id='vk_updates', max_instances=1, coalesce=True)
    scheduler.add_job(check_reminders_job, 'cron', hour=11,
                      args=[client,session_factory,settings], id='vk_reminders', max_instances=1, coalesce=True)
    scheduler.add_job(check_episode_reminders_job, 'cron', hour='10-21', minute=15,
                      args=[client,session_factory,tmdb,settings], id='vk_episodes', max_instances=1, coalesce=True)
    return scheduler
