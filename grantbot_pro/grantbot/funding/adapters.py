from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass
class SearchRequest:
    query: str

    geography: str | None = None

    limit: int = 25

    filters: dict[str, Any] | None = None


@dataclass
class SearchResult:
    external_id: str | None

    title: str

    description: str | None = None

    eligibility: str | None = None

    funder: str | None = None

    agency: str | None = None

    geography: str | None = None

    deadline: str | None = None

    award_floor: float | None = None

    award_ceiling: float | None = None

    source_url: str | None = None

    raw: dict[str, Any] | None = None


class FundingSourceAdapter(ABC):
    """
    Common contract for every live funding connector.

    Later modules can implement:
      - Grants.gov
      - state portals
      - county/city searches
      - foundations
      - corporate giving
      - investor discovery

    The rest of GrantBot does not need to know how
    each source is searched.
    """

    source_key: str

    @abstractmethod
    def search(
        self,
        request: SearchRequest,
    ) -> Iterable[SearchResult]:
        raise NotImplementedError


class AdapterRegistry:
    def __init__(self):
        self._adapters = {}

    def register(
        self,
        adapter: FundingSourceAdapter,
    ):
        self._adapters[
            adapter.source_key
        ] = adapter

    def get(
        self,
        source_key: str,
    ):
        return self._adapters.get(
            source_key
        )

    def keys(self):
        return sorted(
            self._adapters
        )


ADAPTERS = AdapterRegistry()
