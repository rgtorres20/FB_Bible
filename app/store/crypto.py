"""Envelope encryption for tokens at rest.

A Yahoo refresh token is long-lived and grants read access to the account's
fantasy data, so it never gets written in the clear -- not to .tokens.json,
not to Redis.
"""

from __future__ import annotations

import json

from cryptography.fernet import Fernet, InvalidToken


class TokenCipher:
    def __init__(self, key: str) -> None:
        if not key:
            raise ValueError(
                "TOKEN_ENCRYPTION_KEY is not set. Generate one with:\n"
                '  python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            )
        self._fernet = Fernet(key.encode())

    def encrypt(self, data: dict) -> str:
        return self._fernet.encrypt(json.dumps(data).encode()).decode()

    def decrypt(self, blob: str) -> dict | None:
        """Returns None if the blob can't be read -- treat as "not signed in"."""
        try:
            return json.loads(self._fernet.decrypt(blob.encode()))
        except (InvalidToken, ValueError):
            return None
