"""My stuff: each signed-in user's personal layer on the shared app.

Owner's shape for it (Aug 20): "we have a base app but they can add to
their app" -- for personal use. The base app (feeds, boards, AI reads)
is identical for everyone; /app/mine is the part that's yours: named
documents -- notes, target lists, custom rankings, pasted or uploaded
CSVs -- stored under your own per-email key and shown to nobody else.
The owner has no browse-other-users view, deliberately: privacy is the
default until the owner asks for one.

Sized to the deployment: documents are text (paste or a small text/CSV
upload), capped per document and per user, stored as one JSON blob per
email in the existing Redis store. Real file/blob storage is a Phase 3
decision (docs/ACCESS.md notes the tiering).
"""

from __future__ import annotations

import html as html_mod
import logging
import time

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import passkeys
from ..config import Settings, get_settings
from ..feeds import skin
from ..feeds.store import FeedStore
from .access import session_email
from .feeds import get_feed_store

log = logging.getLogger(__name__)

router = APIRouter()

MAX_DOCS = 12
MAX_DOC_BYTES = 200_000
MAX_NAME_LEN = 60

_STYLE = (
    skin.TOKENS_CSS
    + """
main { max-width: 780px; margin: 0 auto; }
h1 { font-weight: 900; font-size: 26px; letter-spacing: -0.02em;
     margin: 0 0 4px; text-transform: uppercase; }
.sub { font-size: 12px; color: var(--color-neutral-600); margin: 0 0 16px; }
.card { border: 2px solid var(--color-text); background: var(--color-bg);
        box-shadow: 3px 3px 0 var(--color-text); padding: 14px 16px;
        margin-bottom: 16px; }
.card h2 { font-weight: 800; font-size: 12px; letter-spacing: 0.14em;
           text-transform: uppercase; color: var(--color-neutral-600);
           margin: 0 0 8px; }
.meta { font-size: 11px; color: var(--color-neutral-600); margin: 0 0 8px; }
label { display: block; font-size: 11px; font-weight: 800;
        letter-spacing: 0.08em; text-transform: uppercase;
        color: var(--color-neutral-700); margin: 10px 0 4px; }
input[type=text], textarea { width: 100%; font-family: inherit;
        font-size: 13px; padding: 8px; color: var(--color-text);
        background: var(--color-bg); border: 2px solid var(--color-text);
        border-radius: 0; }
textarea { min-height: 140px; font-family: ui-monospace, monospace;
           font-size: 12px; }
button { font-family: inherit; font-size: 13px; font-weight: 800;
         padding: 6px 12px; margin-top: 10px; cursor: pointer;
         color: var(--color-bg); background: var(--color-accent);
         border: 2px solid var(--color-text); border-radius: 0;
         box-shadow: 2px 2px 0 var(--color-text); }
button.quietbtn { background: var(--color-bg); color: var(--color-text);
                  font-weight: 600; padding: 3px 8px; margin: 0;
                  font-size: 11px; box-shadow: none; }
.err { border-left: 4px solid var(--color-accent);
       background: var(--color-neutral-200); padding: 8px 10px;
       font-size: 12.5px; margin-bottom: 12px; }
pre { background: var(--color-neutral-200); padding: 8px 10px;
      overflow-x: auto; font-size: 11.5px; max-height: 240px; }
details summary { cursor: pointer; font-weight: 700; font-size: 13px;
                  padding: 4px 0; }
.quiet { color: var(--color-neutral-600); font-style: italic; font-size: 12.5px; }
button.pk { width: 100%; font-size: 13.5px; padding: 10px 14px; }
.pkrow { display: flex; justify-content: space-between; align-items: center;
         gap: 10px; border-bottom: 1px solid var(--color-neutral-300);
         padding: 5px 0; font-size: 12.5px; }
.pkmsg { font-size: 12px; margin-top: 8px; }
a { color: inherit; }
"""
)


def _page(body: str) -> HTMLResponse:
    return HTMLResponse(
        "<!doctype html><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Fantasy Sports Bible — my stuff</title>"
        + skin.FAVICON
        + f"<style>{_STYLE}</style>{skin.THEME_BOOT}"
        f"<main>{body}</main>"
        f"<script>{passkeys.BROWSER_JS}</script>"
        "<script>"
        "var pkcard = document.getElementById('pkcard');"
        "if (pkcard && FBPK.supported) {"
        "  pkcard.hidden = false;"
        "  var btn = document.getElementById('pkbtn'), msg = document.getElementById('pkmsg');"
        "  btn.onclick = async function () {"
        "    btn.disabled = true; msg.textContent = 'Waiting for your device…';"
        "    var name = (navigator.platform || 'This device').split(' ')[0];"
        "    try { await FBPK.register(name); location.reload(); }"
        "    catch (e) { msg.textContent = e.message || 'That did not work.';"
        "                btn.disabled = false; }"
        "  };"
        "}"
        "</script>"
    )


def _render(
    email: str, data: dict, err: str = "", pk_list: list[dict] | None = None
) -> HTMLResponse:
    docs = data.get("docs") or {}
    cards = []
    for name in sorted(docs):
        doc = docs[name]
        text = doc.get("text", "")
        stamp = doc.get("updated")
        when = time.strftime("%b %d, %Y", time.localtime(stamp)) if stamp else ""
        safe = html_mod.escape(name, quote=True)
        cards.append(
            "<div class='card'>"
            f"<h2>{html_mod.escape(name)}</h2>"
            f"<p class='meta'>{len(text.encode('utf-8'))} bytes"
            + (f" · saved {when}" if when else "")
            + "</p>"
            f"<details><summary>View</summary><pre>{html_mod.escape(text)}</pre></details>"
            "<details><summary>Edit</summary>"
            "<form method='post' action='/app/mine/save' enctype='multipart/form-data'>"
            f"<input type='hidden' name='name' value='{safe}'>"
            f"<textarea name='text'>{html_mod.escape(text)}</textarea>"
            "<button>Save</button></form></details>"
            "<form method='post' action='/app/mine/delete' style='margin-top:6px'>"
            f"<input type='hidden' name='name' value='{safe}'>"
            "<button class='quietbtn'>Delete</button></form>"
            "</div>"
        )

    add_form = (
        "<div class='card'><h2>Add something</h2>"
        "<form method='post' action='/app/mine/save' enctype='multipart/form-data'>"
        "<label>Name</label>"
        f"<input type='text' name='name' maxlength='{MAX_NAME_LEN}' required "
        "placeholder='My rankings, Draft notes, Sleepers…'>"
        "<label>Paste text / CSV</label><textarea name='text'></textarea>"
        "<label>…or upload a text/CSV file</label>"
        "<input type='file' name='file' accept='.txt,.csv,.md,.json'>"
        "<button>Save</button></form></div>"
        if len(docs) < MAX_DOCS
        else "<p class='quiet'>You're at the "
        f"{MAX_DOCS}-document cap — delete one to add another.</p>"
    )

    return _page(
        "<h1>My stuff</h1>"
        f"<p class='sub'>Signed in as <b>{html_mod.escape(email)}</b> · your "
        "personal layer on the shared app — notes, rankings, lists. Only you "
        "see this page's contents; it follows your sign-in across devices. "
        f"Up to {MAX_DOCS} documents, {MAX_DOC_BYTES // 1000}KB each · "
        "<a href='/app/leagues'>league settings</a> · "
        "<a href='/app/'>back to the app</a></p>"
        + (f"<div class='err'>{html_mod.escape(err)}</div>" if err else "")
        + _passkey_card(pk_list or [])
        + add_form
        + ("".join(cards) or "<p class='quiet'>Nothing saved yet.</p>")
    )


def _passkey_card(pk_list: list[dict]) -> str:
    """Face ID / Touch ID setup for this device. Rendered hidden and
    revealed by script only where the browser supports WebAuthn."""
    rows = "".join(
        "<div class='pkrow'><span>"
        + html_mod.escape(entry.get("label") or "Passkey")
        + (
            " <span class='quiet'>added "
            + time.strftime("%b %d, %Y", time.localtime(entry["added"]))
            + "</span>"
            if entry.get("added")
            else ""
        )
        + "</span>"
        "<form method='post' action='/app/mine/passkey/remove' style='margin:0'>"
        "<input type='hidden' name='cred' value='"
        + html_mod.escape(entry.get("id", ""), quote=True)
        + "'><button class='quietbtn'>Remove</button></form></div>"
        for entry in pk_list
    )
    return (
        "<div class='card' id='pkcard' hidden><h2>Sign in with Face ID</h2>"
        "<p class='meta'>Add this device and next time you can sign in with a "
        "face or a fingerprint instead of a link or a code. The key stays in "
        "your device's secure enclave — this app only ever stores its public "
        "half.</p>"
        + (rows or "<p class='quiet'>No devices set up yet.</p>")
        + "<button class='pk' id='pkbtn' style='margin-top:12px'>"
        "Set up on this device</button>"
        "<div class='pkmsg quiet' id='pkmsg'></div></div>"
    )


def _signin_needed() -> HTMLResponse:
    return _page(
        "<h1>My stuff</h1>"
        "<p class='sub'>This page is your personal layer on the app, so it "
        "needs to know who you are. <a href='/login'>Sign in</a> — with your "
        "invite link, or the owner code if you're the owner.</p>"
    )


@router.get("/app/mine", include_in_schema=False, response_class=HTMLResponse)
async def mine_page(
    request: Request,
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> Response:
    email = session_email(request, settings)
    if not email:
        return _signin_needed()
    auth = await store.load_auth()
    return _render(email, await store.load_user(email), pk_list=passkeys.list_for(auth, email))


@router.post("/app/mine/save", include_in_schema=False)
async def mine_save(
    request: Request,
    name: str = Form(...),
    text: str = Form(""),
    file: UploadFile | None = File(None),
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> Response:
    email = session_email(request, settings)
    if not email:
        return _signin_needed()

    name = name.strip()[:MAX_NAME_LEN]
    data = await store.load_user(email)
    docs = dict(data.get("docs") or {})

    body = text
    if file is not None and file.filename:
        raw = await file.read()
        try:
            body = raw.decode("utf-8")
        except UnicodeDecodeError:
            return _render(
                email, data, "That file isn't text — this page stores text and CSV only."
            )

    if not name:
        return _render(email, data, "A document needs a name.")
    if len(body.encode("utf-8")) > MAX_DOC_BYTES:
        return _render(email, data, f"Too big — the cap is {MAX_DOC_BYTES // 1000}KB per document.")
    if name not in docs and len(docs) >= MAX_DOCS:
        return _render(email, data, f"You're at the {MAX_DOCS}-document cap.")

    docs[name] = {"text": body, "updated": int(time.time())}
    await store.save_user(email, {**data, "docs": docs})
    # Count only -- never the contents, never the email (repo token rule
    # spirit: personal data stays out of logs).
    log.info("mine: saved a doc, user now holds %d", len(docs))
    return RedirectResponse("/app/mine", status_code=303)


@router.post("/app/mine/delete", include_in_schema=False)
async def mine_delete(
    request: Request,
    name: str = Form(...),
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> Response:
    email = session_email(request, settings)
    if not email:
        return _signin_needed()
    data = await store.load_user(email)
    docs = {k: v for k, v in (data.get("docs") or {}).items() if k != name}
    await store.save_user(email, {**data, "docs": docs})
    return RedirectResponse("/app/mine", status_code=303)
