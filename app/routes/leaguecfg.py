"""League settings: let a user describe their own league.

Owner request (Aug 21): "we should also add the ability to adjust league
setting for users." The two built-in leagues are the owner's, verified
from their own Yahoo settings pages -- useless to anyone else. Everything
this app claims about a player depends on scoring: an IDP board is a
different board at 4 points a sack than at 2, and telling someone to
reach for a quarterback is only true if their league actually pays for
one. So a user gets the same `League` the built-ins are, with their own
numbers in it.

Full custom scoring rather than presets, deliberately. A preset list is a
promise that everyone's league is one of N shapes, and the moment it
isn't, the app is confidently wrong about their draft -- which is the one
failure this repo will not ship (see the no-false-positives rule).

Stored per-email in the same Redis blob as /app/mine, so a league follows
the sign-in across devices and nobody else can see it. The built-ins stay
read-only: they are the *owner's* verified settings, and a copy button is
the honest way to start from them.
"""

from __future__ import annotations

import html as html_mod
import logging
import re
from dataclasses import replace

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import leagues as leagues_mod
from ..config import Settings, get_settings
from ..feeds import skin
from ..feeds.store import FeedStore
from .access import session_email
from .feeds import get_feed_store

log = logging.getLogger(__name__)

router = APIRouter()

MAX_LEAGUES = 6
MAX_NAME_LEN = 40
USER_KEY_PREFIX = "u_"

_OFFENSE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("ppr", "Per reception", "1 = full PPR, 0.5 = half, 0 = none"),
    ("pass_td", "Passing TD", "market is 4"),
    ("pass_yds_per_pt", "Pass yards per point", "market is 25 — lower pays more"),
    ("pass_completion", "Per completion", "market is 0"),
    ("rec_yds_per_pt", "Receiving yards per point", "market is 10 — higher pays less"),
    ("rush_yds_per_pt", "Rush yards per point", "market is 10"),
)

_SLOT_HELP = {
    "FLX": "any WR/RB/TE",
    "DEF": "whole team D/ST",
    "D": "any single defender",
    "BN": "bench",
}


# --- storage ---------------------------------------------------------------


# The store shape lives with the League itself (app/leagues.py) so that
# every surface can read a user's leagues without importing this router.
user_leagues = leagues_mod.user_leagues
all_leagues = leagues_mod.for_user


def _slug(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "league"
    key = f"{USER_KEY_PREFIX}{base}"[:40]
    n = 2
    while key in taken:
        key = f"{USER_KEY_PREFIX}{base}_{n}"[:40]
        n += 1
    return key


# --- form -> League --------------------------------------------------------


def _num(form, field: str, fallback: float) -> float:
    raw = (form.get(field) or "").strip()
    if raw == "":
        return fallback
    try:
        return float(raw)
    except ValueError:
        return fallback


def league_from_form(form, key: str) -> tuple[leagues_mod.League | None, str]:
    """Build a League from the editor's fields, or say what's wrong.

    Validation refuses rather than repairs. Silently clamping someone's
    league to something it isn't would make every downstream number a
    quiet lie about their draft.
    """
    name = (form.get("name") or "").strip()[:MAX_NAME_LEN]
    if not name:
        return None, "Your league needs a name."

    try:
        teams = int(float((form.get("teams") or "").strip() or 0))
    except ValueError:
        return None, "Teams has to be a number."
    if not leagues_mod.MIN_TEAMS <= teams <= leagues_mod.MAX_TEAMS:
        return None, (
            f"Teams has to be between {leagues_mod.MIN_TEAMS} and "
            f"{leagues_mod.MAX_TEAMS} — the mock room seats every team from "
            "one live player pool, and past that it would draft air."
        )

    counts = {s: form.get(f"slot_{s}") for s in leagues_mod.SLOT_ORDER}
    slots = leagues_mod.slots_from_counts(counts)
    starters = [s for s in slots if s != "BN"]
    if not starters:
        return None, "A league needs at least one starting slot."
    if len(slots) > leagues_mod.MAX_ROUNDS:
        return None, f"That's {len(slots)} roster spots — the cap is {leagues_mod.MAX_ROUNDS}."

    idp = {}
    for field_name, _label in leagues_mod.IDP_FIELDS:
        value = _num(form, f"idp_{field_name}", 0.0)
        if value:
            idp[field_name] = value

    starts_defenders = any(s in {"DB", "LB", "DL", "D"} for s in slots)
    # Owner's rule, Aug 21: a league picks one kind of defense. A roster
    # with both would need two rankings for one lineup decision, and the
    # boards would show a defender and a whole defense competing for
    # slots that are not actually interchangeable.
    if "DEF" in slots and starts_defenders:
        return None, (
            "Pick one kind of defense: a team D/ST slot (DEF), or "
            "individual defenders (DL/LB/DB/D) — not both. Set the ones "
            "you don't use to zero."
        )
    if starts_defenders and not idp:
        return None, (
            "You start defenders but score them nothing — fill in the IDP "
            "values, or the defensive board would rank everyone at zero."
        )

    # Team defense / special teams. Three separate dicts because they are
    # three different kinds of number: per event, per game inside a
    # points-allowed band, per game inside a yards-allowed band.
    dst = {}
    for stat_field, _label in leagues_mod.DST_FIELDS:
        value = _num(form, f"dst_{stat_field}", 0.0)
        if value:
            dst[stat_field] = value
    dst_pa = {}
    for stat_field, _label in leagues_mod.DST_PA_TIERS:
        value = _num(form, f"dst_{stat_field}", 0.0)
        if value:
            dst_pa[stat_field] = value
    dst_ya = {}
    for stat_field, _label in leagues_mod.DST_YA_TIERS:
        value = _num(form, f"dst_{stat_field}", 0.0)
        if value:
            dst_ya[stat_field] = value

    if "DEF" in slots and not (dst or dst_pa or dst_ya):
        return None, (
            "You start a team defense but score it nothing — fill in the "
            "D/ST values, or all 32 defenses would rank identically at zero."
        )

    league = leagues_mod.League(
        key=key,
        name=name,
        teams=teams,
        slots=slots,
        ppr=_num(form, "ppr", 1.0),
        pass_td=_num(form, "pass_td", leagues_mod.MARKET_PASS_TD),
        pass_yds_per_pt=_num(form, "pass_yds_per_pt", leagues_mod.MARKET_PASS_YDS_PER_PT),
        pass_completion=_num(form, "pass_completion", leagues_mod.MARKET_PASS_COMPLETION),
        rec_yds_per_pt=_num(form, "rec_yds_per_pt", leagues_mod.MARKET_REC_YDS_PER_PT),
        rush_yds_per_pt=_num(form, "rush_yds_per_pt", 10.0),
        idp=idp,
        idp_ret_yds_per_pt=_num(form, "idp_ret_yds_per_pt", 0.0),
        dst=dst,
        dst_pa=dst_pa,
        dst_ya=dst_ya,
        dst_ret_yds_per_pt=_num(form, "dst_ret_yds_per_pt", 0.0),
        # Never inherited: a user league's QB adjustment is derived from
        # the scoring they just typed. The built-ins' tuned values came
        # from how those specific rooms draft and mean nothing here.
        qb_boost_override=None,
    )
    if league.pass_yds_per_pt <= 0 or league.rec_yds_per_pt <= 0:
        return None, "Yards-per-point has to be above zero — it's a divisor."
    return league, ""


# --- page ------------------------------------------------------------------

_STYLE = (
    skin.TOKENS_CSS
    + """
main { max-width: 880px; margin: 0 auto; }
h1 { font-weight: 900; font-size: 26px; letter-spacing: -0.02em;
     margin: 0 0 4px; text-transform: uppercase; }
.sub { font-size: 12px; color: var(--color-neutral-600); margin: 0 0 16px; }
.card { border: 2px solid var(--color-text); background: var(--color-bg);
        box-shadow: 3px 3px 0 var(--color-text); padding: 14px 16px;
        margin-bottom: 16px; }
.card h2 { font-weight: 800; font-size: 12px; letter-spacing: 0.14em;
           text-transform: uppercase; color: var(--color-neutral-600);
           margin: 0 0 8px; }
.read { font-size: 12px; color: var(--color-neutral-700); margin: 0 0 8px;
        line-height: 1.5; }
.read b { color: var(--color-text); }
label { display: block; font-size: 10.5px; font-weight: 800;
        letter-spacing: 0.06em; text-transform: uppercase;
        color: var(--color-neutral-700); margin: 0 0 3px; }
label span { display: block; font-weight: 500; text-transform: none;
             letter-spacing: 0; color: var(--color-neutral-600);
             font-size: 10.5px; }
input[type=text], input[type=number] { width: 100%; font-family: inherit;
        font-size: 13px; padding: 6px; color: var(--color-text);
        background: var(--color-bg); border: 2px solid var(--color-text);
        border-radius: 0; box-sizing: border-box; }
.grid { display: grid; gap: 10px 12px;
        grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
.grid.tight { grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); }
fieldset { border: none; padding: 0; margin: 0 0 14px; }
legend { font-size: 11px; font-weight: 800; letter-spacing: 0.12em;
         text-transform: uppercase; color: var(--color-neutral-600);
         padding: 0; margin-bottom: 8px; }
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
.quiet { color: var(--color-neutral-600); font-style: italic; font-size: 12.5px; }
.tag { display: inline-block; font-size: 9.5px; font-weight: 800;
       letter-spacing: 0.1em; text-transform: uppercase; padding: 1px 5px;
       border: 1px solid var(--color-text); margin-left: 6px;
       vertical-align: 2px; }
details summary { cursor: pointer; font-weight: 700; font-size: 13px;
                  padding: 4px 0; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
a { color: inherit; }
"""
)


def _page(body: str) -> HTMLResponse:
    return HTMLResponse(
        skin.head("league settings", "League settings", _STYLE) + f"<main>{body}</main>"
    )


def _esc(value) -> str:
    return html_mod.escape(str(value), quote=True)


def _num_field(name: str, label: str, hint: str, value, step: str = "any") -> str:
    return (
        f"<div><label for='{name}'>{html_mod.escape(label)}"
        f"<span>{html_mod.escape(hint)}</span></label>"
        f"<input type='number' step='{step}' id='{name}' name='{name}' "
        f"value='{_esc(value)}'></div>"
    )


def derived_read(lg: leagues_mod.League) -> str:
    """What the app concludes from these settings, said out loud.

    The point of the editor is that these numbers change the advice; a
    user should be able to see that happen rather than take it on faith.
    """
    groups = ", ".join(sorted(lg.idp_groups)) or "none"
    if lg.starts_dst:
        seats = sum(1 for s in lg.slots if s == "DEF")
        shutout = lg.dst_pa.get("pts_allow_0")
        defense = (
            f"· <b>{seats}</b> team D/ST slot"
            + ("s" if seats > 1 else "")
            + (f", {shutout:g} for a shutout" if shutout else "")
        )
    else:
        defense = ""
    premium = lg.qb_premium_per_game
    if premium > 0:
        qb = (
            f"<b>+{premium:g} pts/game</b> above market for a starting QB — "
            f"the mock room moves quarterbacks up about <b>{lg.qb_draft_boost:g}</b> "
            "draft slots"
        )
        # The two numbers disagreeing is the interesting case, not an
        # error: a bonus every starting QB earns lifts the whole position
        # and separates nobody, so it is real points that change no draft
        # order. Saying so beats letting a big premium next to a small
        # boost read as a bug.
        spread = lg.qb_spread_premium_per_game
        if spread < premium:
            qb += (
                f" — but only <b>{spread:g}</b> of those points separate the best QB "
                "from a replacement. A bonus every starter earns (a point per "
                "completion, say) lifts them all and moves none of them up your board"
            )
        if lg.qb_boost_override is not None:
            qb += " (tuned against how this room actually drafts)"
        elif lg.qb_draft_boost >= leagues_mod.MAX_DERIVED_QB_BOOST:
            qb += " — capped at two rounds, since the estimate gets crude at the extremes"
    elif premium < 0:
        qb = f"<b>{premium:g} pts/game</b> <i>below</i> market — QBs are worth less here"
    else:
        qb = "QBs score at market, so nothing moves them off ADP"
    return (
        "<p class='read'>"
        f"<b>{lg.teams}</b> teams · <b>{lg.rounds}</b> rounds · drafts against "
        f"FantasyFootballCalculator's <b>{lg.adp_size_key[1:]}-team</b> board · "
        f"individual defenders startable: <b>{groups}</b> {defense}<br>"
        f"{qb}<br>"
        + (
            "Receiving yardage is <b>discounted</b> here, so receptions carry more "
            "of the value — target volume over air yards."
            if lg.receiving_is_halved
            else "Receiving yardage scores at or above market."
        )
        + "</p>"
    )


def _lineup(lg: leagues_mod.League | None) -> str:
    counts = leagues_mod.counts_from_slots(lg.slots) if lg else {}
    cells = []
    for slot in leagues_mod.SLOT_ORDER:
        hint = _SLOT_HELP.get(slot, "")
        cells.append(
            f"<div><label for='slot_{slot}'>{slot}<span>{hint or '&nbsp;'}</span></label>"
            f"<input type='number' min='0' max='20' step='1' id='slot_{slot}' "
            f"name='slot_{slot}' value='{counts.get(slot, 0)}'></div>"
        )
    return "<div class='grid tight'>" + "".join(cells) + "</div>"


def _form(lg: leagues_mod.League | None, key: str = "") -> str:
    # A new league's D/ST boxes start at Yahoo's own defaults rather than
    # at zero. Fifteen numbers typed from memory is how a league gets
    # entered wrong; the defaults are what most people would type anyway,
    # and every one of them is still editable. An existing league shows
    # exactly what it was saved with, defaults or not.
    base = lg or replace(
        leagues_mod.blank(),
        dst=dict(leagues_mod.DEFAULT_DST),
        dst_pa=dict(leagues_mod.DEFAULT_DST_PA),
    )
    offense = "".join(
        _num_field(field, label, hint, getattr(base, field))
        for field, label, hint in _OFFENSE_FIELDS
    )
    idp = "".join(
        _num_field(f"idp_{field}", label, "", base.idp.get(field, 0))
        for field, label in leagues_mod.IDP_FIELDS
    )
    idp += _num_field(
        "idp_ret_yds_per_pt",
        "Return yards per point",
        "INT and fumble returns · 0 = not scored",
        base.idp_ret_yds_per_pt,
    )
    dst_events = "".join(
        _num_field(f"dst_{f}", label, "", base.dst.get(f, 0)) for f, label in leagues_mod.DST_FIELDS
    )
    dst_events += _num_field(
        "dst_ret_yds_per_pt",
        "Return yards per point",
        "INT and fumble returns · 0 = not scored",
        base.dst_ret_yds_per_pt,
    )
    dst_pa = "".join(
        _num_field(f"dst_{f}", label, "", base.dst_pa.get(f, 0))
        for f, label in leagues_mod.DST_PA_TIERS
    )
    # Folded away: the data is there and some leagues really do score it,
    # but almost none do, and nine always-zero boxes would bury the
    # points-allowed ladder that nearly every league does use.
    dst_ya = "".join(
        _num_field(f"dst_{f}", label, "", base.dst_ya.get(f, 0))
        for f, label in leagues_mod.DST_YA_TIERS
    )

    return (
        "<form method='post' action='/app/leagues/save'>"
        f"<input type='hidden' name='key' value='{_esc(key)}'>"
        "<div class='grid'>"
        "<div><label for='name'>League name</label>"
        f"<input type='text' id='name' name='name' maxlength='{MAX_NAME_LEN}' "
        f"value='{_esc(base.name if lg else '')}' required "
        "placeholder='My work league'></div>"
        f"<div><label for='teams'>Teams<span>{leagues_mod.MIN_TEAMS}"
        f"–{leagues_mod.MAX_TEAMS}</span></label>"
        f"<input type='number' min='{leagues_mod.MIN_TEAMS}' "
        f"max='{leagues_mod.MAX_TEAMS}' step='1' id='teams' name='teams' "
        f"value='{base.teams}'></div>"
        "</div>"
        "<fieldset><legend>Starting lineup &amp; bench</legend>"
        "<p class='read'><b>DEF</b> is a whole team defense; <b>DL/LB/DB/D</b> "
        "are individual defenders (IDP). A league uses one or the other — "
        "fill in whichever your league starts and leave the rest at zero.</p>"
        + _lineup(lg)
        + "</fieldset>"
        "<fieldset><legend>Offense scoring</legend>"
        f"<div class='grid'>{offense}</div></fieldset>"
        "<fieldset><legend>Defensive players (IDP)</legend>"
        "<p class='read'>Leave these at zero if your league doesn't start "
        "individual defenders. Points per event, as your settings page "
        "states them.</p>"
        f"<div class='grid'>{idp}</div></fieldset>"
        "<fieldset><legend>Team defense (D/ST)</legend>"
        "<p class='read'>For a <b>DEF</b> slot — a whole team's defense and "
        "special teams, scored as one. Use these <i>instead of</i> the IDP "
        "values above, not alongside them. Prefilled with Yahoo's defaults; "
        "leave them at zero if your league starts individual defenders.</p>"
        f"<div class='grid'>{dst_events}</div>"
        "<p class='read' style='margin-top:10px'><b>Points allowed</b>, per "
        "game finished inside the band.</p>"
        f"<div class='grid'>{dst_pa}</div>"
        "<details style='margin-top:8px'><summary>Yards allowed "
        "(most leagues leave these at zero)</summary>"
        f"<div class='grid'>{dst_ya}</div></details>"
        "</fieldset>"
        "<button>Save league</button></form>"
    )


def render(email: str, data: dict, err: str = "", editing: str = "") -> HTMLResponse:
    mine = user_leagues(data)
    cards = []

    for lg in leagues_mod.defaults():
        cards.append(
            "<div class='card'>"
            f"<h2>{html_mod.escape(lg.name)}<span class='tag'>owner's, verified</span></h2>"
            + derived_read(lg)
            + "<form method='post' action='/app/leagues/copy' class='row'>"
            f"<input type='hidden' name='from' value='{_esc(lg.key)}'>"
            "<button class='quietbtn'>Copy into my leagues</button></form>"
            "<p class='quiet' style='margin:8px 0 0'>Read-only — these are the "
            "owner's own Yahoo settings. Copy one to start from it.</p></div>"
        )

    for lg in mine:
        open_now = " open" if editing == lg.key else ""
        cards.append(
            "<div class='card'>"
            f"<h2>{html_mod.escape(lg.name)}<span class='tag'>yours</span></h2>"
            + derived_read(lg)
            + f"<details{open_now}><summary>Edit settings</summary>"
            + _form(lg, lg.key)
            + "</details>"
            "<form method='post' action='/app/leagues/delete' style='margin-top:6px'>"
            f"<input type='hidden' name='key' value='{_esc(lg.key)}'>"
            "<button class='quietbtn'>Delete</button></form></div>"
        )

    if len(mine) < MAX_LEAGUES:
        cards.append(
            "<div class='card'><h2>Add a league</h2>"
            "<p class='read'>Enter it exactly as your league's settings page "
            "reads. Every board in the app scores with these numbers — that's "
            "the point of typing them.</p>" + _form(None) + "</div>"
        )
    else:
        cards.append(
            f"<p class='quiet'>You're at the {MAX_LEAGUES}-league cap — "
            "delete one to add another.</p>"
        )

    return _page(
        "<h1>League settings</h1>"
        f"<p class='sub'>Signed in as <b>{html_mod.escape(email)}</b> · your "
        "leagues, your scoring. The draft board, the IDP rankings and the mock "
        "draft room all score with whatever you enter here — a league that pays "
        "2 a sack ranks defenders differently from one that pays 4, and this is "
        "where the app finds out which one you're in. Only you see these · "
        "<a href='/app/mock'>mock draft room</a> · "
        "<a href='/app/'>back to the app</a></p>"
        + (f"<div class='err'>{html_mod.escape(err)}</div>" if err else "")
        + "".join(cards)
    )


def _signin_needed() -> HTMLResponse:
    return _page(
        "<h1>League settings</h1>"
        "<p class='sub'>Your leagues are stored against your sign-in, so this "
        "page needs to know who you are. <a href='/login'>Sign in</a> — with "
        "your invite link, or the owner code if you're the owner.</p>"
    )


# --- routes ----------------------------------------------------------------


@router.get("/app/leagues", include_in_schema=False, response_class=HTMLResponse)
async def leagues_page(
    request: Request,
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> Response:
    email = session_email(request, settings)
    if not email:
        return _signin_needed()
    return render(email, await store.load_user(email))


@router.post("/app/leagues/save", include_in_schema=False)
async def leagues_save(
    request: Request,
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> Response:
    email = session_email(request, settings)
    if not email:
        return _signin_needed()

    form = await request.form()
    data = await store.load_user(email)
    stored = list(data.get("leagues") or [])
    key = (form.get("key") or "").strip()
    existing = {raw.get("key") for raw in stored}

    if key and key not in existing:
        return render(email, data, "That league is no longer here — it may have been deleted.")
    if not key:
        if len(stored) >= MAX_LEAGUES:
            return render(email, data, f"You're at the {MAX_LEAGUES}-league cap.")
        key = _slug(form.get("name") or "", existing)

    league, problem = league_from_form(form, key)
    if league is None:
        return render(email, data, problem, editing=key)

    blob = league.to_dict()
    stored = [blob if raw.get("key") == key else raw for raw in stored]
    if not any(raw.get("key") == key for raw in stored):
        stored.append(blob)
    await store.save_user(email, {**data, "leagues": stored})
    # Count only -- never the settings, never the email.
    log.info("league settings: saved, user now holds %d", len(stored))
    return RedirectResponse("/app/leagues", status_code=303)


@router.post("/app/leagues/copy", include_in_schema=False)
async def leagues_copy(
    request: Request,
    from_key: str = Form("", alias="from"),
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> Response:
    email = session_email(request, settings)
    if not email:
        return _signin_needed()

    data = await store.load_user(email)
    stored = list(data.get("leagues") or [])
    if len(stored) >= MAX_LEAGUES:
        return render(email, data, f"You're at the {MAX_LEAGUES}-league cap.")

    source = next((lg for lg in leagues_mod.defaults() if lg.key == from_key), None)
    if source is None:
        return render(email, data, "That league isn't one of the built-in ones.")

    key = _slug(source.name, {raw.get("key") for raw in stored})
    blob = source.to_dict()
    blob["key"] = key
    blob["name"] = f"{source.name} (mine)"
    # The tuned QB boost does not travel: it was fitted to the owner's own
    # room. A copy derives its own from the scoring, like any other user
    # league, so the number always means what it says.
    blob["qb_boost_override"] = None
    stored.append(blob)
    await store.save_user(email, {**data, "leagues": stored})
    return RedirectResponse("/app/leagues", status_code=303)


@router.post("/app/leagues/delete", include_in_schema=False)
async def leagues_delete(
    request: Request,
    key: str = Form(...),
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> Response:
    email = session_email(request, settings)
    if not email:
        return _signin_needed()
    data = await store.load_user(email)
    stored = [raw for raw in (data.get("leagues") or []) if raw.get("key") != key]
    await store.save_user(email, {**data, "leagues": stored})
    return RedirectResponse("/app/leagues", status_code=303)
