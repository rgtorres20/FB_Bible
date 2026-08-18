"""Settings, loaded from the environment (or a local .env)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Yahoo's OAuth2 and Fantasy Sports endpoints.
YAHOO_AUTHORIZE_URL = "https://api.login.yahoo.com/oauth2/request_auth"
YAHOO_TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
YAHOO_API_BASE = "https://fantasysports.yahooapis.com/fantasy/v2"

# Branches whose deploys are pre-production regardless of what the host calls
# them. See Settings.stage.
PREVIEW_BRANCHES = frozenset({"beta"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Yahoo app credentials (from developer.yahoo.com/apps) -------------
    yahoo_client_id: str = ""
    yahoo_client_secret: str = ""
    # Must match the callback registered on the Yahoo app, exactly.
    yahoo_redirect_uri: str = "https://localhost:8000/auth/yahoo/callback"
    # fspt-r = Fantasy Sports read. Use fspt-w only if we ever set lineups.
    yahoo_scope: str = "fspt-r"

    # --- The two leagues from the blueprint --------------------------------
    # Yahoo accepts the bare game code "nfl" to mean the current NFL season,
    # so these keep working year over year without hardcoding a game_key.
    league_keys: list[str] = Field(default_factory=lambda: ["nfl.l.192426", "nfl.l.811739"])

    # --- Token storage ------------------------------------------------------
    # "file" for local dev, "redis" for serverless (no writable disk).
    token_store: Literal["file", "redis"] = "file"
    token_file_path: str = ".tokens.json"
    # Polled news items. Shares the redis/file decision with the token store.
    feed_file_path: str = "data/feeds.json"
    redis_url: str = ""

    # Encrypts tokens at rest. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    token_encryption_key: str = ""

    # --- App ----------------------------------------------------------------
    # Signs the OAuth `state` parameter so callbacks can't be forged.
    session_secret: str = "dev-only-change-me"
    # Shared secret for POST /internal/sync. Empty disables scheduled sync.
    sync_token: str = ""
    # Origins allowed to call this API (the Fantasy Bible page).
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    log_level: str = "INFO"

    # Vercel sets VERCEL_ENV to "production" on main, "preview" on branch
    # deploys. Empty means a local/container run. This is what makes a beta
    # deploy announce itself instead of impersonating prod.
    vercel_env: str = ""
    # Explicit override, because VERCEL_ENV cannot express this: a second
    # Vercel project pointed at a pre-production branch still reports
    # "production" for its own deploy, so it renders with no BETA badge and
    # is indistinguishable from the real thing (verified 2026-08-18 against
    # fb-bible.vercel.app). Set FB_STAGE=preview there and it announces
    # itself. Prod sets nothing.
    fb_stage: str = ""
    # Set by Vercel to the branch a deploy was built from. The fallback that
    # makes the override above unnecessary: preprod builds from `beta`, and a
    # branch name is something the deploy already knows about itself, so the
    # badge does not depend on anyone remembering a dashboard setting.
    vercel_git_commit_ref: str = ""

    @property
    def stage(self) -> str:
        """Which deployment is answering: "production", "preview" or "local".

        Precedence is deliberate. An explicit FB_STAGE always wins. Failing
        that, a deploy built from a pre-production branch is a preview no
        matter what Vercel calls it -- which is the whole problem, since a
        second project's own deploy reports "production". Only then do we
        take Vercel's word for it.
        """
        if self.fb_stage:
            return self.fb_stage
        if self.vercel_git_commit_ref.strip().lower() in PREVIEW_BRANCHES:
            return "preview"
        return self.vercel_env or "local"

    @property
    def configured(self) -> bool:
        return bool(self.yahoo_client_id and self.yahoo_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
