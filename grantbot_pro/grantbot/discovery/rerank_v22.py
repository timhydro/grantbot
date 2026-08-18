from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any


DOMAIN_RULES: tuple[tuple[str, int, tuple[str, ...]], ...] = (
    (
        "reentry",
        25,
        (
            "reentry",
            "re-entry",
            "returning citizen",
            "formerly incarcerated",
            "justice involved",
            "justice-involved",
            "offender reintegration",
            "post-release",
        ),
    ),
    (
        "homelessness",
        20,
        (
            "homeless",
            "homelessness",
            "unsheltered",
            "continuum of care",
        ),
    ),
    (
        "housing",
        20,
        (
            "housing",
            "shelter",
            "supportive housing",
            "transitional housing",
            "affordable housing",
            "permanent supportive housing",
        ),
    ),
    (
        "workforce",
        18,
        (
            "workforce",
            "job training",
            "vocational",
            "career pathway",
            "apprenticeship",
            "skills training",
        ),
    ),
    (
        "employment",
        12,
        (
            "employment",
            "job placement",
            "occupational",
            "economic mobility",
        ),
    ),
    (
        "recovery_support",
        10,
        (
            "recovery support",
            "substance use",
            "behavioral health",
            "peer recovery",
        ),
    ),
    (
        "community_development",
        8,
        (
            "community development",
            "neighborhood revitalization",
            "community services",
        ),
    ),
    (
        "capital",
        8,
        (
            "capital",
            "construction",
            "facility",
            "facilities",
            "infrastructure",
        ),
    ),
    (
        "economic_development",
        8,
        (
            "economic development",
            "economic opportunity",
            "entrepreneurship",
            "small business development",
        ),
    ),
)

HARD_REJECT_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "academic or research fellowship",
        re.compile(
            r"\b(postdoctoral|doctoral|graduate|research)\s+fellowship\b|"
            r"\bdissertation\b|\bfaculty research\b",
            re.I,
        ),
    ),
    (
        "specialized higher-education eligibility",
        re.compile(
            r"\b(institutions? of higher education|tribal colleges?|"
            r"minority[- ]serving institutions?|university centers?)\b",
            re.I,
        ),
    ),
    (
        "specialized commercial research eligibility",
        re.compile(
            r"\b(SBIR|STTR|small business innovation research|"
            r"small business technology transfer)\b",
            re.I,
        ),
    ),
    (
        "student scholarship or fellowship",
        re.compile(r"\b(student scholarship|graduate scholarship|student fellowship)\b", re.I),
    ),
)

LOW_FIT_TERMS = (
    "basic research",
    "clinical trial",
    "genomic",
    "laboratory research",
    "faculty",
    "museum collection",
    "species conservation",
    "fisheries research",
    "agricultural research",
)

CORE_PHRASE_BONUSES: tuple[tuple[str, int], ...] = (
    ("continuum of care", 25),
    ("supportive housing", 20),
    ("transitional housing", 20),
    ("homelessness demonstration", 20),
    ("reentry employment", 18),
    ("reentry workforce", 18),
    ("justice involved employment", 18),
    ("workforce development", 10),
    ("community development block grant", 12),
)

SYNERGY_BONUSES: tuple[tuple[frozenset[str], int, str], ...] = (
    (frozenset({"reentry", "workforce"}), 15, "reentry + workforce alignment"),
    (frozenset({"reentry", "employment"}), 15, "reentry + employment alignment"),
    (frozenset({"homelessness", "housing"}), 15, "homelessness + housing alignment"),
    (frozenset({"housing", "workforce"}), 10, "housing + workforce alignment"),
    (
        frozenset({"community_development", "workforce"}),
        8,
        "community development + workforce alignment",
    ),
)


@dataclass(frozen=True, slots=True)
class MissionScore:
    score: int
    priority: str
    matched_domains: list[str]
    rejection_reasons: list[str]
    strengths: list[str]
    weaknesses: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "priority": self.priority,
            "matched_domains": list(self.matched_domains),
            "rejection_reasons": list(self.rejection_reasons),
            "strengths": list(self.strengths),
            "weaknesses": list(self.weaknesses),
        }


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_clean(item) for item in value if _clean(item)]
    if value in (None, ""):
        return []
    return [_clean(value)]


def _priority(score: int, rejected: bool) -> str:
    if rejected:
        return "REJECT"
    if score >= 50:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    if score >= 15:
        return "REVIEW"
    return "REJECT"


def score_opportunity(
    *,
    title: str,
    agency: str = "",
    matched_keywords: list[str] | None = None,
    assistance_listings: list[str] | None = None,
) -> MissionScore:
    title = _clean(title)
    agency = _clean(agency)
    keywords = _list(matched_keywords)
    listings = _list(assistance_listings)
    text = " ".join([title, agency, *keywords, *listings]).casefold()

    rejection_reasons = [
        reason
        for reason, pattern in HARD_REJECT_RULES
        if pattern.search(text)
    ]

    matched_domains: list[str] = []
    strengths: list[str] = []
    weaknesses: list[str] = []
    score = 0

    for domain, weight, terms in DOMAIN_RULES:
        matched = [term for term in terms if term in text]
        if not matched:
            continue
        matched_domains.append(domain)
        score += weight
        strengths.append(f"{domain} mission fit (+{weight})")

    domain_set = frozenset(matched_domains)
    for required, bonus, label in SYNERGY_BONUSES:
        if required.issubset(domain_set):
            score += bonus
            strengths.append(f"{label} (+{bonus})")

    title_folded = title.casefold()
    for phrase, bonus in CORE_PHRASE_BONUSES:
        if phrase in title_folded:
            score += bonus
            strengths.append(f"high-value phrase: {phrase} (+{bonus})")

    distinct_keywords = {item.casefold() for item in keywords if item}
    if distinct_keywords:
        keyword_bonus = min(10, len(distinct_keywords) * 2)
        score += keyword_bonus
        strengths.append(f"matched across {len(distinct_keywords)} discovery keyword(s) (+{keyword_bonus})")

    low_fit_hits = [term for term in LOW_FIT_TERMS if term in text]
    if low_fit_hits and len(matched_domains) < 2:
        penalty = min(30, 10 + 5 * len(low_fit_hits))
        score -= penalty
        weaknesses.append(
            "specialized low-fit signals: " + ", ".join(low_fit_hits) + f" (-{penalty})"
        )

    if not matched_domains:
        weaknesses.append("no direct BrokenGrowth mission domain detected")

    if rejection_reasons:
        score = 0
        weaknesses.append("hard eligibility/specialization rejection triggered")

    bounded = max(0, min(100, score))
    return MissionScore(
        score=bounded,
        priority=_priority(bounded, bool(rejection_reasons)),
        matched_domains=matched_domains,
        rejection_reasons=rejection_reasons,
        strengths=strengths,
        weaknesses=weaknesses,
    )


def rerank_payload(payload: dict[str, Any]) -> dict[str, Any]:
    output = copy.deepcopy(payload)
    items = output.get("items")
    if not isinstance(items, list):
        output["ranking_version"] = "22.0"
        return output

    reranked: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        analysis_level = _clean(item.get("analysis_level")).upper()
        existing_blockers = _list(item.get("blockers"))

        mission = score_opportunity(
            title=_clean(item.get("title")),
            agency=_clean(item.get("agency")),
            matched_keywords=_list(item.get("matched_keywords")),
            assistance_listings=_list(item.get("assistance_listings")),
        )

        item["v22_mission_score"] = mission.score
        item["v22_mission_domains"] = mission.matched_domains
        item["v22_ranking_reasons"] = mission.strengths + mission.weaknesses

        if analysis_level != "FULL":
            item["fit_score"] = mission.score
            item["final_score"] = mission.score
            item["priority"] = mission.priority
            item["matched_domains"] = mission.matched_domains
            item["rejection_reasons"] = list(
                dict.fromkeys(_list(item.get("rejection_reasons")) + mission.rejection_reasons)
            )
            item["strengths"] = list(
                dict.fromkeys(_list(item.get("strengths")) + mission.strengths)
            )
            item["weaknesses"] = list(
                dict.fromkeys(_list(item.get("weaknesses")) + mission.weaknesses)
            )
        elif existing_blockers:
            item["priority"] = "REJECT"

        reranked.append(item)

    rank = {"HIGH": 0, "MEDIUM": 1, "REVIEW": 2, "REJECT": 3}
    reranked.sort(
        key=lambda item: (
            rank.get(_clean(item.get("priority")).upper(), 4),
            -int(item.get("final_score", 0) or 0),
            _clean(item.get("title")).casefold(),
        )
    )

    output["items"] = reranked
    output["ranking_version"] = "22.0"
    output["high_count"] = sum(item.get("priority") == "HIGH" for item in reranked)
    output["medium_count"] = sum(item.get("priority") == "MEDIUM" for item in reranked)
    output["review_count"] = sum(item.get("priority") == "REVIEW" for item in reranked)
    output["reject_count"] = sum(item.get("priority") == "REJECT" for item in reranked)
    return output
