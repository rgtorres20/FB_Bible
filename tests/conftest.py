import os

from cryptography.fernet import Fernet

# Set before app.config is imported anywhere -- Settings reads the environment
# at construction and get_settings() is cached.
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("TOKEN_STORE", "file")
os.environ.setdefault("TOKEN_FILE_PATH", ".tokens.test.json")

from app.config import Settings  # noqa: E402

# Tests must not read the developer's real .env. Without this the suite
# depends on local config: a populated SYNC_TOKEN flips /internal/sync from
# 503 to 401, and TOKEN_STORE=redis would have tests reaching for a real
# Redis. Caught when adding SYNC_TOKEN to .env broke a passing test.
Settings.model_config["env_file"] = None


# --- the no-network fence ---------------------------------------------------
# CLAUDE.md: "Tests must pass with no network and no Yahoo credentials."
# They did -- but 29 of them were *attempting* real HTTP and passing on the
# failure, which made the suite's runtime ambient rather than deterministic:
# it swung between 11s and 65s depending on how fast the outbound proxy said
# no. `/internal/sync` was the worst of it, reaching Sleeper and ESPN in
# tests that patch only adp.fetch and vegas.fetch.
#
# Blocked at the socket, deliberately, rather than at the httpx transport:
# respx and httpx.MockTransport both patch the transport, so a fence there
# either fights them or gets clobbered by them. Nothing that fakes HTTP ever
# opens a socket, so this catches exactly the calls that would have gone out
# and nothing else -- including urllib, which the mailer uses.
#
# A test that trips this is not a test that needs network. It is a test with
# an unpatched dependency, and the traceback names the URL.
import socket  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(_self, address, *args, **kwargs):
        raise OSError(f"blocked by the test fence: outbound connect to {address}")

    def refuse_create(*args, **kwargs):
        raise OSError(f"blocked by the test fence: outbound connect to {args[0] if args else '?'}")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse_create)
    yield
