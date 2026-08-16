from __future__ import annotations

import platform
import sys

from grantbot import (
    __app_name__,
    __organization__,
    __version__,
)

from grantbot.core.config import settings
from grantbot.core.database import health_check


def system_status() -> dict:
    return {
        "application": __app_name__,
        "version": __version__,
        "organization": __organization__,
        "environment":
            settings.environment,
        "python":
            sys.version.split()[0],
        "platform":
            platform.platform(),
        "project_root":
            str(
                settings.project_root
            ),
        "host":
            settings.host,
        "port":
            settings.port,
        "ollama_enabled":
            settings.ollama_enabled,
        "database":
            health_check(),
    }
