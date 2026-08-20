#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

WITH_LOCAL_AI=0
WITH_AGENTS=0

usage() {
    cat <<'EOF'
Usage: bash bootstrap.sh [--with-local-ai] [--with-agents]

Options:
  --with-local-ai  Install/verify Ollama and the configured free local model.
  --with-agents    Install the optional CrewAI agent layer for local Ollama orchestration.
  -h, --help       Show this help.
EOF
}

for arg in "$@"; do
    case "$arg" in
        --with-local-ai)
            WITH_LOCAL_AI=1
            ;;
        --with-agents)
            WITH_AGENTS=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown argument: $arg"
            usage
            exit 2
            ;;
    esac
done

echo

echo "============================================"
echo " GRANTBOT PRO BOOTSTRAP"
echo "============================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: Python 3 is required."
    exit 1
fi

if ! python3 - <<'PY'
import sys

if not ((3, 10) <= sys.version_info[:2] < (3, 14)):
    raise SystemExit(
        f"GrantBot requires Python >=3.10 and <3.14; found {sys.version.split()[0]}"
    )
PY
then
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "Creating Python virtual environment..."

    if ! python3 -m venv .venv; then
        echo
        echo "Python venv support is missing."
        echo "On Debian/Chromebook Linux run:"
        echo "sudo apt update && sudo apt install -y python3-venv"
        exit 1
    fi
fi

echo
echo "Upgrading packaging tools..."
.venv/bin/python -m pip install --upgrade pip setuptools wheel

echo
echo "Installing GrantBot dependencies..."
.venv/bin/pip install -r requirements.txt

echo
echo "Installing GrantBot itself in editable mode..."
if [ "$WITH_AGENTS" -eq 1 ]; then
    .venv/bin/pip install -e '.[agents]'
else
    .venv/bin/pip install -e .
fi

VERSION="$(PYTHONPATH="$ROOT" .venv/bin/python - <<'PY'
from grantbot import __version__
print(__version__)
PY
)"

echo
echo "GrantBot Pro version: $VERSION"

echo
echo "Compiling source..."
.venv/bin/python -m compileall -q grantbot tests

echo
echo "Initializing database and directories..."
PYTHONPATH="$ROOT" .venv/bin/python -m grantbot init

echo
echo "Running complete GrantBot test suite..."
PYTHONPATH="$ROOT" .venv/bin/python -m pytest -q

if [ "$WITH_LOCAL_AI" -eq 1 ]; then
    echo
    echo "Installing/verifying free local AI..."
    bash "$ROOT/setup_local_ai.sh"
else
    echo
    echo "Checking local AI status (non-fatal)..."
    PYTHONPATH="$ROOT" .venv/bin/python - <<'PY'
import json
from grantbot.writing.ollama_provider import OllamaProvider

print(json.dumps(OllamaProvider().health(), indent=2, sort_keys=True))
PY
fi

if [ "$WITH_AGENTS" -eq 1 ]; then
    echo
    echo "Checking CrewAI local-agent integration..."
    PYTHONPATH="$ROOT" .venv/bin/python - <<'PY'
import json
from grantbot.agents.crewai_local import crewai_status

print(json.dumps(crewai_status().to_dict(), indent=2, sort_keys=True))
PY
fi

echo
echo "Running GrantBot diagnostics..."
PYTHONPATH="$ROOT" .venv/bin/python -m grantbot status

echo
echo "============================================"
echo " GRANTBOT PRO $VERSION READY"
echo "============================================"
echo
echo "Launch API:"
echo "  bash run_grantbot.sh"
if [ "$WITH_LOCAL_AI" -ne 1 ]; then
    echo
    echo "To install/verify the free local writer later:"
    echo "  bash setup_local_ai.sh"
fi
if [ "$WITH_AGENTS" -ne 1 ]; then
    echo
    echo "To enable the optional local CrewAI agents later:"
    echo "  .venv/bin/pip install -e '.[agents]'"
fi
