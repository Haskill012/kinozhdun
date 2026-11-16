# Запуск бота КиноЖдун в мессенджере Макс (MAX Messenger)
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonPath = 'python'
}
& $pythonPath -m max_bot
