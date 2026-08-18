from __future__ import annotations

import hashlib
import json
import os
import time

from pathlib import Path
from typing import Any

from grantbot.core.config import settings


class FileCache:

    def __init__(
        self,
        directory: Path | None = None,
    ):
        self.directory = (
            directory
            or settings.data_dir
            / "cache"
            / "http"
        )

        self.directory.mkdir(
            parents=True,
            exist_ok=True,
        )

    @staticmethod
    def key_for(
        method: str,
        url: str,
        payload: Any = None,
    ) -> str:

        blob = json.dumps(
            {
                "method":
                    method.upper(),

                "url":
                    url,

                "payload":
                    payload,
            },
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")

        return hashlib.sha256(
            blob
        ).hexdigest()

    def _path(
        self,
        key: str,
    ) -> Path:

        return (
            self.directory
            / f"{key}.json"
        )

    def get(
        self,
        key: str,
        ttl: int,
    ) -> dict | None:

        path = self._path(
            key
        )

        if not path.exists():
            return None

        try:
            payload = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )

            created = float(
                payload.get(
                    "created",
                    0,
                )
            )

            if (
                ttl >= 0
                and time.time()
                - created
                > ttl
            ):
                try:
                    path.unlink()
                except OSError:
                    pass

                return None

            return payload.get(
                "value"
            )

        except Exception:
            try:
                path.unlink()
            except OSError:
                pass

            return None

    def set(
        self,
        key: str,
        value: dict,
    ) -> None:

        path = self._path(
            key
        )

        temp = path.with_suffix(
            ".tmp"
        )

        temp.write_text(
            json.dumps(
                {
                    "created":
                        time.time(),

                    "value":
                        value,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        os.replace(
            temp,
            path,
        )

    def clear(self) -> int:

        count = 0

        for path in self.directory.glob(
            "*.json"
        ):
            try:
                path.unlink()
                count += 1

            except OSError:
                pass

        return count
