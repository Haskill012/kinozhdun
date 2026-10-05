# Start from any directory: all paths are relative to this script.
Set-Location -LiteralPath $PSScriptRoot
$pythonPath = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Error 'Install Python dependencies first: python -m venv .venv; .venv/Scripts/python.exe -m pip install -r requirements.txt'
    exit 1
}
& $pythonPath -m website
