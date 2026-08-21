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
from datetime import date

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import passkeys
from ..config import Settings, get_settings
from ..feeds import ranklists, skin, teams
from ..feeds.store import FeedStore
from .access import session_email
from .feeds import get_feed_store

log = logging.getLogger(__name__)

router = APIRouter()

MAX_DOCS = 12
MAX_DOC_BYTES = 200_000
MAX_NAME_LEN = 60
# Ranking lists are separate from documents on purpose: a document is free
# text the owner reads, a list is structured input the draft board blends
# (docs/WEIGHTS.md). Same upload, different contract.
MAX_LISTS = 8

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
.swatches { display: flex; flex-wrap: wrap; gap: 4px; margin: 0 0 10px; }
.sw { width: 16px; height: 16px; border: 2px solid; display: inline-block; }
select { width: 100%; font-family: inherit; font-size: 13px; padding: 7px;
         color: var(--color-text); background: var(--color-bg);
         border: 2px solid var(--color-text); border-radius: 0; }
a { color: inherit; }
"""
)


def _page(body: str, club: str = "") -> HTMLResponse:
    return HTMLResponse(
        skin.head("my stuff", "My stuff", _STYLE, skin.theme_boot(club)) + f"<main>{body}</main>"
        f"<script>{passkeys.BROWSER_JS}</script>"
        "<script>"
        # A save cannot reach localStorage from the server, so the
        # redirect carries the club and the page writes it on arrival.
        # Without this the colours would not change until the next visit.
        "var q = new URLSearchParams(location.search).get('team');"
        "if (q) {"
        "  try { localStorage.setItem('fb_team', q);"
        "        localStorage.setItem('ww_theme', 'team'); } catch (e) {}"
        "  document.documentElement.dataset.theme = 'team';"
        "  document.documentElement.dataset.team = q;"
        "  var tm = document.getElementById('teammsg');"
        "  if (tm) { tm.textContent = 'Saved — the app is wearing it now.'; }"
        "  history.replaceState({}, '', '/app/mine');"
        "}"
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
        + _team_card(data.get("team") or teams.HOUSE)
        + _passkey_card(pk_list or [])
        + _list_card(data.get("ranklists") or {}, date.today())
        + add_form
        + ("".join(cards) or "<p class='quiet'>Nothing saved yet.</p>"),
        club=data.get("team") or "",
    )


def _list_card(saved: dict, today: date) -> str:
    """Ranking lists: the one weighted input in the app.

    Each row shows what the owner needs to judge it -- how many players it
    carries, when it was true, and how old that makes it. Owner, Aug 21:
    "these can get outdated once season starts", so the age is stated
    rather than left for someone to work out from a date.
    """
    rows = []
    for key in sorted(saved):
        entry = saved[key]
        order = entry.get("order") or []
        active = entry.get("active", True)
        as_of = entry.get("as_of") or ""
        age = ""
        if as_of:
            try:
                days = (today - date.fromisoformat(as_of)).days
                age = "today" if days <= 0 else f"{days} day{'s' if days != 1 else ''} old"
            except ValueError:
                age = ""
        safe = html_mod.escape(key, quote=True)
        rows.append(
            "<div class='card'>"
            f"<h2>{html_mod.escape(entry.get('name') or key)}</h2>"
            f"<p class='meta'>{len(order)} players"
            + (f" · as of {html_mod.escape(as_of)}" if as_of else "")
            + (f" · {age}" if age else "")
            + "</p>"
            "<form method='post' action='/app/mine/list/toggle' class='row'>"
            f"<input type='hidden' name='key' value='{safe}'>"
            f"<span class='meta'>{'In the blend' if active else 'Not in the blend'}</span>"
            f"<button>{'Turn off' if active else 'Turn on'}</button></form>"
            "<p class='quiet'>Every list that is on counts the same. There are "
            "no weights — turning one off is how you change the blend.</p>"
            "<details><summary>View order</summary><pre>"
            + html_mod.escape("\n".join(f"{i + 1}. {n}" for i, n in enumerate(order[:60])))
            + ("\n…" if len(order) > 60 else "")
            + "</pre></details>"
            "<form method='post' action='/app/mine/list/delete' style='margin-top:6px'>"
            f"<input type='hidden' name='key' value='{safe}'>"
            "<button class='quietbtn'>Remove this list</button></form>"
            "</div>"
        )

    add = (
        "<div class='card'><h2>Add a ranking list</h2>"
        "<p class='meta'>A top-N in order — one player per line, or pasted "
        "from a CSV. The draft board blends every list you keep here.</p>"
        "<form method='post' action='/app/mine/list' enctype='multipart/form-data'>"
        "<label>Name</label>"
        f"<input type='text' name='name' maxlength='{MAX_NAME_LEN}' required "
        "placeholder='ESPN top 300, Yahoo consensus, My tiers…'>"
        "<label>As of</label><input type='date' name='as_of'>"
        "<label>Paste the list</label><textarea name='text'></textarea>"
        "<label>…or upload it</label>"
        "<input type='file' name='file' accept='.txt,.csv,.md,.json'>"
        "<button>Save list</button></form></div>"
        if len(saved) < MAX_LISTS
        else f"<p class='quiet'>You're at the {MAX_LISTS}-list cap — remove one to add another.</p>"
    )
    return (
        "<h2 class='section'>Ranking lists</h2>"
        + add
        + ("".join(rows) or "<p class='quiet'>No ranking lists yet.</p>")
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


def _team_card(current: str) -> str:
    """Pick a club and the whole app wears it (owner request, Aug 21).

    Saved against the sign-in rather than only in this browser, so the
    choice follows the user to their phone — the theme still renders from
    localStorage, so there is no flash, but a device that has never seen
    the app fills in from here.
    """
    options = "".join(
        f"<option value='{html_mod.escape(code, quote=True)}'"
        + (" selected" if code == current else "")
        + f">{html_mod.escape(teams.name(code))}</option>"
        for code in teams.all_codes()
    )
    swatches = "".join(
        f"<span class='sw' title='{html_mod.escape(teams.name(code))}' "
        f"style='background:{teams.colours(code)[0]};"
        f"border-color:{teams.colours(code)[1]}'></span>"
        for code in teams.all_codes()
    )
    return (
        "<div class='card'><h2>Your team</h2>"
        "<p class='meta'>Pick a club and the app wears its colours — the "
        "boards, the mock room, all of it. The mode switch on the app page "
        "then reads <b>My team / Dark / Light</b>. Until you pick one, "
        "“My team” is the app's own navy.</p>"
        f"<div class='swatches'>{swatches}</div>"
        "<form method='post' action='/app/mine/team'>"
        f"<label for='team'>Club</label><select id='team' name='team'>{options}</select>"
        "<button>Save team</button></form>"
        "<div class='pkmsg quiet' id='teammsg'></div></div>"
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


@router.post("/app/mine/team", include_in_schema=False)
async def mine_team(
    request: Request,
    team: str = Form(...),
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> Response:
    """Save the club whose colours this user's app wears.

    Stored against the email so it follows them across devices; the
    browser also keeps it in localStorage, which is what actually paints
    the page before first render.
    """
    email = session_email(request, settings)
    if not email:
        return _signin_needed()
    if team not in {*teams.CLUBS, teams.HOUSE}:
        data = await store.load_user(email)
        return _render(email, data, "That isn't one of the 32 clubs.")
    data = await store.load_user(email)
    await store.save_user(email, {**data, "team": team})
    # The redirect carries the choice so the page can write localStorage
    # on arrival -- the server cannot reach it, and without this the
    # theme would not change until the next visit.
    return RedirectResponse(f"/app/mine?team={team}", status_code=303)


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


# --- ranking lists ---------------------------------------------------------
# The one weighted input in the app (docs/WEIGHTS.md). Three routes, one per
# intent: add a list, tilt how hard it pulls, or take it out. Removal is the
# only exclusion -- a weight can never silence a list, which is why there is
# no "disable" here.


def _list_key(name: str) -> str:
    return " ".join(name.strip().split()).lower()[:MAX_NAME_LEN]


@router.post("/app/mine/list", include_in_schema=False)
async def mine_list_save(
    request: Request,
    name: str = Form(...),
    as_of: str = Form(""),
    text: str = Form(""),
    file: UploadFile | None = File(None),
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> Response:
    email = session_email(request, settings)
    if not email:
        return _signin_needed()

    data = await store.load_user(email)
    saved = dict(data.get("ranklists") or {})

    body = text
    if file is not None and file.filename:
        raw = await file.read()
        try:
            body = raw.decode("utf-8")
        except UnicodeDecodeError:
            return _render(email, data, "That file isn't text — paste it or upload text/CSV.")

    name = name.strip()[:MAX_NAME_LEN]
    if not name:
        return _render(email, data, "A ranking list needs a name.")
    if len(body.encode("utf-8")) > MAX_DOC_BYTES:
        return _render(email, data, f"Too big — the cap is {MAX_DOC_BYTES // 1000}KB.")

    order = ranklists.parse(body)
    if not order:
        # The whole point of parse() returning empty rather than guessing:
        # a list stored with no players looks like a working one and would
        # silently contribute nothing to the blend.
        return _render(
            email,
            data,
            "No players found in that. One name per line, or a CSV with the "
            "name in the first column.",
        )

    key = _list_key(name)
    if key not in saved and len(saved) >= MAX_LISTS:
        return _render(email, data, f"You're at the {MAX_LISTS}-list cap.")

    # An as-of the owner did not give is today, not blank: a list with no
    # date cannot be judged for staleness, and every list here will be.
    try:
        stamp = date.fromisoformat(as_of).isoformat() if as_of else date.today().isoformat()
    except ValueError:
        stamp = date.today().isoformat()

    saved[key] = {
        "name": name,
        "as_of": stamp,
        "active": bool(saved.get(key, {}).get("active", True)),
        "order": order,
        "updated": int(time.time()),
    }
    await store.save_user(email, {**data, "ranklists": saved})
    # Counts only -- never the contents, never the email.
    log.info("mine: saved a ranking list of %d players, user now holds %d", len(order), len(saved))
    return RedirectResponse("/app/mine", status_code=303)


@router.post("/app/mine/list/toggle", include_in_schema=False)
async def mine_list_toggle(
    request: Request,
    key: str = Form(...),
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> Response:
    """In the blend, or not. The only control a list has.

    Owner, Aug 21: "weight them all the same and only blend data when they
    are activated." There is no weight to store, so there is nothing here
    that can be set to a value that quietly means nothing.
    """
    email = session_email(request, settings)
    if not email:
        return _signin_needed()
    data = await store.load_user(email)
    saved = dict(data.get("ranklists") or {})
    entry = saved.get(key)
    if not entry:
        return RedirectResponse("/app/mine", status_code=303)
    saved[key] = {**entry, "active": not entry.get("active", True)}
    await store.save_user(email, {**data, "ranklists": saved})
    return RedirectResponse("/app/mine", status_code=303)


@router.post("/app/mine/list/delete", include_in_schema=False)
async def mine_list_delete(
    request: Request,
    key: str = Form(...),
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> Response:
    email = session_email(request, settings)
    if not email:
        return _signin_needed()
    data = await store.load_user(email)
    saved = dict(data.get("ranklists") or {})
    saved.pop(key, None)
    await store.save_user(email, {**data, "ranklists": saved})
    log.info("mine: removed a ranking list, user now holds %d", len(saved))
    return RedirectResponse("/app/mine", status_code=303)
