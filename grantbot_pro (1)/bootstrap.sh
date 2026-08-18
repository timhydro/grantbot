#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo
echo "============================================"
echo " GRANTBOT PRO BOOTSTRAP"
echo "============================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: Python 3 is required."
    exit 1
fi

if [ ! -d ".venv" ]; then
    echo "Creating Python virtual environment..."

    if ! python3 -m venv .venv; then
        echo
        echo "Python venv support is missing."
        echo
        echo "On Debian/Chromebook Linux run:"
        echo
        echo "sudo apt update && sudo apt install -y python3-venv"
        echo
        exit 1
    fi
fi

echo
echo "Upgrading pip..."
.venv/bin/python -m pip install \
    --upgrade \
    pip \
    setuptools \
    wheel

echo
echo "Installing GrantBot dependencies..."
.venv/bin/pip install \
    -r requirements.txt

echo
echo "Compiling source..."
.venv/bin/python \
    -m compileall \
    -q \
    grantbot \
    tests

echo
echo "Initializing database..."
PYTHONPATH="$ROOT" \
.venv/bin/python \
    -m grantbot init

echo
echo "Running tests..."
PYTHONPATH="$ROOT" \
.venv/bin/python \
    -m pytest \
    tests/test_core.py \
    -q

echo
echo "Running diagnostics..."
PYTHONPATH="$ROOT" \
.venv/bin/python \
    -m grantbot status

echo
echo "============================================"
echo " MODULE 01 FOUNDATION READY"
echo "============================================"
