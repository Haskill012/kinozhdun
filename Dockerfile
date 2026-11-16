FROM python:3.11-slim

# Установка переменных окружения для Python
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Moscow

# Рабочая директория
WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование исходного кода приложения
COPY bot/ ./bot/
COPY website/ ./website/
COPY shared/ ./shared/
COPY max_bot/ ./max_bot/
COPY vk_bot/ ./vk_bot/

# Создание директории для базы данных и шортсов
RUN mkdir -p /app/data /app/output

# Запуск бота
CMD ["python", "-m", "bot"]
