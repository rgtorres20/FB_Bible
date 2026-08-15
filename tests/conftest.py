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
