from grantbot.master.database import initialize_master_schema


def __getattr__(name: str):
    """Load service exports lazily to keep canonical knowledge import-safe.

    canonical.py needs master.database. Importing master.service while canonical.py
    is still initializing re-enters canonical.py and breaks the command-line tool.
    """

    if name in {"health", "learning_profile", "submission_gate", "system_versions"}:
        from grantbot.master import service

        return getattr(service, name)
    raise AttributeError(name)

__all__ = [
    "health",
    "initialize_master_schema",
    "learning_profile",
    "submission_gate",
    "system_versions",
]
