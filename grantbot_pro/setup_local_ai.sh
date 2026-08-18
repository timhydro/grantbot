#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

MODEL="${OLLAMA_MODEL:-llama3.2:3b}"
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"

echo
echo "============================================"
echo " GRANTBOT FREE LOCAL AI SETUP"
echo "============================================"
echo "Model: $MODEL"
echo "API:   $OLLAMA_URL"
echo

if ! command -v curl >/dev/null 2>&1; then
    echo "ERROR: curl is required."
    echo "Install it with: sudo apt update && sudo apt install -y curl"
    exit 1
fi

if ! command -v ollama >/dev/null 2>&1; then
    echo "Ollama is not installed. Installing from the official Ollama installer..."
    curl -fsSL https://ollama.com/install.sh | sh
fi

echo "Ollama binary: $(command -v ollama)"
ollama --version || true

api_ready() {
    curl -fsS --max-time 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1
}

if ! api_ready; then
    echo "Starting Ollama server..."
    nohup ollama serve >"$LOG_DIR/ollama.log" 2>&1 &

    READY=0
    for _ in $(seq 1 30); do
        if api_ready; then
            READY=1
            break
        fi
        sleep 1
    done

    if [ "$READY" -ne 1 ]; then
        echo "ERROR: Ollama did not become ready."
        echo "Log: $LOG_DIR/ollama.log"
        tail -n 50 "$LOG_DIR/ollama.log" 2>/dev/null || true
        exit 1
    fi
fi

echo "Ollama API is ready."

if ! ollama list 2>/dev/null | awk 'NR > 1 {print $1}' | grep -Fxq "$MODEL"; then
    echo "Downloading local model: $MODEL"
    ollama pull "$MODEL"
else
    echo "Model already installed: $MODEL"
fi

ENV_FILE="$ROOT/.env"
if [ ! -f "$ENV_FILE" ]; then
    cp "$ROOT/.env.example" "$ENV_FILE"
fi

set_env_value() {
    local key="$1"
    local value="$2"
    if grep -q "^${key}=" "$ENV_FILE"; then
        sed -i "s#^${key}=.*#${key}=${value}#" "$ENV_FILE"
    else
        printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
    fi
}

set_env_value OLLAMA_ENABLED 1
set_env_value OLLAMA_URL "$OLLAMA_URL"
set_env_value OLLAMA_MODEL "$MODEL"

PYTHON="python3"
if [ -x "$ROOT/.venv/bin/python" ]; then
    PYTHON="$ROOT/.venv/bin/python"
fi

echo
echo "Verifying GrantBot can see the local model..."
PYTHONPATH="$ROOT" "$PYTHON" - <<'PY'
import json
from grantbot.writing.ollama_provider import OllamaProvider

health = OllamaProvider().health()
print(json.dumps(health, indent=2, sort_keys=True))
if not health.get("available"):
    raise SystemExit("GrantBot local AI verification failed")
PY

echo
echo "============================================"
echo " FREE LOCAL AI READY"
echo "============================================"
echo "No paid AI API is required for GrantBot writing."
