"""Route-level checks that need no Yahoo credentials and no network."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_configuration():
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["encryption_configured"] is True
    assert body["league_keys"] == ["nfl.l.192426", "nfl.l.811739"]


def test_login_is_unavailable_without_credentials():
    # No YAHOO_CLIENT_ID in the test env -- should say so, not 500.
    response = client.get("/auth/yahoo/login", follow_redirects=False)
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_callback_rejects_bad_state():
    response = client.get("/auth/yahoo/callback", params={"code": "x", "state": "forged"})
    assert response.status_code == 400
    assert "state" in response.json()["detail"].lower()


def test_callback_requires_code():
    response = client.get("/auth/yahoo/callback", params={"state": "whatever"})
    assert response.status_code == 400


def test_callback_surfaces_yahoo_denial():
    response = client.get(
        "/auth/yahoo/callback",
        params={"error": "access_denied", "error_description": "user said no"},
    )
    assert response.status_code == 400
    assert "access_denied" in response.json()["detail"]


def test_api_returns_401_when_not_linked():
    response = client.get("/api/leagues")
    assert response.status_code == 401
    assert "/auth/yahoo/login" in response.json()["detail"]


def test_unconfigured_token_store_returns_503_not_500(monkeypatch):
    """A missing TOKEN_ENCRYPTION_KEY must name itself, not surface as a bare
    500. This is what the live deploy did before the fix."""
    import pytest
    from fastapi import HTTPException

    from app import deps

    def boom():
        raise ValueError("TOKEN_ENCRYPTION_KEY is not set. Generate one with: ...")

    monkeypatch.setattr(deps, "_store_singleton", boom)

    with pytest.raises(HTTPException) as exc:
        deps.get_store()

    assert exc.value.status_code == 503
    assert "TOKEN_ENCRYPTION_KEY" in exc.value.detail


def test_sync_requires_a_token():
    """SYNC_TOKEN is unset in tests, so scheduled sync must report itself
    disabled rather than quietly polling five publishers."""
    response = client.post("/internal/sync")
    assert response.status_code == 503
    assert "SYNC_TOKEN" in response.json()["detail"]


def test_feeds_endpoint_is_readable_when_empty():
    response = client.get("/api/feeds")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_bare_domain_redirects_to_the_app():
    """A JSON 404 at the root reads as "nothing on screen" to anyone who types
    the domain without /app/."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] in {"/app/", "/docs"}


def test_app_page_injects_the_mobile_stylesheet():
    """index.html on disk stays pristine; the <link> exists only in the
    served response, like the feeds overlay does for data."""
    from pathlib import Path

    response = client.get("/app/")
    assert response.status_code == 200
    assert '<link rel="stylesheet" href="mobile.css">' in response.text
    assert '<script src="mobile.js" defer></script>' in response.text

    on_disk = Path("frontend/index.html").read_text(encoding="utf-8")
    assert "mobile.css" not in on_disk


def test_mobile_css_is_served():
    response = client.get("/app/mobile.css")
    assert response.status_code == 200
    assert "@media (max-width: 768px)" in response.text


def test_mobile_js_is_served():
    response = client.get("/app/mobile.js")
    assert response.status_code == 200
    assert "fb-menu-btn" in response.text


def test_ffbets_lands_on_predictions_with_builder_shelved():
    """Serve-time edits only: the file on disk keeps the builder intact."""
    from pathlib import Path

    served = client.get("/app/").text
    assert 'gdMode: "predict",' in served
    assert '{ id: "build", label: "Build a team" }' not in served

    on_disk = Path("frontend/index.html").read_text(encoding="utf-8")
    assert 'gdMode: "build",' in on_disk
    assert '{ id: "build", label: "Build a team" }' in on_disk


def test_app_index_alias_gets_the_same_injection():
    """Both spellings of the page must carry the mobile layer -- the PWA
    manifest points at index.html directly."""
    served = client.get("/app/index.html").text
    assert '<link rel="stylesheet" href="mobile.css">' in served
    assert 'gdMode: "predict",' in served


def test_injection_happens_exactly_once():
    """The replace is anchored to </head>; if the document ever grew a second
    match the page would double-load the mobile layer."""
    served = client.get("/app/").text
    assert served.count('href="mobile.css"') == 1
    assert served.count('src="mobile.js"') == 1


def test_vegas_table_is_rebound_to_live_data_at_serve_time():
    """The committed VEGAS constant becomes the fallback; the overlay's
    F.vegas wins when live lines exist. Disk stays pristine."""
    from pathlib import Path

    served = client.get("/app/").text
    assert "vegas: (F.vegas || VEGAS)," in served

    on_disk = Path("frontend/index.html").read_text(encoding="utf-8")
    assert "F.vegas" not in on_disk


def test_served_page_fixes_the_client_import_path():
    """The design doc imports ./frontend/lib/fbApi.js, which 404s under the
    /app mount -- both the Yahoo link check and the 24h cache purge died on
    it. The served copy must point at ./lib/."""
    served = client.get("/app/").text
    assert 'import("./lib/fbApi.js")' in served
    assert 'import("./frontend/lib/fbApi.js")' not in served


def test_an_explicit_stage_overrides_what_vercel_reports():
    """A second Vercel project on a pre-production branch reports
    "production" for its own deploy, so without an override it serves with
    no BETA badge and looks exactly like the real thing."""
    from app.config import Settings

    assert Settings(vercel_env="production", fb_stage="preview").stage == "preview"
    assert Settings(vercel_env="production").stage == "production"
    assert Settings(vercel_env="preview").stage == "preview"
    assert Settings().stage == "local"


def test_a_beta_branch_deploy_is_a_preview_without_any_dashboard_setting():
    """The override above only helps if someone remembers to set it. The
    branch is not something anyone has to remember: preprod builds from
    `beta`, Vercel hands the function the ref, and that is enough."""
    from app.config import Settings

    beta = Settings(vercel_env="production", vercel_git_commit_ref="beta")
    assert beta.stage == "preview"
    # Case and stray whitespace in the ref must not silently un-badge it.
    assert Settings(vercel_env="production", vercel_git_commit_ref=" Beta ").stage == "preview"
    # Prod builds from main and stays production. This is the assertion that
    # would catch a fallback broad enough to badge the real site.
    assert Settings(vercel_env="production", vercel_git_commit_ref="main").stage == "production"
    # An explicit stage still outranks the branch, in both directions.
    assert Settings(vercel_git_commit_ref="beta", fb_stage="production").stage == "production"
    # No Vercel at all: a local checkout of beta is still local.
    assert Settings(vercel_git_commit_ref="").stage == "local"


# --- endpoint prober -------------------------------------------------------


def test_probe_describes_structure_without_dumping_the_body():
    """The point is the shape: these payloads run to megabytes, and a probe
    that prints all of it is unreadable in a run log."""
    from scripts.probe_endpoint import describe

    payload = {str(i): {"pts": i, "tm": "DET"} for i in range(200)}
    out = describe(payload)

    assert "dict(200 keys)" in out
    assert "keyed like:" in out  # named, not expanded 200 times
    assert out.count("\n") < 40


def test_probe_reports_list_and_scalar_shapes():
    from scripts.probe_endpoint import describe

    assert describe({"games": [{"a": 1}, {"a": 2}]}).count("list(2)") == 1
    assert "..." in describe({"long": "x" * 200})


def test_titans_mode_joins_cowboys_mode():
    """Two team modes, owner's call: Cowboys exactly as shipped, Titans
    beside it. Serve-time edits only -- the file on disk keeps a single
    cowboys mode -- and the skin follows whichever starred mode is active.
    Token blocks ride the injected stylesheet."""
    from pathlib import Path

    served = client.get("/app/").text
    assert '<option value="titans">★ Titans mode</option>' in served
    assert '<option value="cowboys">★ Cowboys mode</option>' in served
    assert 'skin: s.theme === "titans" ? "titans" : "cowboys",' in served
    assert 'th === "titans"' in served  # stored choice survives reload

    on_disk = Path("frontend/index.html").read_text(encoding="utf-8")
    assert "titans" not in on_disk
    assert 'skin: "cowboys",' in on_disk

    css = client.get("/app/mobile.css").text
    assert '[data-skin="titans"]' in css
    assert '[data-skin="titans"][data-theme="titans"]' in css
    assert '[data-skin="titans"][data-theme="dark"]' in css


def test_league_names_are_the_real_ones():
    """The design document still says Sunday Gravy / The Trenches; the
    served page renames every occurrence to the verified league names
    (docs/LEAGUES.md) -- picker values and the injected ADP toggle move
    together because the rename runs after all injections."""
    from pathlib import Path

    served = client.get("/app/").text
    assert "NDDPL" in served and "RED_EYE" in served
    assert "Gravy" not in served and "Trenches" not in served

    on_disk = Path("frontend/index.html").read_text(encoding="utf-8")
    assert "Sunday Gravy" in on_disk  # disk stays pristine
