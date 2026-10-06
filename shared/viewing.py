"""Viewer actions based on confirmed release dates and episode facts."""
from datetime import date, datetime, timezone, timedelta


def parsed(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def viewing_state(item, current=None):
    current = current or datetime.now(timezone(timedelta(hours=3))).date()
    def result(mode, status, label, note, when=None, season=None, episode=None):
        return dict(mode=mode, status=status, label=label, note=note,
                    date=when, season=season, episode=episode)
    if item.get('media_type') == 'movie':
        released = parsed(item.get('release_date') or item.get('first_release'))
        if released and released > current:
            return result('premiere', 'Скоро премьера', '+ Ждать премьеру',
                          'Сохраните фильм в Telegram. Бот напомнит о предстоящей премьере.', released)
        if released or item.get('status') == 'Released':
            return result('save', 'Премьера сегодня' if released == current else 'Уже вышел',
                          '+ Посмотреть позже', 'Сохраните фильм в свой список в Telegram, чтобы посмотреть позже.')
        return result('follow', 'Дата выхода пока неизвестна', '+ Следить за выходом',
                      'Добавьте фильм в Telegram. Сообщим, когда появится дата выхода.')

    status = item.get('status')
    if status in ('Ended', 'Canceled'):
        return result('save', 'Сериал завершён' if status == 'Ended' else 'Сериал закрыт',
                      '+ Посмотреть позже', 'Сохраните сериал в свой список в Telegram, чтобы посмотреть позже.')
    next_ep = item.get('next_episode_to_air') or {}
    when = parsed(next_ep.get('air_date') or item.get('release_date'))
    season = next_ep.get('season_number') or item.get('season')
    episode = next_ep.get('episode_number') or item.get('episode')
    seasons = [s for s in item.get('seasons') or [] if (s.get('season_number') or 0) > 0]
    future = [(parsed(s.get('air_date')), s['season_number']) for s in seasons
              if parsed(s.get('air_date')) and parsed(s['air_date']) >= current]
    premiere = parsed(item.get('season_premiere'))
    if premiere and premiere >= current and item.get('premiere_season'):
        future.append((premiere, item['premiere_season']))
    first = parsed(item.get('first_air_date') or item.get('first_release'))
    if not future and first and first >= current and not when:
        future.append((first, 1))
    if future:
        first, number = min(future)
        if not when or when < current or first <= when:
            when, season, episode = first, number, 1
    if when and when >= current:
        if episode == 1:
            label = '+ Ждать сезон' if season and season > 1 else '+ Ждать премьеру'
            text = 'Сезон начинается сегодня' if when == current else 'Скоро новый сезон' if season and season > 1 else 'Скоро премьера сериала'
        else:
            label = '+ Следить за сериями' if when == current else '+ Ждать серию'
            text = 'Новая серия сегодня' if when == current else 'Сезон выходит'
        return result('episode', text, label,
                      'Добавьте сериал в Telegram. Бот сообщит о выходе новых серий и изменениях расписания.', when, season, episode)
    last = item.get('last_episode_to_air') or {}
    last_date = parsed(last.get('air_date'))
    started = [s for s in seasons if parsed(s.get('air_date')) and parsed(s['air_date']) < current]
    latest = max(started, key=lambda s:s['season_number']) if started else None
    if latest and any(s['season_number'] > latest['season_number'] and not parsed(s.get('air_date')) for s in seasons):
        return result('follow', 'Новый сезон: дата пока неизвестна', '+ Следить за продолжением',
                      'Добавьте сериал в Telegram. Сообщим, когда появится дата нового сезона.')
    if (latest and last_date and last_date < current and last.get('season_number') == latest['season_number']
            and (latest.get('episode_count') or 0) > 0 and last.get('episode_number') == latest['episode_count']):
        return result('save', f"Все серии {latest['season_number']}-го сезона вышли", '+ Посмотреть позже',
                      'Сохраните сериал в Telegram. Если появятся новости о продолжении, бот сообщит об этом.')
    if last_date and status == 'Returning Series' and latest and (last.get('episode_number') or 0) < (latest.get('episode_count') or 0):
        return result('follow', 'Расписание следующих серий уточняется', '+ Следить за сериями',
                      'Добавьте сериал в Telegram. Сообщим, когда появится дата следующей серии.')
    return result('follow', 'Дата продолжения пока неизвестна' if status == 'Returning Series' else 'Дата выхода пока неизвестна',
                  '+ Следить за продолжением' if status == 'Returning Series' else '+ Следить за выходом',
                  'Добавьте сериал в Telegram. Сообщим, когда появятся сведения о следующем выходе.')
