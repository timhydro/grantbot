from __future__ import annotations

import json
import os
from typing import Dict, Any, Optional

class FactRegistry:
    """Enterprise Fact Registry for Non-Profit Case Management & Grant Data."""

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
                "organization": "Tiny Home Village Initiative",
                "mission": "Rehousing and workforce integration for unhoused citizens and former inmates.",
                "housing_units_planned": 50,
                "job_placement_target_rate": 0.85
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
