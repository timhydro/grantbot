from __future__ import annotations

import argparse
import json

from grantbot import __version__
from grantbot.core.database import (
    backup_database,
    initialize_database,
)
from grantbot.core.diagnostics import system_status


def pretty(value):
    print(
        json.dumps(
            value,
            indent=2,
            ensure_ascii=False,
        )
    )


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

    commands = parser.add_subparsers(
        dest="command"
    )

    commands.add_parser(
        "status",
        help="Run complete GrantBot diagnostics.",
    )

    commands.add_parser(
        "init",
        help="Initialize database and directories.",
    )

    commands.add_parser(
        "backup",
        help="Backup the GrantBot database.",
    )

    commands.add_parser(
        "tree",
        help="Display the GrantBot project structure.",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "init":
        initialize_database()
        print("GrantBot core initialized.")
        return

    if args.command == "status":
        initialize_database()
        pretty(
            system_status()
        )
        return

    if args.command == "backup":
        initialize_database()

        path = backup_database()

        if path:
            print(
                f"Backup created: {path}"
            )
        else:
            print(
                "No database exists yet."
            )

        return

    if args.command == "tree":
        from grantbot.core.config import settings

        for path in sorted(
            settings.project_root.rglob("*")
        ):
            relative = path.relative_to(
                settings.project_root
            )

            if ".venv" in relative.parts:
                continue

            print(relative)

        return

    parser.print_help()


if __name__ == "__main__":
    main()
