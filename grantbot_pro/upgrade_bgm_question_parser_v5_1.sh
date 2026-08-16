#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME/grantbot_pro"
cd "$ROOT"

if [[ ! -f grantbot/nofo/analyzer.py ]]; then
    echo "ERROR: grantbot/nofo/analyzer.py not found." >&2
    exit 1
fi

if [[ ! -d .venv ]]; then
    echo "ERROR: $ROOT/.venv not found." >&2
    exit 1
fi

source .venv/bin/activate

STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p backups
cp grantbot/nofo/analyzer.py "backups/analyzer_before_question_parser_${STAMP}.py"

python3 - <<'PY'
from pathlib import Path
import re

p = Path("grantbot/nofo/analyzer.py")
s = p.read_text(encoding="utf-8")

helper = '''def _extract_questions(text: str) -> list[str]:
    questions: list[str] = []

    numbered = re.compile(
        r"(?:^|\\s)(?:\\d{1,3}|[A-Z])[\\.\\)]\\s*"
        r"(.+?\\?)"
        r"(?=\\s+(?:\\d{1,3}|[A-Z])[\\.\\)]\\s*|$)",
        re.DOTALL,
    )

    for match in numbered.finditer(text):
        question = " ".join(match.group(1).split()).strip()

        if len(question) >= 8 and question not in questions:
            questions.append(question)

    if questions:
        return questions

    for line in text.splitlines():
        clean = " ".join(line.strip().split())

        if not clean.endswith("?") or len(clean) < 8:
            continue

        clean = re.sub(
            r"^\\s*(?:\\d{1,3}|[A-Z])[\\.\\)]\\s*",
            "",
            clean,
        )

        if clean not in questions:
            questions.append(clean)

    return questions


'''

if "def _extract_questions(" not in s:
    marker = "def analyze_nofo("
    if marker not in s:
        raise SystemExit("ERROR: analyze_nofo() not found.")
    s = s.replace(marker, helper + marker, 1)

old_snippet = '''    questions = []
    for line in text.splitlines():
        line = " ".join(line.strip().split())
        if line.endswith("?") and len(line) >= 12:
            q = re.sub(r"^\\s*(?:\\d+[.)]|[A-Z][.)])\\s*", "", line)
            if q not in questions:
                questions.append(q)
'''

if old_snippet in s:
    s = s.replace(
        old_snippet,
        "    questions = _extract_questions(text)\\n",
        1,
    )

if "questions = _extract_questions(text)" not in s:
    raise SystemExit(
        "ERROR: Could not safely locate active question extraction logic."
    )

p.write_text(s, encoding="utf-8")
print("NOFO QUESTION PARSER PATCH: INSTALLED")
PY

python3 -m py_compile grantbot/nofo/analyzer.py

python3 - <<'PY'
from grantbot.nofo.analyzer import analyze_nofo

sample = (
    "Eligible applicants include nonprofit and faith-based organizations. "
    "This program supports reentry, homelessness, housing, employment, "
    "workforce development, job training, case management, and supportive services. "
    "1. Describe your organization mission? "
    "2. Describe your proposed program? "
    "3. How will success be measured?"
)

result = analyze_nofo(sample)

expected = [
    "Describe your organization mission?",
    "Describe your proposed program?",
    "How will success be measured?",
]

if result.application_questions != expected:
    raise SystemExit(
        f"ERROR: Question parsing test failed: {result.application_questions!r}"
    )

print("NOFO QUESTION PARSER TEST: PASS")
print("QUESTIONS EXTRACTED: 3")
PY

python3 -m unittest tests.test_master_v3_v5 -v
python3 -m compileall -q grantbot
python3 -c "import grantbot.app; print('GRANTBOT APP IMPORT: OK')"

echo "NOFO QUESTION PARSER UPGRADE COMPLETE"
