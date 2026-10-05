#!/bin/bash
set -e

echo "=== Получение/обновление репозитория КиноЖдун ==="
if [ -d "/root/kinozhdun/.git" ]; then
    cd /root/kinozhdun
    git fetch origin master
    git reset --hard origin/master
else
    cd /root
    git clone https://github.com/Haskill012/kinozhdun.git
    cd kinozhdun
fi

echo "=== Проверка конфигурации .env ==="
if [ ! -f .env ]; then
    (umask 077; cp .env.example .env)
    echo "Создан шаблон /root/kinozhdun/.env. Заполните токены и настройки перед запуском."
    exit 1
fi
chmod 600 .env
# Read only the credential lines; never execute .env as a shell script.
for key in TELEGRAM_BOT_TOKEN TMDB_API_KEY; do
    value=$(sed -n "s/^${key}=//p" .env | tail -n 1 | tr -d '\r')
    case "$value" in
        ""|your_telegram_bot_token_here|your_tmdb_api_key_here)
            echo "Заполните $key в /root/kinozhdun/.env перед запуском."
            exit 1
            ;;
    esac
done
unset value

echo "=== Сборка и запуск контейнеров ==="
docker compose down || true
docker compose up -d --build

echo "=== Проверка статуса сервисов ==="
sleep 5
docker compose ps

echo "================================================="
echo "ГОТОВО! Бот и сайт успешно запущены на сервере!"
echo "================================================="
