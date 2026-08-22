from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(
    os.environ.get(
        "GRANTBOT_ROOT",
        Path(__file__).resolve().parents[2],
    )
).expanduser().resolve()

load_dotenv(PROJECT_ROOT / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)

    if raw is None:
        return default

    return raw.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "enabled",
    }


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)

    if raw is None:
        return default

    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(
            f"{name} must be an integer. Received {raw!r}."
        ) from exc


def env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name, "").strip()
    path = Path(raw).expanduser() if raw else default
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


@dataclass(frozen=True)
class Settings:
    project_root: Path = PROJECT_ROOT

    data_dir: Path = field(
        default_factory=lambda: env_path("GRANTBOT_DATA_DIR", PROJECT_ROOT / "data")
    )
    log_dir: Path = field(
        default_factory=lambda: env_path("GRANTBOT_LOG_DIR", PROJECT_ROOT / "logs")
    )
    export_dir: Path = field(
        default_factory=lambda: env_path("GRANTBOT_EXPORT_DIR", PROJECT_ROOT / "exports")
    )
    backup_dir: Path = field(
        default_factory=lambda: env_path("GRANTBOT_BACKUP_DIR", PROJECT_ROOT / "backups")
    )

    environment: str = os.getenv(
        "GRANTBOT_ENVIRONMENT",
        "development",
    )

    organization_name: str = os.getenv(
        "GRANTBOT_ORGANIZATION",
        "BrokenGrowthMinistries",
    )

    host: str = os.getenv(
        "GRANTBOT_HOST",
        "127.0.0.1",
    )

    port: int = env_int(
        "GRANTBOT_PORT",
        5000,
    )

    debug: bool = env_bool(
        "GRANTBOT_DEBUG",
        False,
    )

    log_level: str = os.getenv(
        "GRANTBOT_LOG_LEVEL",
        "INFO",
    ).upper()

    request_timeout: int = env_int(
        "GRANTBOT_REQUEST_TIMEOUT",
        30,
    )

    ollama_enabled: bool = env_bool(
        "OLLAMA_ENABLED",
        True,
    )

    ollama_url: str = os.getenv(
        "OLLAMA_URL",
        "http://127.0.0.1:11434",
    )

    ollama_model: str = os.getenv(
        "OLLAMA_MODEL",
        "llama3.2:3b",
    )

    @property
    def database_path(self) -> Path:
        raw = os.getenv(
            "GRANTBOT_DATABASE",
            "data/grantbot.db",
        )

        path = Path(raw)

        if not path.is_absolute():
            path = self.project_root / path

        return path.resolve()

    def ensure_directories(self) -> None:
        directories = [
            self.data_dir,
            self.log_dir,
            self.export_dir,
            self.backup_dir,
            self.data_dir / "imports",
            self.data_dir / "cache",
            self.data_dir / "knowledge",
            self.data_dir / "funding",
            self.data_dir / "investors",
            self.data_dir / "nofo",
        ]

        for directory in directories:
            directory.mkdir(
                parents=True,
                exist_ok=True,
            )


settings = Settings()
settings.ensure_directories()
