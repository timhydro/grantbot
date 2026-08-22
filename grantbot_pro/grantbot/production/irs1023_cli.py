from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_ROOT / ".env"
OUTPUT_DIR = PROJECT_ROOT / "applications" / "irs1023_v29"
STATUS_FILENAME = "production_model_status.json"
RESULT_FILENAME = "form_1023_part_iv_1.json"


def load_project_environment() -> Path:
    """Load GrantBot's project .env explicitly without python-dotenv stack discovery."""
    if ENV_PATH.exists():
        load_dotenv(dotenv_path=ENV_PATH, override=False)
    return ENV_PATH


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _print_model_plan(status: dict[str, Any]) -> tuple[bool, int]:
    pipeline = status["production_pipeline"]
    roles = pipeline["roles"]

    print()
    print("=== MULTI-AI PRODUCTION MODEL PLAN ===")
    for role, info in roles.items():
        print(
            f"{role:18} "
            f"provider={info.get('provider')}  "
            f"model={info.get('model')}  "
            f"available={info.get('available')}"
        )

    print()
    print("=== PRODUCTION CONTROL GATES ===")
    print(
        "Master Writer reused for revision:",
        pipeline.get("master_writer_reused_for_revision"),
    )
    print(
        "Grant Quality Reviewer can rewrite:",
        pipeline.get("reviewer_can_rewrite_final_prose"),
    )
    print(
        "Readiness Officer can rewrite:",
        pipeline.get("readiness_can_rewrite_final_prose"),
    )
    print("Human review required:", pipeline.get("human_review_required"))

    identities = {
        (
            str(info.get("provider") or ""),
            str(info.get("model") or ""),
        )
        for info in roles.values()
        if info.get("available")
    }

    print()
    print("Distinct active AI/model identities:", len(identities))
    return bool(pipeline.get("available")), len(identities)


def _print_answer(result: dict[str, Any], result_path: Path) -> int:
    answers = result.get("answers") or []
    if not answers:
        print("ERROR: No Part IV-1 answer was produced.")
        print(f"Diagnostic file: {result_path}")
        return 22

    answer = answers[0]
    quality = answer.get("deterministic_quality") or {}
    claims = answer.get("claim_integrity") or {}
    voice = answer.get("voice_integrity") or {}

    print()
    print("============================================================")
    print(" FORM 1023 PART IV-1 — MASTER WRITER RESULT")
    print("============================================================")
    print()
    print("STATUS:")
    print(answer.get("status"))
    print()
    print("FINAL ANSWER:")
    print(answer.get("final_answer") or "[NO FINAL ANSWER — REMEDIATION REQUIRED]")
    print()
    print("QUALITY SCORE:")
    print(quality.get("score"))
    print()
    print("QUALITY PASSED:")
    print(quality.get("passed"))
    print()
    print("CLAIM INTEGRITY:")
    print("SAFE" if claims.get("safe") else "REMEDIATION REQUIRED")
    print()
    print("VOICE INTEGRITY:")
    print("PASSED" if voice.get("passed") else "REMEDIATION REQUIRED")
    print()
    print("PRODUCTION ARTIFACT:")
    print(answer.get("artifact_path"))
    print()
    print("RESULT JSON:")
    print(result_path)
    print()
    print("FORM 1023 REVIEW PACKET:")
    print(result.get("folder"))
    print()
    print("============================================================")
    print(" PART IV-1 COMPLETE — HUMAN REVIEW REQUIRED")
    print("============================================================")
    return 0


def main() -> None:
    load_project_environment()

    # Import after loading the explicit project environment so provider keys and
    # model-routing configuration are present before GrantBot resolves runtimes.
    from grantbot import __version__
    from grantbot.production.master_tool import (
        build_irs1023_production_packet,
        production_status,
    )

    print("============================================================")
    print(" GRANTBOT PRO v29 — FORM 1023 PRODUCTION ENGINE")
    print("============================================================")
    print()
    print("=== GRANTBOT VERSION ===")
    print(__version__)

    if __version__ != "29.0.0":
        raise SystemExit(
            f"ERROR: Expected GrantBot Pro 29.0.0; found {__version__}"
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    status = production_status()
    status_path = OUTPUT_DIR / STATUS_FILENAME
    _write_json(status_path, status)

    available, identity_count = _print_model_plan(status)
    if not available:
        print()
        print("STOPPED: Production AI pipeline is incomplete.")
        print(f"Diagnostic file: {status_path}")
        raise SystemExit(20)

    if identity_count < 2:
        print()
        print("STOPPED: Every role resolved to the same AI/model.")
        print("No Form 1023 prose was generated.")
        print(f"Diagnostic file: {status_path}")
        raise SystemExit(21)

    print()
    print("=== GENERATING IRS FORM 1023 PART IV-1 ===")
    result = build_irs1023_production_packet(
        generate_ai=True,
        question_ids=["IV-1"],
    )
    result_path = OUTPUT_DIR / RESULT_FILENAME
    _write_json(result_path, result)

    exit_code = _print_answer(result, result_path)
    if exit_code:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
