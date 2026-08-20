from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import threading
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Type
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from crewai.tools import BaseTool
from crewai.tools.tool_failure import ToolFailure
from ddgs import DDGS
from pydantic import BaseModel, Field
from pypdf import PdfReader
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from grantbot.discovery.brave import BraveSearchProvider
from grantbot.discovery.grants_gov import discover
from grantbot.knowledge.repository import missing_facts
from grantbot.knowledge.service import grant_safe_profile


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROVENANCE_PATH = PROJECT_ROOT / "data" / "research" / "provenance.jsonl"
_PROVENANCE_LOCK = threading.Lock()


class SearchInput(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    max_results: int = Field(default=8, ge=1, le=20)


class FetchInput(BaseModel):
    url: str = Field(min_length=8, max_length=2048)
    max_chars: int = Field(default=24000, ge=1000, le=60000)


class KnowledgeInput(BaseModel):
    query: str = Field(default="", max_length=500)
    max_results: int = Field(default=15, ge=1, le=50)
    include_missing_keys: bool = True


class GrantSearchInput(BaseModel):
    query: str = Field(min_length=2, max_length=250)
    max_results: int = Field(default=10, ge=1, le=25)


class SourceRecord(BaseModel):
    title: str = ""
    url: str
    snippet: str = ""
    domain: str = ""
    provider: str = ""
    source_quality: int = Field(ge=0, le=100)
    source_class: str = "UNKNOWN"


class SearchBundle(BaseModel):
    query: str
    provider: str
    result_count: int
    results: list[SourceRecord]


class FetchResult(BaseModel):
    url: str
    final_url: str
    content_type: str
    title: str = ""
    text: str
    sha256: str
    retrieved_at: str
    source_quality: int = Field(ge=0, le=100)
    source_class: str


class KnowledgeRecord(BaseModel):
    fact_key: str
    value: Any
    status: str
    source: str
    confidence: Any = None


class KnowledgeBundle(BaseModel):
    query: str
    verified_count: int
    facts: list[KnowledgeRecord]
    missing_fact_keys: list[str]


class GrantOpportunityRecord(BaseModel):
    opportunity_id: str
    title: str
    funder: str = ""
    deadline: str | None = None
    amount: float | None = None
    score: int = Field(default=0, ge=0, le=100)
    priority: str = ""
    source_url: str = ""


class GrantSearchBundle(BaseModel):
    query: str
    raw_hits: int
    unique_hits: int
    results: list[GrantOpportunityRecord]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_provenance(tool: str, operation: str, payload: dict[str, Any]) -> None:
    PROVENANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": _utc_now(),
        "tool": tool,
        "operation": operation,
        **payload,
    }
    with _PROVENANCE_LOCK:
        with PROVENANCE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _source_quality(url: str) -> tuple[int, str]:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if host.endswith(".gov") or host == "grants.gov" or host.endswith(".grants.gov"):
        return 100, "GOVERNMENT_PRIMARY"
    if host.endswith(".edu"):
        return 92, "ACADEMIC_INSTITUTION"
    if host.endswith(".mil"):
        return 95, "GOVERNMENT_PRIMARY"
    if host.endswith(".org"):
        return 78, "ORGANIZATION"
    if host.endswith(".foundation"):
        return 82, "FUNDER_ORGANIZATION"
    if host:
        return 65, "PUBLIC_WEB"
    return 40, "UNKNOWN"


def _validate_public_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http:// and https:// URLs are allowed")
    if parsed.username or parsed.password:
        raise ValueError("Credential-bearing URLs are not allowed")
    if not parsed.hostname:
        raise ValueError("URL hostname is required")
    if parsed.port not in {None, 80, 443}:
        raise ValueError("Only ports 80 and 443 are allowed for public research")

    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"}:
        raise ValueError("Localhost is not allowed")

    try:
        addr_info = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve public hostname: {host}") from exc

    for entry in addr_info:
        address = entry[4][0].split("%", 1)[0]
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ValueError(f"Non-public destination is blocked: {host}")

    return parsed.geturl()


def _session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.8,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry, pool_connections=8, pool_maxsize=8)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def _safe_fetch_bytes(url: str, max_bytes: int = 12 * 1024 * 1024) -> tuple[str, str, bytes]:
    current = _validate_public_url(url)
    session = _session()
    headers = {
        "User-Agent": "GrantBotPro/26.0 (nonprofit-research; source-verification)",
        "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,application/json;q=0.9,*/*;q=0.5",
    }

    for _ in range(6):
        response = session.get(
            current,
            headers=headers,
            timeout=30,
            allow_redirects=False,
            stream=True,
        )
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location", "").strip()
            response.close()
            if not location:
                raise RuntimeError("Redirect response did not include a Location header")
            current = _validate_public_url(urljoin(current, location))
            continue
        if response.status_code >= 400:
            response.close()
            raise RuntimeError(f"Source returned HTTP {response.status_code}")

        content_type = response.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0].strip().lower()
        length = response.headers.get("Content-Length")
        if length:
            try:
                if int(length) > max_bytes:
                    response.close()
                    raise RuntimeError("Source exceeds GrantBot's research size limit")
            except ValueError:
                pass

        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                response.close()
                raise RuntimeError("Source exceeded GrantBot's research size limit")
            chunks.append(chunk)
        response.close()
        return current, content_type, b"".join(chunks)

    raise RuntimeError("Too many redirects while fetching source")


def _extract_text(content_type: str, raw: bytes) -> tuple[str, str]:
    if content_type == "application/pdf" or raw[:5] == b"%PDF-":
        reader = PdfReader(BytesIO(raw))
        pages: list[str] = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text.strip())
        return "", "\n\n".join(pages)

    decoded = raw.decode("utf-8", errors="replace")
    if "html" in content_type or "<html" in decoded[:1000].lower():
        soup = BeautifulSoup(decoded, "lxml")
        for tag in soup(["script", "style", "noscript", "svg", "canvas"]):
            tag.decompose()
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        text = "\n".join(
            line.strip()
            for line in soup.get_text("\n").splitlines()
            if line.strip()
        )
        return title, text

    return "", decoded.strip()


class PublicWebSearchTool(BaseTool):
    name: str = "public_web_search"
    description: str = (
        "Search the public web for current funder, grant, policy, research, and evidence sources. "
        "Uses configured Brave Search when available and otherwise a free DDGS metasearch fallback."
    )
    args_schema: Type[BaseModel] = SearchInput

    def _run(self, query: str, max_results: int = 8) -> SearchBundle | ToolFailure:
        query = query.strip()
        try:
            brave = BraveSearchProvider()
            if brave.enabled:
                raw = brave.search(query, count=max_results)
                provider = "brave"
                rows = [
                    {
                        "title": item.get("title", ""),
                        "href": item.get("url", ""),
                        "body": item.get("description", ""),
                    }
                    for item in raw
                ]
            else:
                rows = DDGS(timeout=12).text(
                    query,
                    region="us-en",
                    safesearch="moderate",
                    max_results=max_results,
                    backend="auto",
                )
                provider = "ddgs"

            results: list[SourceRecord] = []
            seen: set[str] = set()
            for item in rows:
                url = str(item.get("href") or item.get("url") or "").strip()
                if not url or url in seen:
                    continue
                try:
                    _validate_public_url(url)
                except ValueError:
                    continue
                seen.add(url)
                score, source_class = _source_quality(url)
                results.append(
                    SourceRecord(
                        title=str(item.get("title") or "").strip(),
                        url=url,
                        snippet=str(item.get("body") or item.get("description") or "").strip(),
                        domain=(urlparse(url).hostname or "").lower(),
                        provider=provider,
                        source_quality=score,
                        source_class=source_class,
                    )
                )

            bundle = SearchBundle(
                query=query,
                provider=provider,
                result_count=len(results),
                results=results[:max_results],
            )
            _append_provenance(
                self.name,
                "search",
                {
                    "query": query,
                    "provider": provider,
                    "result_count": bundle.result_count,
                    "urls": [row.url for row in bundle.results],
                },
            )
            return bundle
        except Exception as exc:
            return ToolFailure(
                message=f"Public web search failed: {exc}",
                code="public_web_search_failed",
                retryable=True,
            )


class SafeSourceFetchTool(BaseTool):
    name: str = "safe_source_fetch"
    description: str = (
        "Fetch and extract text from one public HTTP/HTTPS source returned by research search. "
        "Blocks localhost, private networks, credential URLs, nonstandard ports, and unsafe redirects."
    )
    args_schema: Type[BaseModel] = FetchInput

    def _run(self, url: str, max_chars: int = 24000) -> FetchResult | ToolFailure:
        try:
            normalized = _validate_public_url(url)
            final_url, content_type, raw = _safe_fetch_bytes(normalized)
            title, text = _extract_text(content_type, raw)
            text = text[:max_chars]
            score, source_class = _source_quality(final_url)
            result = FetchResult(
                url=normalized,
                final_url=final_url,
                content_type=content_type,
                title=title,
                text=text,
                sha256=hashlib.sha256(raw).hexdigest(),
                retrieved_at=_utc_now(),
                source_quality=score,
                source_class=source_class,
            )
            _append_provenance(
                self.name,
                "fetch",
                {
                    "url": normalized,
                    "final_url": final_url,
                    "content_type": content_type,
                    "sha256": result.sha256,
                    "text_chars": len(text),
                },
            )
            return result
        except Exception as exc:
            return ToolFailure(
                message=f"Source fetch failed: {exc}",
                code="source_fetch_failed",
                retryable=False,
            )


class VerifiedKnowledgeSearchTool(BaseTool):
    name: str = "verified_knowledge_search"
    description: str = (
        "Search GrantBot's VERIFIED/APPROVED organizational fact bank. "
        "It never promotes draft or unverified working facts into grant-safe facts."
    )
    args_schema: Type[BaseModel] = KnowledgeInput

    def _run(
        self,
        query: str = "",
        max_results: int = 15,
        include_missing_keys: bool = True,
    ) -> KnowledgeBundle:
        query = query.strip().lower()
        profile = grant_safe_profile()
        tokens = {token for token in query.replace("_", " ").split() if len(token) > 1}

        scored: list[tuple[int, str, dict[str, Any]]] = []
        for fact_key, record in profile.items():
            searchable = f"{fact_key} {record.get('value', '')} {record.get('source', '')}".lower()
            score = sum(1 for token in tokens if token in searchable) if tokens else 1
            if score > 0:
                scored.append((score, fact_key, record))

        scored.sort(key=lambda row: (-row[0], row[1]))
        facts = [
            KnowledgeRecord(
                fact_key=fact_key,
                value=record.get("value"),
                status=str(record.get("status") or ""),
                source=str(record.get("source") or ""),
                confidence=record.get("confidence"),
            )
            for _, fact_key, record in scored[:max_results]
        ]

        missing_keys: list[str] = []
        if include_missing_keys:
            missing_rows = missing_facts()
            for row in missing_rows:
                key = str(row.get("fact_key") or "").strip()
                if not key:
                    continue
                searchable = f"{key} {row.get('category', '')}".lower()
                if not tokens or any(token in searchable for token in tokens):
                    missing_keys.append(key)
            missing_keys = sorted(set(missing_keys))[:max_results]

        result = KnowledgeBundle(
            query=query,
            verified_count=len(profile),
            facts=facts,
            missing_fact_keys=missing_keys,
        )
        _append_provenance(
            self.name,
            "knowledge_search",
            {
                "query": query,
                "returned_fact_keys": [fact.fact_key for fact in facts],
                "missing_fact_keys": missing_keys,
            },
        )
        return result


class GrantsGovSearchTool(BaseTool):
    name: str = "grants_gov_search"
    description: str = (
        "Search live Grants.gov opportunities using GrantBot's existing official API integration, "
        "normalization, deduplication, and ranking logic."
    )
    args_schema: Type[BaseModel] = GrantSearchInput

    def _run(self, query: str, max_results: int = 10) -> GrantSearchBundle | ToolFailure:
        try:
            discovery = discover(
                keywords=[query.strip()],
                rows_per_keyword=max_results,
                fetch_details=True,
                generate_drafts=False,
            )
            results: list[GrantOpportunityRecord] = []
            for item in discovery.results[:max_results]:
                amount = item.get("amount")
                results.append(
                    GrantOpportunityRecord(
                        opportunity_id=str(item.get("id") or ""),
                        title=str(item.get("title") or ""),
                        funder=str(item.get("funder") or ""),
                        deadline=str(item.get("deadline")) if item.get("deadline") else None,
                        amount=float(amount) if isinstance(amount, (int, float)) else None,
                        score=max(0, min(100, int(item.get("score") or 0))),
                        priority=str(item.get("priority") or ""),
                        source_url=str(item.get("source_url") or ""),
                    )
                )
            bundle = GrantSearchBundle(
                query=query.strip(),
                raw_hits=discovery.raw_hits,
                unique_hits=discovery.unique_hits,
                results=results,
            )
            _append_provenance(
                self.name,
                "grants_gov_search",
                {
                    "query": query.strip(),
                    "raw_hits": bundle.raw_hits,
                    "unique_hits": bundle.unique_hits,
                    "opportunity_ids": [row.opportunity_id for row in results],
                },
            )
            return bundle
        except Exception as exc:
            return ToolFailure(
                message=f"Grants.gov search failed: {exc}",
                code="grants_gov_search_failed",
                retryable=True,
            )


def tools_for_research_agent(agent_name: str) -> list[BaseTool]:
    mapping: dict[str, list[type[BaseTool]]] = {
        "funding_scout": [GrantsGovSearchTool, PublicWebSearchTool, SafeSourceFetchTool],
        "funder_intelligence_analyst": [PublicWebSearchTool, SafeSourceFetchTool],
        "evidence_researcher": [PublicWebSearchTool, SafeSourceFetchTool],
        "knowledge_archivist": [VerifiedKnowledgeSearchTool],
    }
    return [tool_type() for tool_type in mapping.get(agent_name, [])]
