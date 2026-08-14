"""Local-dev token store: one encrypted JSON file on disk.

Not for serverless -- the filesystem is read-only and ephemeral there.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .base import TokenSet
from .crypto import TokenCipher


class FileTokenStore:
    def __init__(self, path: str, cipher: TokenCipher) -> None:
        self._path = Path(path)
        self._cipher = cipher
        self._lock = asyncio.Lock()

    def _read_all(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_all(self, data: dict[str, str]) -> None:
        # Write-then-rename so an interrupted write can't truncate the file.
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    async def get(self, key: str) -> TokenSet | None:
        async with self._lock:
            blob = self._read_all().get(key)
        if not blob:
            return None
        payload = self._cipher.decrypt(blob)
        return TokenSet.from_dict(payload) if payload else None

    async def put(self, key: str, tokens: TokenSet) -> None:
        async with self._lock:
            data = self._read_all()
            data[key] = self._cipher.encrypt(tokens.to_dict())
            self._write_all(data)

    async def delete(self, key: str) -> None:
        async with self._lock:
            data = self._read_all()
            if data.pop(key, None) is not None:
                self._write_all(data)
