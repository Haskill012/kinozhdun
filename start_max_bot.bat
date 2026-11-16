@echo off
chcp 65001 > nul
echo Запуск бота КиноЖдун в мессенджере Макс...
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m max_bot
) else (
    python -m max_bot
)
pause
