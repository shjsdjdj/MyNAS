#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT"

: "${MYNAS_COOKIE_SECURE:=false}"
export MYNAS_COOKIE_SECURE

cleanup() {
    kill "${backend_pid:-}" "${frontend_pid:-}" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

printf '%s\n' 'Starting MyNAS backend: http://127.0.0.1:8000'
python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --no-server-header &
backend_pid=$!

printf '%s\n' 'Starting MyNAS frontend: http://127.0.0.1:5173'
npm run dev &
frontend_pid=$!

(
    sleep 3
    if command -v open >/dev/null 2>&1; then
        open http://127.0.0.1:5173
    elif command -v xdg-open >/dev/null 2>&1; then
        xdg-open http://127.0.0.1:5173
    fi
) >/dev/null 2>&1 &

wait "$backend_pid" "$frontend_pid"
