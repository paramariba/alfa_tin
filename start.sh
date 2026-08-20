#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"
VENV_DIR="$BACKEND_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
VITE_BIN="$FRONTEND_DIR/node_modules/.bin/vite"
ENV_FILE="$PROJECT_DIR/.env"
ENV_EXAMPLE="$PROJECT_DIR/.env.example"

INSTALL_ONLY=false
SKIP_INSTALL=false
OPEN_BROWSER=true
BACKEND_PID=""
FRONTEND_PID=""

usage() {
  cat <<'EOF'
Использование: ./start.sh [опции]

  --install-only  установить зависимости и завершить работу
  --skip-install  не проверять и не устанавливать зависимости
  --no-browser    не открывать браузер автоматически
  -h, --help      показать эту справку
EOF
}

while (($# > 0)); do
  case "$1" in
    --install-only) INSTALL_ONLY=true ;;
    --skip-install) SKIP_INSTALL=true ;;
    --no-browser) OPEN_BROWSER=false ;;
    -h|--help) usage; exit 0 ;;
    *)
      echo "Неизвестная опция: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Не найдена команда '$1'. $2" >&2
    exit 1
  fi
}

checksum() {
  sha256sum "$1" | awk '{print $1}'
}

install_backend_dependencies() {
  require_command python3 "Установите пакеты python3, python3-venv и python3-pip."
  require_command sha256sum "Установите пакет coreutils."
  require_command mktemp "Установите пакет coreutils."

  if [[ -d "$VENV_DIR" ]] && { [[ ! -x "$PYTHON_BIN" ]] || ! "$PYTHON_BIN" --version >/dev/null 2>&1; }; then
    local backup_dir
    backup_dir="$(mktemp -d "${TMPDIR:-/tmp}/alfa-teen-venv.XXXXXX")"
    echo "Обнаружено несовместимое Python-окружение."
    echo "Перемещаю его в $backup_dir/.venv"
    mv "$VENV_DIR" "$backup_dir/.venv"
  fi

  if [[ ! -d "$VENV_DIR" ]]; then
    echo "Создаю виртуальное окружение Python..."
    if ! python3 -m venv "$VENV_DIR"; then
      echo "Не удалось создать venv. На Ubuntu выполните: sudo apt install python3-venv python3-pip" >&2
      exit 1
    fi
  fi

  local requirements_hash
  local stamp="$VENV_DIR/.requirements.sha256"
  requirements_hash="$(checksum "$BACKEND_DIR/requirements.txt")"

  if [[ ! -f "$stamp" ]] || [[ "$(<"$stamp")" != "$requirements_hash" ]] || ! "$PYTHON_BIN" -m pip check >/dev/null 2>&1; then
    echo "Устанавливаю backend-зависимости..."
    "$PYTHON_BIN" -m pip install --disable-pip-version-check -r "$BACKEND_DIR/requirements.txt"
    printf '%s\n' "$requirements_hash" >"$stamp"
  else
    echo "Backend-зависимости уже установлены."
  fi
}

install_frontend_dependencies() {
  require_command node "Установите Node.js 20.19+ (или 22.12+)."
  require_command npm "Установите npm."
  require_command sha256sum "Установите пакет coreutils."

  local lock_hash
  local stamp="$FRONTEND_DIR/node_modules/.package-lock.sha256"
  lock_hash="$(checksum "$FRONTEND_DIR/package-lock.json")"

  if [[ ! -d "$FRONTEND_DIR/node_modules" ]] || [[ ! -f "$stamp" ]] || [[ "$(<"$stamp")" != "$lock_hash" ]]; then
    echo "Устанавливаю frontend-зависимости..."
    (cd "$FRONTEND_DIR" && npm ci --no-audit --no-fund)
    printf '%s\n' "$lock_hash" >"$stamp"
  else
    echo "Frontend-зависимости уже установлены."
  fi
}

wait_for_url() {
  local name="$1"
  local url="$2"
  local pid="$3"

  if ! command -v curl >/dev/null 2>&1; then
    sleep 2
    return 0
  fi

  for _ in {1..60}; do
    if curl --silent --fail --max-time 1 "$url" >/dev/null; then
      return 0
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "$name завершился до готовности." >&2
      return 1
    fi
    sleep 0.25
  done

  echo "$name не стал доступен по адресу $url." >&2
  return 1
}

cleanup() {
  local status=$?
  trap - EXIT INT TERM HUP

  local pid
  for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  # Uvicorn can briefly wait for an in-flight news request. Do not leave either
  # development server behind after Ctrl+C.
  for _ in {1..30}; do
    local alive=false
    for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
      if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then alive=true; fi
    done
    [[ "$alive" == true ]] || break
    sleep 0.1
  done
  for pid in "$FRONTEND_PID" "$BACKEND_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
  done
  [[ -z "$BACKEND_PID" ]] || wait "$BACKEND_PID" 2>/dev/null || true
  [[ -z "$FRONTEND_PID" ]] || wait "$FRONTEND_PID" 2>/dev/null || true

  exit "$status"
}

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ ! -f "$ENV_EXAMPLE" ]]; then
    echo "Не найден ни .env, ни .env.example." >&2
    exit 1
  fi
  echo "Создаю .env из .env.example..."
  cp "$ENV_EXAMPLE" "$ENV_FILE"
fi

if [[ "$SKIP_INSTALL" == false ]]; then
  install_backend_dependencies
  install_frontend_dependencies
fi

if [[ "$INSTALL_ONLY" == true ]]; then
  echo "Все зависимости установлены."
  exit 0
fi

if [[ ! -x "$PYTHON_BIN" ]] || [[ ! -x "$VITE_BIN" ]]; then
  echo "Зависимости не установлены. Запустите ./start.sh --install-only." >&2
  exit 1
fi

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM HUP

echo "Запускаю backend..."
BIND_HOST="${APP_BIND_HOST:-0.0.0.0}"
(
  cd "$BACKEND_DIR"
  exec "$PYTHON_BIN" -m uvicorn app.main:app --env-file "$ENV_FILE" --host "$BIND_HOST" --port 8000
) &
BACKEND_PID=$!

# Starting Vite only after the API is ready prevents its WebSocket proxy from
# connecting to a half-started backend and logging EPIPE.
wait_for_url "Backend" "http://127.0.0.1:8000/health/ready" "$BACKEND_PID"

echo "Запускаю frontend..."
(
  cd "$FRONTEND_DIR"
  exec "$VITE_BIN" --host "$BIND_HOST" --port 5173 --strictPort
) &
FRONTEND_PID=$!

wait_for_url "Frontend" "http://127.0.0.1:5173/" "$FRONTEND_PID"

echo
echo "Альфа Тин запущен:"
echo "  На этом компьютере: http://127.0.0.1:5173/"
echo "  Backend API: http://127.0.0.1:8000/docs"
if [[ "$BIND_HOST" == "0.0.0.0" ]]; then
  LAN_IP=""
  if command -v ip >/dev/null 2>&1; then
    LAN_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src"){print $(i+1); exit}}')"
  elif command -v hostname >/dev/null 2>&1; then
    LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  fi
  if [[ -n "$LAN_IP" ]]; then
    echo "  В локальной сети: http://$LAN_IP:5173/"
    echo "  Откройте этот адрес на телефоне в той же Wi-Fi-сети."
  fi
fi
echo "Для остановки нажмите Ctrl+C."

if [[ "$OPEN_BROWSER" == true ]] && command -v xdg-open >/dev/null 2>&1 && { [[ -n "${DISPLAY:-}" ]] || [[ -n "${WAYLAND_DISPLAY:-}" ]]; }; then
  xdg-open "http://127.0.0.1:5173/" >/dev/null 2>&1 || true
fi

set +e
wait -n "$BACKEND_PID" "$FRONTEND_PID"
status=$?
set -e

if kill -0 "$BACKEND_PID" 2>/dev/null; then
  echo "Frontend остановлен (код $status)." >&2
else
  echo "Backend остановлен (код $status)." >&2
fi
exit "$status"
