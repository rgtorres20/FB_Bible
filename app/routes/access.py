"""Who may open the app: /login, invite links, and the owner's access page.

The flow (owner request, Aug 20 -- "a login to app page and let me store
people I want to have access via email"):

  - The owner signs in at /login with their email and the owner code from
    Vercel env. No password is ever stored anywhere.
  - On /app/access the owner stores emails. Adding one mints a one-time
    invite link, shown exactly once on that page -- the server keeps only
    its hash. The owner sends the link however they like; opening it
    signs that email in and burns the invite.
  - Removing an email revokes immediately: the gate re-checks the
    allowlist on every request, so a still-valid cookie stops working the
    moment its email is gone.

Everything here is inert until the owner enables the gate in Vercel env
(docs/ACCESS.md) -- until then /login exists but nothing requires it.
"""

from __future__ import annotations

import html as html_mod
import logging
import time

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from .. import authn, mailer
from ..config import Settings, get_settings
from ..feeds import skin
from ..feeds.store import FeedStore, build_feed_store
from .feeds import get_feed_store

log = logging.getLogger(__name__)

router = APIRouter()

_STYLE = (
    skin.TOKENS_CSS
    + """
body { display: flex; flex-direction: column; align-items: center; }
main { width: min(430px, 94vw); margin-top: 9vh; }
main.wide { width: min(640px, 94vw); margin-top: 5vh; }
h1 { font-weight: 900; font-size: 26px; letter-spacing: -0.02em;
     margin: 0 0 4px; text-transform: uppercase; }
.sub { font-size: 12px; color: var(--color-neutral-600); margin: 0 0 16px; }
.card { border: 2px solid var(--color-text); background: var(--color-bg);
        box-shadow: 3px 3px 0 var(--color-text); padding: 16px;
        margin-bottom: 16px; }
.card h2 { font-weight: 800; font-size: 12px; letter-spacing: 0.14em;
           text-transform: uppercase; color: var(--color-neutral-600);
           margin: 0 0 10px; }
label { display: block; font-size: 11px; font-weight: 800;
        letter-spacing: 0.08em; text-transform: uppercase;
        color: var(--color-neutral-700); margin: 10px 0 4px; }
input { width: 100%; font-family: inherit; font-size: 14px; padding: 8px;
        color: var(--color-text); background: var(--color-bg);
        border: 2px solid var(--color-text); border-radius: 0; }
button { font-family: inherit; font-size: 13px; font-weight: 800;
         padding: 8px 14px; margin-top: 12px; cursor: pointer;
         color: var(--color-bg); background: var(--color-accent);
         border: 2px solid var(--color-text); border-radius: 0;
         box-shadow: 2px 2px 0 var(--color-text); }
button.quietbtn { background: var(--color-bg); color: var(--color-text);
                  font-weight: 600; padding: 3px 8px; margin: 0;
                  font-size: 11px; box-shadow: none; }
.err { border-left: 4px solid var(--color-accent); background:
       var(--color-neutral-200); padding: 8px 10px; font-size: 12.5px;
       margin-bottom: 12px; }
.ok { border-left: 4px solid var(--color-accent);
      background: var(--color-neutral-200); padding: 10px;
      font-size: 12.5px; margin-bottom: 12px; word-break: break-all; }
table { border-collapse: collapse; width: 100%; font-size: 12.5px; }
th { text-align: left; border-bottom: 2px solid var(--color-text);
     padding: 4px 6px; font-size: 10px; letter-spacing: 0.06em;
     text-transform: uppercase; color: var(--color-neutral-700); }
td { padding: 5px 6px; border-bottom: 1px solid var(--color-neutral-300); }
.quiet { color: var(--color-neutral-600); font-style: italic; }
a { color: inherit; }
"""
)


def _page(title: str, body: str, wide: bool = False) -> HTMLResponse:
    main_tag = "<main class='wide'>" if wide else "<main>"
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>FB Bible — {html_mod.escape(title)}</title>"
        f"<style>{_STYLE}</style>{skin.THEME_BOOT}"
        f"{main_tag}{body}</main>"
    )


def session_email(request: Request, settings: Settings) -> str | None:
    return authn.read_session(request.cookies.get(authn.SESSION_COOKIE), settings.session_secret)


def _is_owner(request: Request, settings: Settings) -> bool:
    email = session_email(request, settings)
    return bool(email) and email == authn.normalize_email(settings.owner_email)


async def request_allowed(request: Request, settings: Settings) -> bool:
    """The /app gate's question. The runner/watchdog secret passes (it
    already authenticates the sync push); the owner's session passes on
    the env check alone; anyone else needs a signed session whose email
    is still on the stored allowlist -- checked per request, so removal
    revokes immediately. A store that cannot be built fails closed for
    non-owners: access silently defaulting open would be worse."""
    import hmac as hmac_mod

    header = request.headers.get("x-sync-token", "")
    if settings.sync_token and hmac_mod.compare_digest(header, settings.sync_token):
        return True
    email = session_email(request, settings)
    if not email:
        return False
    if email == authn.normalize_email(settings.owner_email):
        return True
    try:
        store: FeedStore = build_feed_store(settings)
        auth = await store.load_auth()
    except Exception:  # noqa: BLE001 - unreachable store = no allowlist = no entry
        return False
    return authn.is_allowed(auth, email, settings.owner_email)


def _set_session(response: RedirectResponse, email: str, settings: Settings) -> None:
    response.set_cookie(
        authn.SESSION_COOKIE,
        authn.mint_session(email, settings.session_secret),
        max_age=authn.SESSION_DAYS * 86400,
        httponly=True,
        secure=settings.stage != "local",
        samesite="lax",
        path="/",
    )


# --- sign in ---------------------------------------------------------------


@router.get("/login", include_in_schema=False, response_class=HTMLResponse)
async def login_page(request: Request, settings: Settings = Depends(get_settings)) -> HTMLResponse:
    err = ""
    if request.query_params.get("e") == "1":
        # Which part was wrong is deliberately not said.
        err = "<div class='err'>That sign-in didn't match.</div>"
    elif request.query_params.get("e") == "2":
        err = (
            "<div class='err'>That invite link has been used already or has "
            "expired — ask for a fresh one.</div>"
        )
    state_note = (
        ""
        if settings.auth_state == "on"
        else "<p class='sub'>Access control is currently "
        f"<b>{settings.auth_state}</b> — the app is open at /app/ and this "
        "page is a preview. docs/ACCESS.md has the enable steps.</p>"
    )
    return _page(
        "sign in",
        "<h1>Fantasy Bible</h1>"
        "<p class='sub'>Access is by invitation. If you got an invite link, "
        "open it on this device and you're in — no password.</p>"
        + err
        + "<div class='card'><h2>Owner sign-in</h2>"
        "<form method='post' action='/login'>"
        "<label>Email</label><input name='email' type='email' required>"
        "<label>Owner code</label><input name='code' type='password' required>"
        "<button>Sign in</button></form></div>" + state_note,
    )


@router.post("/login", include_in_schema=False)
async def owner_login(
    email: str = Form(""),
    code: str = Form(""),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    import hmac as hmac_mod

    ok = (
        settings.app_owner_code
        and settings.owner_email
        and hmac_mod.compare_digest(code, settings.app_owner_code)
        and authn.normalize_email(email) == authn.normalize_email(settings.owner_email)
    )
    if not ok:
        # Same response either way; nothing about the attempt is logged.
        return RedirectResponse("/login?e=1", status_code=303)
    response = RedirectResponse("/app/", status_code=303)
    _set_session(response, email, settings)
    return response


@router.get("/login/invite/{token}", include_in_schema=False)
async def accept_invite(
    token: str,
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> RedirectResponse:
    auth = await store.load_auth()
    updated, email = authn.accept_invite(auth, token)
    if not email:
        return RedirectResponse("/login?e=2", status_code=303)
    await store.save_auth(updated)
    log.info("access: invite accepted, allowlist now %d", len(updated.get("allow") or {}))
    response = RedirectResponse("/app/", status_code=303)
    _set_session(response, email, settings)
    return response


@router.post("/logout", include_in_schema=False)
async def logout() -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(authn.SESSION_COOKIE, path="/")
    return response


# --- the owner's access page ------------------------------------------------


def _access_page(
    auth: dict,
    settings: Settings,
    minted: tuple[str, str] | None = None,
    mail_note: str = "",
) -> HTMLResponse:
    allow = auth.get("allow") or {}
    invites = auth.get("invites") or {}
    now = time.time()

    minted_html = ""
    if minted:
        email, link = minted
        minted_html = (
            "<div class='ok'><b>Invite minted for "
            f"{html_mod.escape(email)}.</b> "
            + (html_mod.escape(mail_note) + " " if mail_note else "")
            + "The link — shown only this once, works once, expires in "
            f"{authn.INVITE_DAYS} days:<br><br><code>{html_mod.escape(link)}"
            "</code></div>"
        )

    rows = (
        "".join(
            f"<tr><td>{html_mod.escape(addr)}</td>"
            "<td><form method='post' action='/app/access/remove' style='margin:0'>"
            f"<input type='hidden' name='email' value='{html_mod.escape(addr, quote=True)}'>"
            "<button class='quietbtn'>Remove</button></form></td></tr>"
            for addr in sorted(allow)
        )
        or "<tr><td colspan='2' class='quiet'>Nobody yet — just you.</td></tr>"
    )

    pending = "".join(
        f"<tr><td>{html_mod.escape(v.get('email', ''))}</td>"
        f"<td>{max(0, int((v.get('expires', 0) - now) / 86400))}d left</td></tr>"
        for v in invites.values()
        if v.get("expires", 0) > now
    )
    pending_html = (
        "<div class='card'><h2>Unused invites</h2><table>"
        "<tr><th>Email</th><th>Expires</th></tr>" + pending + "</table>"
        "<p class='sub' style='margin:8px 0 0'>Links are shown only at mint "
        "time; re-add an email to mint a fresh one.</p></div>"
        if pending
        else ""
    )

    return _page(
        "access",
        "<h1>Who gets in</h1>"
        "<p class='sub'>People you store here can open the app. Adding an "
        "email mints a one-time invite link for you to send; removing one "
        "locks them out on their next request. Gate is "
        f"<b>{settings.auth_state}</b>.</p>" + minted_html + "<div class='card'>"
        "<h2>Add access</h2><form method='post' action='/app/access/add'>"
        "<label>Email</label><input name='email' type='email' required>"
        "<button>Add &amp; mint invite link</button></form></div>"
        "<div class='card'><h2>Allowed</h2><table>"
        "<tr><th>Email</th><th></th></tr>"
        + rows
        + "</table></div>"
        + pending_html
        + "<form method='post' action='/logout'><button class='quietbtn'>"
        "Sign out</button></form>",
        wide=True,
    )


@router.get("/app/access", include_in_schema=False, response_class=HTMLResponse)
async def access_page(
    request: Request,
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> Response:
    if not _is_owner(request, settings):
        return RedirectResponse("/login", status_code=303)
    return _access_page(await store.load_auth(), settings)


@router.post("/app/access/add", include_in_schema=False)
async def access_add(
    request: Request,
    email: str = Form(...),
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> Response:
    if not _is_owner(request, settings):
        return RedirectResponse("/login", status_code=303)
    email = authn.normalize_email(email)
    auth = await store.load_auth()
    updated, token = authn.mint_invite(auth, email)
    await store.save_auth(updated)
    link = f"{request.base_url}login/invite/{token}"
    # The link itself is never logged (repo rule) -- count only.
    log.info("access: invite minted, %d pending", len(updated.get("invites") or {}))

    # Owner request: adding someone emails them the invite plus the app
    # intro and league links. Best-effort -- any failure falls back to the
    # link on this page, honestly labelled, so delivery trouble never
    # strands an invite.
    mail_note = "Email isn't configured (docs/ACCESS.md), so send it yourself:"
    if settings.email_configured:
        try:
            await run_in_threadpool(
                mailer.send_invite, email, link, str(request.base_url), settings
            )
            mail_note = "Invite emailed to them — the same link, as a backup:"
            log.info("access: invite emailed")
        except Exception as exc:  # noqa: BLE001 - the page reports it; the link still works
            mail_note = f"Emailing failed ({type(exc).__name__}) — send it yourself:"
            log.warning("access: invite email failed: %s", type(exc).__name__)
    return _access_page(updated, settings, minted=(email, link), mail_note=mail_note)


@router.post("/app/access/remove", include_in_schema=False)
async def access_remove(
    request: Request,
    email: str = Form(...),
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> Response:
    if not _is_owner(request, settings):
        return RedirectResponse("/login", status_code=303)
    auth = await store.load_auth()
    updated = authn.remove_email(auth, email)
    await store.save_auth(updated)
    log.info("access: removed one, allowlist now %d", len(updated.get("allow") or {}))
    return _access_page(updated, settings)
