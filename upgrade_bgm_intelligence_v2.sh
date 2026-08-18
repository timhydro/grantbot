#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/grantbot_pro"
mkdir -p "$ROOT"
cd "$ROOT"

# Ensure virtualenv exists
if [[ ! -d .venv ]]; then
  echo "[+] Creating Python virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate

# Create required directories
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p backups grantbot/knowledge/data grantbot/api grantbot/grants tests

# Safe copy of app.py (create default if absent)
if [[ -f grantbot/app.py ]]; then
  cp grantbot/app.py "backups/app_before_intelligence_v2_${STAMP}.py"
else
  echo "[+] Creating baseline grantbot/app.py..."
  cat > grantbot/app.py <<'PY'
from __future__ import annotations

def main() -> None:
    print("GrantBot Pro Engine Initialized")

if __name__ == "__main__":
    main()
PY
fi

# Write fact_registry.py module
echo "[+] Writing grantbot/knowledge/fact_registry.py..."
cat > grantbot/knowledge/fact_registry.py <<'PY'
from __future__ import annotations

import json
import os
from typing import Dict, Any, Optional

class FactRegistry:
    """Production Fact Registry for Grant Data & Non-Profit Metrics."""

    def __init__(self, data_path: Optional[str] = None) -> None:
        self.data_path = data_path or os.path.join(
            os.path.dirname(__file__), "data", "fact_store.json"
        )
        self._facts: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        if os.path.exists(self.data_path):
            with open(self.data_path, "r", encoding="utf-8") as f:
                self._facts = json.load(f)
        else:
            self._facts = {
                "organization_name": "Pensacola Transitional Housing Initiative",
                "mission_statement": "Providing housing, employment, and reintegration for unhoused citizens and former inmates.",
                "target_units": 50,
                "employment_placement_rate_target": 0.85,
                "grant_readiness_status": True
            }
            self.save()

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
        with open(self.data_path, "w", encoding="utf-8") as f:
            json.dump(self._facts, f, indent=2)

    def get_fact(self, key: str, default: Any = None) -> Any:
        return self._facts.get(key, default)

    def set_fact(self, key: str, value: Any) -> None:
        self._facts[key] = value
        self.save()

    def export_all(self) -> Dict[str, Any]:
        return self._facts.copy()
PY

# Write unit tests
echo "[+] Writing test suite..."
cat > tests/test_fact_registry.py <<'PY'
from __future__ import annotations

import os
import unittest
from grantbot.knowledge.fact_registry import FactRegistry

class TestFactRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self.test_path = "tests/test_fact_store.json"
        if os.path.exists(self.test_path):
            os.remove(self.test_path)
        self.registry = FactRegistry(data_path=self.test_path)

    def tearDown(self) -> None:
        if os.path.exists(self.test_path):
            os.remove(self.test_path)

    def test_fact_lifecycle(self) -> None:
        self.registry.set_fact("tiny_homes_count", 10)
        self.assertEqual(self.registry.get_fact("tiny_homes_count"), 10)
        self.assertEqual(self.registry.get_fact("organization_name"), "Pensacola Transitional Housing Initiative")

if __name__ == "__main__":
    unittest.main()
PY

# Execute tests
echo "[+] Executing test suite..."
python3 -m unittest discover -s tests

echo "[✓] Upgrade Complete: Intelligence V2 deployed successfully."
