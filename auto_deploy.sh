#!/bin/bash
set -e

echo "=== [КиноЖдун] Настройка автоматического развертывания ==="

APP_DIR="/root/kinozhdun"
if [ ! -d "$APP_DIR" ]; then
    echo "Директория $APP_DIR не найдена. Клонируем..."
    git clone https://github.com/Haskill012/kinozhdun.git "$APP_DIR"
fi

cd "$APP_DIR"

echo "=== Получение свежего кода из GitHub ==="
git fetch origin master
git reset --hard origin/master

echo "=== Сборка и перезапуск Docker контейнеров ==="
docker compose up -d --build

echo "=== Установка автообновления каждые 2 минуты ==="
DEPLOY_SCRIPT="$APP_DIR/deploy_cron.sh"
cat << 'EOF' > "$DEPLOY_SCRIPT"
#!/bin/bash
cd /root/kinozhdun || exit 1
git fetch origin master > /dev/null 2>&1
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/master)
if [ "$LOCAL" != "$REMOTE" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') New commit detected ($REMOTE). Updating..." >> /var/log/kinozhdun_deploy.log
    git reset --hard origin/master >> /var/log/kinozhdun_deploy.log 2>&1
    docker compose up -d --build >> /var/log/kinozhdun_deploy.log 2>&1
    echo "$(date '+%Y-%m-%d %H:%M:%S') Update complete." >> /var/log/kinozhdun_deploy.log
fi
EOF

chmod +x "$DEPLOY_SCRIPT"

# Добавляем в crontab, если еще не добавлено
(crontab -l 2>/dev/null | grep -F -v "deploy_cron.sh" ; echo "*/2 * * * * /root/kinozhdun/deploy_cron.sh") | crontab -

echo "=========================================================="
echo "УСПЕХ! Сайт и бот обновлены."
echo "Автообновление установлено: теперь при каждом пуше в GitHub"
echo "сервер сам обновится в течение 2 минут без вашего участия!"
echo "=========================================================="
