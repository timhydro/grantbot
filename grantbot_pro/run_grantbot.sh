#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    echo "ERROR: GrantBot virtual environment is missing."
    echo "Run: bash bootstrap.sh --with-local-ai"
    exit 1
fi

HOST="$(PYTHONPATH="$ROOT" "$PYTHON" - <<'PY'
from grantbot.core.config import settings
print(settings.host)
PY
)"
PORT="$(PYTHONPATH="$ROOT" "$PYTHON" - <<'PY'
from grantbot.core.config import settings
print(settings.port)
PY
)"

if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
    echo "ERROR: Invalid GrantBot port: $PORT"
    exit 1
fi

PORT_BUSY="$($PYTHON - "$HOST" "$PORT" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
sock = socket.socket()
sock.settimeout(0.5)
try:
    result = sock.connect_ex((host, port))
finally:
    sock.close()
print("1" if result == 0 else "0")
PY
)"

if [ "$PORT_BUSY" = "1" ]; then
    echo "Port $HOST:$PORT is already in use."
    if command -v curl >/dev/null 2>&1 && \
       curl -fsS --max-time 2 "http://$HOST:$PORT/openapi.json" 2>/dev/null | \
       grep -q 'GrantBot Pro Unified'; then
        echo "GrantBot is already running at http://$HOST:$PORT"
        exit 0
    fi
    echo "ERROR: Another process is using the configured GrantBot port."
    echo "Change GRANTBOT_PORT in .env or stop the conflicting process."
    exit 1
fi

echo
echo "============================================"
echo " GRANTBOT PRO STARTING"
echo "============================================"
echo "API:  http://$HOST:$PORT"
echo "Docs: http://$HOST:$PORT/docs"
echo "Admin key file: $ROOT/data/master_api_key.txt"
echo
echo "Press Ctrl+C to stop GrantBot."
echo

exec env PYTHONPATH="$ROOT" \
    "$PYTHON" -m uvicorn grantbot.app:app \
    --host "$HOST" \
    --port "$PORT"
