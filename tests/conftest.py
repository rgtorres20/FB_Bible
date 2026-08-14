import os

from cryptography.fernet import Fernet

# Set before app.config is imported anywhere -- Settings reads the environment
# at construction and get_settings() is cached.
os.environ.setdefault("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("TOKEN_STORE", "file")
os.environ.setdefault("TOKEN_FILE_PATH", ".tokens.test.json")
