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
VERSION="$(PYTHONPATH="$ROOT" "$PYTHON" - <<'PY'
from grantbot import __version__
print(__version__)
PY
)"

if ! [[ "$PORT" =~ ^[0-9]+$ ]] || [ "$PORT" -lt 1 ] || [ "$PORT" -gt 65535 ]; then
    echo "ERROR: Invalid GrantBot port: $PORT"
    exit 1
fi

PROBE_HOST="$HOST"
case "$PROBE_HOST" in
    0.0.0.0|::|"[::]") PROBE_HOST="127.0.0.1" ;;
esac

PORT_BUSY="$($PYTHON - "$PROBE_HOST" "$PORT" <<'PY'
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
       curl -fsS --max-time 2 "http://$PROBE_HOST:$PORT/health" 2>/dev/null | \
       grep -q '"status":"ok"'; then
        echo "GrantBot Pro $VERSION is already running at http://$PROBE_HOST:$PORT"
        exit 0
    fi
    echo "ERROR: Another process is using the configured GrantBot port."
    echo "Change GRANTBOT_PORT in .env or stop the conflicting process."
    exit 1
fi

echo
echo "============================================"
echo " GRANTBOT PRO $VERSION STARTING"
echo "============================================"
echo "API:    http://$PROBE_HOST:$PORT"
echo "Health: http://$PROBE_HOST:$PORT/health"
echo "Docs:   http://$PROBE_HOST:$PORT/docs"
echo "Admin key file: $ROOT/data/master_api_key.txt"
echo
echo "Press Ctrl+C to stop GrantBot."
echo

exec env PYTHONPATH="$ROOT" \
    "$PYTHON" -m uvicorn grantbot.app:app \
    --host "$HOST" \
    --port "$PORT"
