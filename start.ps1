$ErrorActionPreference = "Stop"

$ProjectDir = $PSScriptRoot
$BackendDir = Join-Path $ProjectDir "backend"
$FrontendDir = Join-Path $ProjectDir "frontend"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "      Запуск Альфа Тин (Windows PS)      " -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

$EnvFile = Join-Path $ProjectDir ".env"
$EnvExample = Join-Path $ProjectDir ".env.example"
if (-not (Test-Path $EnvFile) -and (Test-Path $EnvExample)) {
    Write-Host "Создаю .env из .env.example..." -ForegroundColor Yellow
    Copy-Item $EnvExample $EnvFile
}

$VenvUvicorn = Join-Path $BackendDir ".venv\Scripts\uvicorn.exe"
if (-not (Test-Path $VenvUvicorn)) {
    Write-Host "Устанавливаю backend-зависимости..." -ForegroundColor Yellow
    python -m venv (Join-Path $BackendDir ".venv")
    & (Join-Path $BackendDir ".venv\Scripts\pip.exe") install -r (Join-Path $BackendDir "requirements.txt")
}

$NodeModules = Join-Path $FrontendDir "node_modules"
if (-not (Test-Path $NodeModules)) {
    Write-Host "Устанавливаю frontend-зависимости..." -ForegroundColor Yellow
    Push-Location $FrontendDir
    npm install
    Pop-Location
}

Write-Host "Запускаю Backend (FastAPI)..." -ForegroundColor Green
Start-Process cmd -ArgumentList "/k", "cd /d `"$BackendDir`" && .venv\Scripts\uvicorn app.main:app --env-file ..\.env --host 127.0.0.1 --port 8000 --reload"

Write-Host "Запускаю Frontend (Vite)..." -ForegroundColor Green
Start-Process cmd -ArgumentList "/k", "cd /d `"$FrontendDir`" && npm run dev -- --host 127.0.0.1"

Start-Sleep -Seconds 3
Write-Host "Открываю браузер..." -ForegroundColor Green
Start-Process "http://127.0.0.1:5173/"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "Приложение успешно запущено!" -ForegroundColor Green
Write-Host "Frontend: http://127.0.0.1:5173/" -ForegroundColor Yellow
Write-Host "Backend API: http://127.0.0.1:8000/docs" -ForegroundColor Yellow
Write-Host "=========================================" -ForegroundColor Cyan
