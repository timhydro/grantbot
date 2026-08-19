"""
Health check system for monitoring GrantBot components.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any

from grantbot.core.config import settings
from grantbot.core.database import connection
from grantbot.core.logging_config import get_logger

logger = get_logger("health")


@dataclass
class HealthStatus:
    """Overall system health status."""
    status: str  # "healthy" | "degraded" | "unhealthy"
    timestamp: str
    version: str
    environment: str
    components: dict[str, Any]
    checks_passed: int
    checks_failed: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_database() -> dict[str, Any]:
    """Check database connectivity and schema."""
    try:
        with connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
            table_count = cursor.fetchone()[0]
            
            if table_count == 0:
                return {
                    "status": "unhealthy",
                    "error": "No tables found in database",
                }
            
            cursor.execute("PRAGMA database_list")
            _ = cursor.fetchall()
            
            return {
                "status": "healthy",
                "database": str(settings.database_path),
                "tables": table_count,
            }
    except sqlite3.Error as exc:
        logger.error("Database check failed: %s", exc)
        return {
            "status": "unhealthy",
            "error": str(exc),
        }
    except Exception as exc:
        logger.error("Unexpected database check error: %s", exc)
        return {
            "status": "unhealthy",
            "error": f"Unexpected error: {type(exc).__name__}",
        }


def check_ollama() -> dict[str, Any]:
    """Check local AI availability."""
    if not settings.ollama_enabled:
        return {
            "status": "disabled",
            "reason": "OLLAMA_ENABLED=false",
        }
    
    try:
        from grantbot.writing.ollama_provider import OllamaProvider
        
        provider = OllamaProvider()
        health = provider.health()
        
        if not health.get("available"):
            return {
                "status": "unavailable",
                "error": health.get("error", "Unknown error"),
                "model": settings.ollama_model,
            }
        
        if not health.get("model_installed"):
            return {
                "status": "degraded",
                "message": f"Model {settings.ollama_model} not yet downloaded",
                "url": settings.ollama_url,
            }
        
        return {
            "status": "healthy",
            "url": settings.ollama_url,
            "model": settings.ollama_model,
            "model_installed": True,
        }
    except Exception as exc:
        logger.warning("Ollama check failed: %s", exc)
        return {
            "status": "unavailable",
            "error": str(exc),
        }


def check_directories() -> dict[str, Any]:
    """Check required directories exist and are writable."""
    issues = []
    
    dirs_to_check = [
        ("data", settings.data_dir),
        ("logs", settings.log_dir),
        ("exports", settings.export_dir),
        ("backups", settings.backup_dir),
    ]
    
    for name, path in dirs_to_check:
        if not path.exists():
            issues.append(f"{name} directory missing: {path}")
        elif not path.is_dir():
            issues.append(f"{name} exists but is not a directory: {path}")
        elif not os.access(path, os.W_OK):
            issues.append(f"{name} directory not writable: {path}")
    
    if issues:
        return {
            "status": "degraded",
            "issues": issues,
        }
    
    return {
        "status": "healthy",
        "data_dir": str(settings.data_dir),
        "logs_dir": str(settings.log_dir),
        "exports_dir": str(settings.export_dir),
        "backups_dir": str(settings.backup_dir),
    }


def check_recent_discovery() -> dict[str, Any]:
    """Check if discovery runs are recent."""
    try:
        with connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) as runs, 
                       MAX(created_at) as latest
                FROM discovery_runs
                WHERE created_at > datetime('now', '-7 days')
                """
            )
            result = cursor.fetchone()
            
            if result and result[0] > 0:
                return {
                    "status": "healthy",
                    "discovery_runs_7d": result[0],
                    "latest_run": result[1],
                }
            else:
                return {
                    "status": "degraded",
                    "discovery_runs_7d": 0,
                    "message": "No discovery runs in past 7 days",
                }
    except Exception as exc:
        logger.warning("Discovery check failed: %s", exc)
        return {
            "status": "unknown",
            "error": str(exc),
        }


def get_health() -> HealthStatus:
    """Get overall system health status."""
    from grantbot import __version__
    import os
    
    checks = {
        "database": check_database(),
        "ollama": check_ollama(),
        "directories": check_directories(),
        "discovery": check_recent_discovery(),
    }
    
    failed = sum(
        1 for c in checks.values() 
        if c.get("status") in ("unhealthy", "unavailable")
    )
    passed = len(checks) - failed
    
    # Determine overall status
    if failed > 0:
        overall = "unhealthy"
    elif any(c.get("status") == "degraded" for c in checks.values()):
        overall = "degraded"
    else:
        overall = "healthy"
    
    return HealthStatus(
        status=overall,
        timestamp=datetime.now(timezone.utc).isoformat(),
        version=__version__,
        environment=settings.environment,
        components=checks,
        checks_passed=passed,
        checks_failed=failed,
    )
