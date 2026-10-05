#!/bin/bash
set -e

echo "=== Клонирование репозитория КиноЖдун ==="
cd /root
rm -rf kinozhdun
git clone https://github.com/Haskill012/kinozhdun.git
cd kinozhdun

echo "=== Создание боевого .env ==="
cat << 'EOF' > .env
TELEGRAM_BOT_TOKEN=8859530073:AAGIWKxhkuLJTLUXnVFnNMRzLKhqAVd5M_U
TMDB_API_KEY=3fd2be6f0c70a2a598f084ddfb75487c
TMDB_BASE_URL=https://api.themoviedb.org/3
DATABASE_URL=sqlite+aiosqlite:///./data/kinozhdun.db
CHECK_INTERVAL_HOURS=6
ANNOUNCED_CHECK_INTERVAL_HOURS=2
MAX_ITEMS_PER_USER=50
TMDB_IMAGE_BASE_URL=https://image.tmdb.org/t/p/w500

TELEGRAM_CHANNEL_ID=@kinojdun_channel
CHANNEL_POSTING_ENABLED=true
CHANNEL_AUTO_PUBLISH=true
CHANNEL_MIN_POST_INTERVAL_MINUTES=15
ADMIN_USER_IDS=330413281

DAILY_DIGEST_ENABLED=true
DAILY_DIGEST_HOUR=9
WEEKLY_DIGEST_ENABLED=true
WEEKLY_DIGEST_DAY=0
WEEKLY_DIGEST_HOUR=10

SITE_HOST=0.0.0.0
SITE_PORT=8099
SITE_BASE_URL=https://kinojdun.ru
SITE_PUBLIC=true
SITE_CHANNEL_URL=https://t.me/kinojdun_channel
SITE_SYNC_INTERVAL_MINUTES=60
SITE_BATCH_SIZE=12
SITE_YANDEX_METRIKA_ID=113425218
EOF

echo "=== Сборка и запуск контейнеров ==="
docker compose down || true
docker compose up -d --build

echo "=== Проверка статуса сервисов ==="
sleep 5
docker compose ps

echo "================================================="
echo "ГОТОВО! Бот и сайт успешно запущены на сервере!"
echo "================================================="
