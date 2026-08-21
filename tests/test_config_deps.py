"""Two small modules whose failure modes are large.

`config.stage` decides whether a deploy wears the BETA badge, and
`deps.get_store` decides whether a missing setting reads as a named
problem or as a bare 500. Neither had a test until Aug 21.

The stage precedence in particular is not obvious and was bought with a
real incident: the beta project's own Vercel deploy reports itself as
"production", so taking Vercel's word for it puts the preview badge on
nothing and lets a preview look like prod
([docs/ENVIRONMENTS.md](../docs/ENVIRONMENTS.md)).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app import deps
from app.config import Settings


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


# --- which deployment is answering --------------------------------------


def test_a_plain_local_run_is_local():
    assert _settings().stage == "local"


def test_vercel_production_is_production():
    assert _settings(vercel_env="production").stage == "production"


def test_the_beta_branch_is_a_preview_whatever_vercel_calls_it():
    """The incident this precedence exists for. The beta project's own
    deploy reports vercel_env=production, so trusting that alone would
    serve an unbadged preview that looks exactly like prod."""
    beta = _settings(vercel_env="production", vercel_git_commit_ref="beta")
    assert beta.stage == "preview"


def test_the_branch_check_is_case_and_whitespace_insensitive():
    """Branch names arrive from an environment variable, and a stray
    space would silently drop the badge."""
    for ref in ("Beta", "  beta  ", "BETA"):
        assert _settings(vercel_env="production", vercel_git_commit_ref=ref).stage == "preview"


def test_an_explicit_stage_always_wins():
    """The manual override, for a deploy neither rule describes."""
    forced = _settings(fb_stage="preview", vercel_env="production", vercel_git_commit_ref="main")
    assert forced.stage == "preview"
    assert _settings(fb_stage="production", vercel_git_commit_ref="beta").stage == "production"


def test_main_is_not_a_preview():
    """The other direction, and the one that would be embarrassing: a
    production deploy must not wear a BETA badge."""
    assert _settings(vercel_env="production", vercel_git_commit_ref="main").stage == "production"


# --- is Yahoo linked at all ---------------------------------------------


def test_configured_needs_both_halves_of_the_yahoo_credential():
    assert not _settings().configured
    assert not _settings(yahoo_client_id="id").configured
    assert not _settings(yahoo_client_secret="secret").configured
    assert _settings(yahoo_client_id="id", yahoo_client_secret="secret").configured


# --- a missing setting is named, never a bare 500 ------------------------


def test_an_unconfigured_store_is_a_503_naming_the_setting(monkeypatch):
    """The mystery-failure this project's /health exists to prevent. A
    missing TOKEN_ENCRYPTION_KEY raises ValueError, which FastAPI would
    otherwise surface as "Internal Server Error" and nothing else."""

    def unconfigured(_settings):
        raise ValueError("TOKEN_ENCRYPTION_KEY is not set")

    deps._store_singleton.cache_clear()
    monkeypatch.setattr(deps, "build_token_store", unconfigured)
    with pytest.raises(HTTPException) as exc:
        deps.get_store()
    deps._store_singleton.cache_clear()
    assert exc.value.status_code == 503
    assert "TOKEN_ENCRYPTION_KEY" in exc.value.detail


def test_the_error_names_the_setting_but_never_its_value(monkeypatch):
    """Repo rule: never log or return a token. This detail is rendered to
    an HTTP client."""

    def unconfigured(_settings):
        raise ValueError("TOKEN_ENCRYPTION_KEY is not set")

    deps._store_singleton.cache_clear()
    monkeypatch.setattr(deps, "build_token_store", unconfigured)
    with pytest.raises(HTTPException) as exc:
        deps.get_store()
    deps._store_singleton.cache_clear()
    assert "secret" not in exc.value.detail.lower()


def test_the_store_is_built_once_and_reused(monkeypatch):
    """Vercel runs this per request. Rebuilding the store each time would
    open a new Redis client per page load."""
    built = []

    def counting(_settings):
        built.append(1)
        return object()

    deps._store_singleton.cache_clear()
    monkeypatch.setattr(deps, "build_token_store", counting)
    first, second = deps.get_store(), deps.get_store()
    deps._store_singleton.cache_clear()
    assert first is second
    assert len(built) == 1


def test_phase_two_uses_one_named_user_key():
    """Single-user by design, but named — so multi-user is a routing
    change later rather than a storage migration."""
    assert deps.DEFAULT_USER_KEY == "owner"
