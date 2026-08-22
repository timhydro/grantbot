from __future__ import annotations

import argparse
import json
from pathlib import Path

from grantbot import __version__
from grantbot.core.database import backup_database, initialize_database
from grantbot.core.diagnostics import system_status
from grantbot.knowledge.integrity_v23 import knowledge_status, prepare_canonical_knowledge


def pretty(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def build_parser():
    parser = argparse.ArgumentParser(
        prog="grantbot",
        description=(
            "GrantBot Pro — BrokenGrowthMinistries "
            "funding intelligence platform"
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"GrantBot Pro {__version__}",
    )

    commands = parser.add_subparsers(dest="command")

    commands.add_parser("status", help="Run complete GrantBot diagnostics.")
    commands.add_parser(
        "init",
        help="Initialize database, directories, canonical knowledge, and safe legacy migration.",
    )
    commands.add_parser(
        "knowledge",
        help="Show canonical knowledge readiness, integrity, and next questions.",
    )
    commands.add_parser("backup", help="Backup the GrantBot database.")
    commands.add_parser("tree", help="Display the GrantBot project structure.")
    apply_command = commands.add_parser(
        "apply",
        help="Build a source-backed, human-review application packet.",
    )
    opportunity_source = apply_command.add_mutually_exclusive_group(required=True)
    opportunity_source.add_argument(
        "--builtin",
        metavar="NAME",
        help="Use a packaged opportunity definition, such as publix-housing-2026.",
    )
    opportunity_source.add_argument(
        "--input",
        type=Path,
        metavar="PATH",
        help="Load a structured opportunity JSON file.",
    )
    apply_command.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Root directory for the generated human-review packet.",
    )
    apply_command.add_argument(
        "--draft-mode",
        choices=("template", "local_ai"),
        default="template",
        help="Use deterministic source-backed drafting or the configured local AI.",
    )
    apply_command.add_argument(
        "--answers",
        type=Path,
        default=None,
        help="Optional JSON object of section_id to operator-approved answer text.",
    )
    apply_command.add_argument(
        "--no-docx",
        action="store_true",
        help="Skip the Word packet while still creating JSON and Markdown artifacts.",
    )
    apply_command.add_argument(
        "--adversarial-review",
        action="store_true",
        help="Run the optional adversarial panel when local_ai drafting is selected.",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init":
        initialize_database()
        preparation = prepare_canonical_knowledge(actor="cli-init")
        pretty({
            "status": "GrantBot core initialized",
            "version": __version__,
            "knowledge_preparation": preparation,
            "knowledge_readiness": knowledge_status(),
        })
        return

    if args.command == "status":
        initialize_database()
        payload = system_status()
        payload["knowledge_v23"] = knowledge_status()
        pretty(payload)
        return

    if args.command == "knowledge":
        initialize_database()
        preparation = prepare_canonical_knowledge(actor="cli-knowledge")
        pretty({
            "preparation": preparation,
            "status": knowledge_status(),
        })
        return

    if args.command == "backup":
        initialize_database()
        path = backup_database()
        if path:
            print(f"Backup created: {path}")
        else:
            print("No database exists yet.")
        return

    if args.command == "tree":
        from grantbot.core.config import settings

        for path in sorted(settings.project_root.rglob("*")):
            relative = path.relative_to(settings.project_root)
            if ".venv" in relative.parts:
                continue
            print(relative)
        return

    if args.command == "apply":
        from grantbot.applications.production_packet import (
            build_production_application_packet,
            builtin_opportunity_path,
            load_opportunity_file,
        )

        initialize_database()
        opportunity_path = (
            builtin_opportunity_path(args.builtin)
            if args.builtin
            else args.input
        )
        opportunity = load_opportunity_file(opportunity_path)
        supplied_answers = None
        if args.answers:
            supplied_answers = json.loads(args.answers.read_text(encoding="utf-8"))
            if not isinstance(supplied_answers, dict):
                parser.error("--answers must contain a JSON object")
        packet = build_production_application_packet(
            opportunity,
            output_root=args.output_root,
            draft_mode=args.draft_mode,
            supplied_answers=supplied_answers,
            include_docx=not args.no_docx,
            run_adversarial_review=args.adversarial_review,
        )
        pretty({
            "packet_id": packet["packet_id"],
            "status": packet["status"],
            "readiness_score": packet["readiness_score"],
            "deadline_review": packet["deadline_review"],
            "hard_gate_count": len(packet["hard_gates"]),
            "hard_gates": packet["hard_gates"],
            "artifacts": packet["artifacts"],
            "human_review_required": packet["human_review_required"],
            "submission_performed": packet["submission_performed"],
            "safe_to_submit": packet["safe_to_submit"],
        })
        return

    parser.print_help()


if __name__ == "__main__":
    main()
