"""Reader-facing copy for source events; archived URLs and evidence stay stable."""
import json
import re
from datetime import date

STATUS_LABELS = {'Canceled': 'проект закрыт', 'Ended': 'история завершена',
                 'In Production': 'проект в производстве', 'Post Production': 'идёт постпродакшн',
                 'Released': 'проект вышел', 'Returning Series': 'сериал продолжается',
                 'Planned': 'проект запланирован', 'Rumored': 'проект обсуждается'}


def reader_text(text):
    replacements = {
        'По данным каталога TMDB': 'По расписанию', 'Согласно каталогу TMDB': 'По расписанию',
        'по данным TMDB': 'по расписанию', 'По данным TMDB': 'По расписанию',
        'В каталоге TMDB': 'В расписании', 'в каталоге TMDB': 'в расписании',
        'В текущей записи TMDB больше нет прежней даты следующего выхода.': 'Дата следующего выхода пока уточняется.',
        'Сегодняшняя дата выхода была указана в предыдущем снимке TMDB.': 'Выход был запланирован на сегодня.',
        'В предыдущем снимке каталога выход был указан на': 'Ранее выход был запланирован на',
        'Текущая запись уже изменилась.': 'Расписание обновилось.',
        'Это запись каталога, а не гарантия доступности на конкретной платформе.': 'Уточняйте доступность на своей платформе.',
        'При автоматической проверке обнаружено изменение статуса': 'Статус проекта изменился',
        'с отметкой official': '', 'типа Trailer': '',
        'TMDB': 'источнике', 'снимок выбранных проектов': 'копию списка',
        'автоматическая редакция': 'КиноЖдун',
    }
    for before, after in replacements.items():
        text = text.replace(before, after)
    return re.sub(r' {2,}', ' ', text).replace(' .', '.').strip()


def public_article(article):
    article = dict(article)
    for key in ('title', 'summary'):
        article[key] = reader_text(article[key])
    article['body'] = json.dumps([reader_text(p) for p in json.loads(article['body'])], ensure_ascii=False)
    guides = {
        'guide:tracking': [
            'Не нужно искать новости о любимом сериале каждый день. Сохраните его в КиноЖдуне — список ожидания всегда будет под рукой.',
            'Найдите сериал на сайте, нажмите «+ Ждать» и подтвердите добавление в Telegram. Или отправьте название прямо боту и выберите нужную карточку.',
            'Бот следит за изменениями и напоминает о выходе. Когда новый сезон появится в расписании, его дату можно будет посмотреть в карточке проекта.'],
        'guide:calendar': [
            'Международная, российская и цифровая премьеры могут приходиться на разные даты. Перед просмотром уточните доступность фильма в своём кинотеатре или на своей платформе.',
            'Календарь помогает спланировать просмотр: в нём собраны премьеры фильмов, старты сезонов и ближайшие новые серии. Если расписание изменится, дата обновится в карточке.',
            'Добавьте проект в свой список в Telegram, чтобы получать напоминания. Для личных планов можно задать свою дату.'],
        'guide:watchlist': [
            'Сохраняйте всё, что хочется посмотреть, в одном списке. Откройте «Мой Кинождун» в Telegram — ваши фильмы и сериалы всегда рядом.',
            'Нажмите «Поделиться списком», чтобы отправить другу копию выбранных проектов. Получатель сможет добавить их себе, а ваш личный профиль останется закрытым.',
            'Удаляйте проекты, которые больше не ждёте, и добавляйте новые. Бот напомнит о премьере, когда подойдёт время.'],
    }
    if article.get('fingerprint') in guides:
        article['body'] = json.dumps(guides[article['fingerprint']], ensure_ascii=False)
    event = re.match(r'^tmdb:(movie|tv):\d+:(status|release|trailer):(.+)$', article.get('fingerprint', ''))
    name = re.match(r'^«(.+?)»', article['title'])
    if event and name:
        if event[2] == 'status':
            status = STATUS_LABELS.get(event[3], 'изменился статус проекта')
            article['title'] = f'«{name[1]}»: {status}'
            article['summary'] = f'«{name[1]}»: {status}. Добавьте проект в список ожидания, чтобы следить за новостями.'
            article['body'] = json.dumps([f'Статус проекта обновился: {status}.',
                                         'Даты выхода и последние новости собраны в карточке проекта.'], ensure_ascii=False)
        elif event[2] == 'trailer':
            article['title'] = f'«{name[1]}»: смотрите новый трейлер'
            article['summary'] = 'Трейлер уже в карточке проекта. Посмотрите ролик и решите, стоит ли добавить проект в свой список.'
        elif article.get('release_date'):
            try:
                released = date.fromisoformat(article['release_date']).strftime('%d.%m.%Y')
            except ValueError:
                return article
            episode = re.search(r'Речь о (\d+)-м эпизоде (\d+)-го сезона', article['summary'])
            label = f'{episode[2]}-й сезон, {episode[1]}-я серия' if episode else 'выход по расписанию'
            article['title'] = f'«{name[1]}»: {label} — в календаре на {released}'
    return article
