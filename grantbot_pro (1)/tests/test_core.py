from grantbot.core.config import settings
from grantbot.core.database import (
    health_check,
    initialize_database,
)
from grantbot.core.utils import (
    normalize_text,
    safe_json_dumps,
    safe_json_loads,
    slugify,
)


def test_directories():
    settings.ensure_directories()

    assert settings.data_dir.exists()
    assert settings.log_dir.exists()
    assert settings.export_dir.exists()
    assert settings.backup_dir.exists()


def test_database():
    initialize_database()

    result = health_check()

    assert result["healthy"] is True
    assert result["schema_version"] >= 1

    assert "facts" in result["tables"]
    assert "funding_sources" in result["tables"]
    assert "opportunities" in result["tables"]
    assert "investors" in result["tables"]
    assert "proposals" in result["tables"]


def test_text_normalizer():
    result = normalize_text(
        "Broken   Growth\n Ministries"
    )

    assert result == "Broken Growth Ministries"


def test_slugify():
    assert (
        slugify(
            "Broken Growth Ministries!"
        )
        == "broken-growth-ministries"
    )


def test_json_helpers():
    source = {
        "hello": "world",
        "number": 7,
    }

    encoded = safe_json_dumps(
        source
    )

    decoded = safe_json_loads(
        encoded
    )

    assert decoded == source
