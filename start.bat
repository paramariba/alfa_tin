@echo off
chcp 65001 > NUL
title Альфа Тин — Запуск приложения

set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "BACKEND_DIR=%PROJECT_DIR%\backend"
set "FRONTEND_DIR=%PROJECT_DIR%\frontend"

echo =========================================
echo       Запуск Альфа Тин (Windows)
echo =========================================

if not exist "%PROJECT_DIR%\.env" (
    if exist "%PROJECT_DIR%\.env.example" (
        echo Создаю файл .env из .env.example...
        copy "%PROJECT_DIR%\.env.example" "%PROJECT_DIR%\.env" > NUL
    )
)

if not exist "%BACKEND_DIR%\.venv\Scripts\uvicorn.exe" (
    echo Устанавливаю backend-зависимости...
    python -m venv "%BACKEND_DIR%\.venv"
    "%BACKEND_DIR%\.venv\Scripts\pip.exe" install -r "%BACKEND_DIR%\requirements.txt"
)

if not exist "%FRONTEND_DIR%\node_modules" (
    echo Устанавливаю frontend-зависимости...
    cd /d "%FRONTEND_DIR%"
    call npm install
    cd /d "%PROJECT_DIR%"
)

echo Запускаю Backend (FastAPI)...
start "Alfa Teen Backend" cmd /k "cd /d "%BACKEND_DIR%" && .venv\Scripts\uvicorn app.main:app --env-file ..\.env --host 127.0.0.1 --port 8000 --reload"

echo Запускаю Frontend (Vite)...
start "Alfa Teen Frontend" cmd /k "cd /d "%FRONTEND_DIR%" && npm run dev -- --host 127.0.0.1"

timeout /t 3 /nobreak > NUL
echo Открываю веб-интерфейс в браузере...
start http://127.0.0.1:5173/

echo.
echo =========================================
echo Приложение успешно запущено!
echo Frontend: http://127.0.0.1:5173/
echo Backend OpenAPI: http://127.0.0.1:8000/docs
echo =========================================
