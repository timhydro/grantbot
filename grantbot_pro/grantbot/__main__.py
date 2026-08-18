from __future__ import annotations

import argparse
import json

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

    parser.print_help()


if __name__ == "__main__":
    main()
