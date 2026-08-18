#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

# Usage:
#   scripts/run_all.sh                # default (installs optional deps)
#   SKIP_OPTIONAL=1 scripts/run_all.sh
#   BUILD_INDEX=1 FACTS_FILE=path/to/facts.jsonl scripts/run_all.sh
#   EXPORT=1 DB_PATH=data/grantbot.db OUT=export/approved_training.jsonl scripts/run_all.sh

# Configuration (can be overridden via env)
PYTHON=${PYTHON:-python3}
VENV_DIR=${VENV_DIR:-.venv}
SKIP_OPTIONAL=${SKIP_OPTIONAL:-0}   # set to 1 to skip sentence-transformers/faiss install
BUILD_INDEX=${BUILD_INDEX:-0}       # set to 1 to run FAISS index builder (requires optional deps)
FACTS_FILE=${FACTS_FILE:-""}        # required if BUILD_INDEX=1
INDEX_OUT=${INDEX_OUT:-out/index.faiss}
MODEL_NAME=${MODEL_NAME:-all-MiniLM-L6-v2}
EXPORT=${EXPORT:-0}                 # set to 1 to run export_training_jsonl
DB_PATH=${DB_PATH:-data/grantbot.db}
OUT=${OUT:-export/approved_training.jsonl}
EXPORT_LIMIT=${EXPORT_LIMIT:-10000}

# Files to syntax-check (add or remove as needed)
COMPILE_FILES=(
  "grantbot_pro/grantbot/writing/master_writer.py"
  "grantbot_pro/grantbot/writing/provider.py"
  "grantbot_pro/grantbot/writing/feedback.py"
  "grantbot_pro/grantbot/writing/retrieval.py"
  "grantbot/writing/provider.py"
)

echo "==> Starting run_all.sh"
echo "Python: $PYTHON"
echo "Venv: $VENV_DIR"
echo "Skip optional deps: $SKIP_OPTIONAL"
echo "Build index: $BUILD_INDEX"
echo "Export: $EXPORT"

# 1) create venv if missing
if [ ! -d "$VENV_DIR" ]; then
  echo "==> Creating virtualenv $VENV_DIR"
  $PYTHON -m venv "$VENV_DIR"
fi

# 2) activate venv for the script
# shellcheck source=/dev/null
source "$VENV_DIR/bin/activate"

# 3) upgrade pip/tools and install core deps
echo "==> Upgrading pip and setuptools"
python -m pip install --upgrade pip setuptools wheel

# Try to install repo editable (if setup.py / pyproject exist)
if [ -f "pyproject.toml" ] || [ -f "setup.py" ] || [ -f "setup.cfg" ]; then
  echo "==> Installing repository in editable mode (pip install -e .)"
  if ! pip install -e .; then
    echo "WARNING: editable install failed; tests will run with PYTHONPATH=."
    export PYTHONPATH="$(pwd):${PYTHONPATH:-}"
  fi
else
  echo "No setup.py/pyproject - using PYTHONPATH=."
  export PYTHONPATH="$(pwd):${PYTHONPATH:-}"
fi

# 4) install optional semantic retrieval deps unless SKIP_OPTIONAL
if [ "$SKIP_OPTIONAL" = "0" ]; then
  echo "==> Installing optional semantic retrieval deps (sentence-transformers, faiss-cpu). This may take a few minutes."
  # allow failure but continue: retrieval module has fallback
  pip install sentence-transformers faiss-cpu || echo "Optional install failed; continuing with fallback retrieval"
else
  echo "==> SKIPPING optional semantic retrieval deps (SKIP_OPTIONAL=1)"
fi

# 5) run syntax checks
echo "==> Running python -m py_compile"
for f in "${COMPILE_FILES[@]}"; do
  if [ -f "$f" ]; then
    echo "  compiling $f"
    python -m py_compile "$f"
  else
    echo "  skipping missing file $f"
  fi
done

# 6) run unit tests
echo "==> Running unit tests (unittest discover)"
# use -v for verbose
python -m unittest discover -s tests -v

# 7) optionally build FAISS index (requires optional deps)
if [ "$BUILD_INDEX" = "1" ]; then
  if [ -z "$FACTS_FILE" ]; then
    echo "ERROR: BUILD_INDEX=1 but FACTS_FILE is empty. Provide FACTS_FILE=path/to/facts.jsonl"
    exit 2
  fi
  echo "==> Building FAISS index from facts file: $FACTS_FILE -> $INDEX_OUT"
  python scripts/build_fact_index.py --facts "$FACTS_FILE" --index "$INDEX_OUT" --model "$MODEL_NAME"
  echo "Index built: $INDEX_OUT"
fi

# 8) optionally export approved training examples
if [ "$EXPORT" = "1" ]; then
  echo "==> Exporting approved examples from DB: $DB_PATH -> $OUT (limit $EXPORT_LIMIT)"
  python tools/export_training_jsonl.py --db "$DB_PATH" --out "$OUT" --limit "$EXPORT_LIMIT"
  echo "Export complete: $OUT"
fi

echo "==> run_all.sh finished successfully"
