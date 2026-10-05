#!/bin/bash
set -e

echo "=========================================================="
echo "  КиноЖдун — полная настройка сервера (одноразовый запуск)"
echo "=========================================================="

# ===== 1. SSH-ключи для удалённого управления =====
echo ""
echo "=== [1/4] Настройка SSH-доступа для автоматизации ==="
mkdir -p /root/.ssh
chmod 700 /root/.ssh
touch /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

DEPLOY_KEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIH5nQoQJv2dVX903+h9xBfxAOdiPAlIFgAPf83hvQEQ2 antigravity-deploy"

if ! grep -qF "antigravity-deploy" /root/.ssh/authorized_keys 2>/dev/null; then
    echo "$DEPLOY_KEY" >> /root/.ssh/authorized_keys
    echo "  SSH-ключ antigravity-deploy добавлен"
else
    echo "  SSH-ключ antigravity-deploy уже установлен"
fi

# ===== 2. Клонирование / обновление репозитория =====
echo ""
echo "=== [2/4] Получение кода из GitHub ==="
APP_DIR="/root/kinozhdun"
if [ ! -d "$APP_DIR/.git" ]; then
    # git clone refuses a nonempty directory, preserving existing .env/data.
    git clone https://github.com/Haskill012/kinozhdun.git "$APP_DIR"
    echo "  Репозиторий склонирован"
else
    cd "$APP_DIR"
    git fetch origin master
    git reset --hard origin/master
    echo "  Код обновлён до последнего коммита"
fi

cd "$APP_DIR"

# ===== 3. Сборка и запуск контейнеров =====
echo ""
echo "=== [3/4] Сборка и запуск Docker-контейнеров ==="
docker compose up -d --build
echo "  Контейнеры запущены"

# ===== 4. Автодеплой по cron =====
echo ""
echo "=== [4/4] Настройка автоматического обновления ==="
cat << 'CRONSCRIPT' > "$APP_DIR/deploy_cron.sh"
#!/bin/bash
set -euo pipefail
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
cd /root/kinozhdun || exit 1
exec >> /var/log/kinozhdun_deploy.log 2>&1
# Prevent overlapping builds, and retry a failed deployment next cycle.
exec 9>/root/kinozhdun_deploy.lock
flock -n 9 || exit 0
git fetch origin master
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/master)
DEPLOYED=$(cat data/.deployed_revision 2>/dev/null || true)
if [ "$LOCAL" != "$REMOTE" ] || [ "$DEPLOYED" != "$REMOTE" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') Развёртываю $REMOTE..."
    git merge --ff-only origin/master
    docker compose up -d --build
    printf '%s\n' "$REMOTE" > data/.deployed_revision
    echo "$(date '+%Y-%m-%d %H:%M:%S') Обновление завершено."
fi
CRONSCRIPT
chmod +x "$APP_DIR/deploy_cron.sh"

(crontab -l 2>/dev/null | grep -F -v "deploy_cron.sh" || true; echo "*/2 * * * * /root/kinozhdun/deploy_cron.sh") | crontab -
echo "  Автообновление каждые 2 минуты установлено"

echo ""
echo "=========================================================="
echo "  ГОТОВО! Сервер полностью настроен."
echo ""
echo "  SSH-доступ для автоматизации — включён"
echo "  Сайт и бот — запущены"
echo "  Автообновление из GitHub — каждые 2 минуты"
echo ""
echo "  Вам больше НЕ нужно заходить в эту консоль."
echo "  Все обновления будут применяться автоматически."
echo "=========================================================="
