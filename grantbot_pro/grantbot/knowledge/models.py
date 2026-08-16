from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class FactStatus(str, Enum):
    APPROVED = "APPROVED"
    VERIFIED = "VERIFIED"
    DRAFT = "DRAFT"
    MISSING = "MISSING"


TRUST_ORDER = {
    FactStatus.MISSING.value: 0,
    FactStatus.DRAFT.value: 1,
    FactStatus.VERIFIED.value: 2,
    FactStatus.APPROVED.value: 3,
}


@dataclass
class Fact:
    category: str
    fact_key: str
    value: Optional[str] = None
    status: str = FactStatus.MISSING.value
    source: Optional[str] = None
    confidence: float = 1.0
    notes: Optional[str] = None

    @property
    def usable(self) -> bool:
        return bool(
            self.value
            and self.status
            in {
                FactStatus.APPROVED.value,
                FactStatus.VERIFIED.value,
                FactStatus.DRAFT.value,
            }
        )

    @property
    def grant_safe(self) -> bool:
        return bool(
            self.value
            and self.status
            in {
                FactStatus.APPROVED.value,
                FactStatus.VERIFIED.value,
            }
        )
