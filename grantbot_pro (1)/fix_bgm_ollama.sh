#!/usr/bin/env bash
set -euo pipefail
cd "$HOME/grantbot_pro"
if ! command -v ollama >/dev/null 2>&1; then
  echo "ERROR: Ollama is not installed."
  exit 1
fi
pkill -f "ollama serve" 2>/dev/null || true
nohup ollama serve >"$HOME/grantbot_pro/logs/ollama.log" 2>&1 &
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "OLLAMA SERVER: ONLINE"
    break
  fi
  sleep 1
done
if ! curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "ERROR: Ollama failed to start."
  cat "$HOME/grantbot_pro/logs/ollama.log"
  exit 1
fi
if ! ollama list | awk 'NR>1 {print $1}' | grep -Fxq 'llama3.2:3b'; then
  ollama pull llama3.2:3b
fi
echo "OLLAMA MODEL: READY"
ollama list
echo "OLLAMA REPAIR COMPLETE"
