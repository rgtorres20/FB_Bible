"""Feed endpoints.

`/api/feeds` is what the browser app reads instead of a chat-synced
`feeds.json`. `/internal/sync` is what the scheduler calls.

The sync endpoint is a POST behind a shared secret, not because the data is
sensitive -- it is public news -- but because it makes outbound requests to
five publishers. Leaving it open invites someone to use your deployment to
hammer them.
"""

from __future__ import annotations

import hmac
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .. import authn
from .. import leagues as leagues_mod
from ..config import Settings, get_settings
from ..feeds import (
    adp,
    alerts300,
    build_feed_store,
    capsules,
    cheatsheet,
    idp,
    injury,
    mock,
    players,
    poller,
    previews,
    render,
    stats,
    vegas,
)
from ..feeds.store import FeedStore

log = logging.getLogger(__name__)

router = APIRouter(tags=["feeds"])

# The committed feeds.json the page ships with. Live wire items are overlaid
# onto it; everything else in the file is served as-is.
BUNDLED_FEEDS = Path(__file__).resolve().parent.parent.parent / "frontend" / "data" / "feeds.json"


def get_feed_store(settings: Settings = Depends(get_settings)) -> FeedStore:
    try:
        return build_feed_store(settings)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=f"Feed store not configured: {exc}") from exc


def get_optional_feed_store(settings: Settings = Depends(get_settings)) -> FeedStore | None:
    """For routes that overlay live data onto a page: a missing store means
    'serve the committed content', never a 503 -- the page must render."""
    try:
        return build_feed_store(settings)
    except ValueError:
        return None


@router.get("/app/data/feeds.json", include_in_schema=False)
async def app_feeds(store: FeedStore = Depends(get_feed_store)) -> dict:
    """Serve the page's own data file, with live news overlaid.

    Declared before the /app static mount so this wins over the file on disk.
    The page fetches this path at startup already -- so pointing it at live
    data needs no change to index.html, and no fork from the design project.

    Every failure path falls back to the committed file: a blank news tab
    would be worse than a slightly stale one.
    """
    try:
        bundled = json.loads(BUNDLED_FEEDS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        bundled = {}

    try:
        stored = await store.load()
    except Exception as exc:  # noqa: BLE001 - never take the app down for this
        log.warning("feed store unavailable, serving bundled feeds: %s", exc)
        return bundled

    index = await store.load_players()
    ranks = {
        pid: p["rank"]
        for pid, p in (index or {}).get("players", {}).items()
        if p.get("rank") is not None
    }
    merged = render.merge_into_feeds(
        bundled,
        stored.get("items", []),
        datetime.now(UTC),
        ranks,
        adp_data=stored.get("adp"),
        index=index,
        verdicts=stored.get("verdicts"),
        vegas_state=stored.get("vegas"),
        injury_names=injury.watched_names(),
        stats_state=stored.get("stats"),
        mover_reads=stored.get("mover_reads"),
        scores_state=stored.get("scores"),
    )
    return render.rename_leagues(merged)


@router.get("/app/cheatsheet", include_in_schema=False, response_class=HTMLResponse)
async def draft_cheatsheet(store: FeedStore = Depends(get_feed_store)) -> HTMLResponse:
    """Printable draft board from the live blended ADP. Declared before the
    /app static mount so it wins; zero scripts so it prints cleanly."""
    try:
        stored = await store.load()
        index = await store.load_players()
    except Exception as exc:  # noqa: BLE001 - a broken store yields the empty sheet
        log.warning("cheatsheet: store unavailable: %s", exc)
        stored, index = {}, None
    state = (stored.get("adp") or {}).get("state") or {}
    return HTMLResponse(cheatsheet.build_html(state, index, datetime.now(UTC)))


async def _leagues_for(
    request: Request, settings: Settings, store: FeedStore
) -> list[leagues_mod.League]:
    """The leagues this visitor's boards should be scored with.

    The owner's verified two, plus whatever the signed-in user defined at
    /app/leagues. Read here rather than through the settings router so
    the two do not import each other; `authn` is the leaf both share.
    Nobody signed in (or the gate switched off) sees the built-ins alone,
    which is exactly what shipped before.
    """
    email = authn.read_session(request.cookies.get(authn.SESSION_COOKIE), settings.session_secret)
    if not email:
        return leagues_mod.defaults()
    try:
        return leagues_mod.for_user(await store.load_user(email))
    except Exception as exc:  # noqa: BLE001 - a broken store must not blank the board
        log.warning("league settings unavailable, falling back to the built-ins: %s", exc)
        return leagues_mod.defaults()


@router.get("/app/alerts300", include_in_schema=False, response_class=HTMLResponse)
async def alerts_top300(store: FeedStore = Depends(get_feed_store)) -> HTMLResponse:
    """The top-300 alert board: every ranked player's latest wire word and
    its labelled machine-drafted line. Declared before the /app static mount
    so it wins; zero scripts, same as the cheat sheet."""
    try:
        stored = await store.load()
        index = await store.load_players()
    except Exception as exc:  # noqa: BLE001 - a broken store yields the honest empty page
        log.warning("alerts300: store unavailable: %s", exc)
        stored, index = {}, None
    return HTMLResponse(
        alerts300.build_html(
            index,
            stored.get("items", []),
            stored.get("verdicts") or {},
            (stored.get("adp") or {}).get("state"),
            datetime.now(UTC),
            capsules=stored.get("capsules") or {},
        )
    )


@router.get("/app/idp", include_in_schema=False, response_class=HTMLResponse)
async def idp_board(
    request: Request,
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> HTMLResponse:
    """The IDP draft board: every indexed defender scored with each league's
    own settings — the owner's verified two (docs/LEAGUES.md) plus any the
    signed-in user entered at /app/leagues, one column each. Declared before
    the /app static mount so it wins; zero scripts, same as the cheat sheet."""
    try:
        stored = await store.load()
        index = await store.load_players()
    except Exception as exc:  # noqa: BLE001 - a broken store yields the honest empty page
        log.warning("idp board: store unavailable: %s", exc)
        stored, index = {}, None
    return HTMLResponse(
        idp.build_html(
            index,
            stored.get("stats"),
            datetime.now(UTC),
            board_leagues=await _leagues_for(request, settings, store),
        )
    )


@router.get("/app/mock", include_in_schema=False, response_class=HTMLResponse)
async def mock_draft_room(
    request: Request,
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> HTMLResponse:
    """The mock draft room: the owner picks a league and a slot, the other
    nine teams autopick from the live pool (see app/feeds/mock.py for the
    honesty rules). Declared before the /app static mount so it wins."""
    try:
        stored = await store.load()
        index = await store.load_players()
    except Exception as exc:  # noqa: BLE001 - a broken store yields the honest empty page
        log.warning("mock room: store unavailable: %s", exc)
        stored, index = {}, None
    return HTMLResponse(
        mock.build_html(
            index,
            (stored.get("adp") or {}).get("state"),
            stored.get("stats"),
            stored.get("capsules") or {},
            datetime.now(UTC),
            board_leagues=await _leagues_for(request, settings, store),
        )
    )


@router.get("/app/mock/board", include_in_schema=False, response_class=HTMLResponse)
async def mock_draft_board() -> HTMLResponse:
    """The draft board the mock room hands off, as a real page.

    The room used to write the board into an about:blank popup, which
    gave that tab no document of its own -- so refreshing it reloaded
    about:blank and the board went white (owner, Aug 21). This route is
    the fix: a real same-origin URL that reads the board the room left in
    localStorage, so reload, back/forward and share-to-self all work.

    The board is entirely the visitor's own draft, so nothing is stored
    server-side and nothing here touches the feed store. Declared before
    the /app static mount so it wins.
    """
    return HTMLResponse(mock.BOARD_PAGE)


@router.get("/api/defenses", summary="Stored team-defense season lines")
async def read_defenses(store: FeedStore = Depends(get_feed_store)) -> dict:
    """The 32 team-defense season lines, unscored.

    Unscored on purpose: what a defense is worth depends entirely on the
    league reading it (/app/leagues), so this returns the measurements
    and lets the caller price them. `complete` is how many carry a
    points-allowed ladder accounting for all of their games -- the
    check the boards gate on, reported here so a deploy can be verified
    without guessing from a rendered page.
    """
    try:
        stored = await store.load()
    except Exception as exc:  # noqa: BLE001 - an honest empty beats a 500
        log.warning("defenses: store unavailable: %s", exc)
        stored = {}
    state = stored.get("stats") or {}
    coverage = state.get("coverage") or {}
    return {
        "season": state.get("season"),
        "fetched_at": state.get("fetched_at"),
        "total": coverage.get("defenses") or 0,
        "complete": coverage.get("defense_pa_complete") or 0,
        "defenses": state.get("defenses") or {},
        "source": "Sleeper",
    }


@router.get("/api/feeds", summary="Polled news items, newest first")
async def read_feeds(
    limit: int = Query(default=100, ge=1, le=400),
    source: str | None = Query(default=None, description="Filter to one source key"),
    tier: int | None = Query(default=None, ge=1, le=2),
    player: str | None = Query(
        default=None, description="Only items mentioning this player id or name"
    ),
    tagged_only: bool = Query(
        default=False, description="Only items that mention a fantasy-relevant player"
    ),
    store: FeedStore = Depends(get_feed_store),
) -> dict:
    data = await store.load()
    items = data.get("items", [])

    if source:
        items = [i for i in items if i.get("source_key") == source]
    if tier:
        items = [i for i in items if i.get("tier") == tier]
    if tagged_only:
        items = [i for i in items if i.get("players")]
    if player:
        needle = player.strip().lower()
        items = [
            i
            for i in items
            if any(
                p.get("id") == player or needle in (p.get("name") or "").lower()
                for p in i.get("players", [])
            )
        ]

    now = datetime.now(UTC)
    sources = data.get("sources", {})
    # The honest freshness label, rather than a hardcoded "live".
    for status in sources.values():
        status["state"] = poller.freshness(status, now)

    return {
        "items": items[:limit],
        "total": len(items),
        "sources": sources,
        "polled_at": data.get("polled_at"),
        # Which items already carry an AI-drafted verdict. The hourly drafting
        # job reads this to spend its request on uncovered items instead of
        # re-drafting the same newest handful every run.
        "verdict_ids": sorted(data.get("verdicts") or {}),
    }


def _require_sync_token(settings: Settings, x_sync_token: str | None) -> None:
    if not settings.sync_token:
        raise HTTPException(
            status_code=503,
            detail="SYNC_TOKEN is not set, so scheduled sync is disabled.",
        )
    # compare_digest, not ==, so the comparison does not leak the token's
    # length or prefix through timing.
    if not x_sync_token or not hmac.compare_digest(x_sync_token, settings.sync_token):
        raise HTTPException(status_code=401, detail="Bad or missing X-Sync-Token.")


class VerdictsIn(BaseModel):
    verdicts: dict[str, str]


class VegasIn(BaseModel):
    state: dict


class PredReviewsIn(BaseModel):
    reviews: dict[str, str]


# One short clause appended to an existing "why" cell, not a paragraph.
MAX_REVIEW_CHARS = 110
MAX_REVIEWS = 24


# The odds table renders the first five; the last four feed the Week 1
# schedule tab (kickoff ISO, full team names, network).
_VEGAS_ROW_FIELDS = (
    "game",
    "fav",
    "total",
    "imp",
    "read",
    "kickoff",
    "away_name",
    "home_name",
    "tv",
)
MAX_VEGAS_ROWS = 32


@router.post("/internal/vegas", summary="Store the Vegas slate pushed by the scheduler")
async def save_vegas(
    payload: VegasIn,
    x_sync_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> dict:
    """ESPN 403s requests from Vercel's IP range (verified live 2026-08-15),
    so the GitHub Actions runner fetches the scoreboard and pushes the slate
    here -- the same split as the sync scheduler itself: GitHub provides the
    network vantage point, the deployment stores and serves.

    Rows are rebuilt field-by-field rather than stored verbatim: this data
    is rendered into the page, so only the known string columns pass.
    """
    _require_sync_token(settings, x_sync_token)

    games = []
    for row in (payload.state.get("games") or [])[:MAX_VEGAS_ROWS]:
        if not isinstance(row, dict) or not row.get("game"):
            continue
        games.append({field: str(row.get(field) or "") for field in _VEGAS_ROW_FIELDS})
    if not games:
        raise HTTPException(status_code=422, detail="No usable rows in state.games.")

    data = await store.load()
    data["vegas"] = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "week_label": str(payload.state.get("week_label") or "")[:40],
        "games": games,
    }
    await store.save(data)
    return {"stored": len(games), "week_label": data["vegas"]["week_label"]}


# The Week review tab's game rows: four known string columns, same
# sanitize-per-field rule as the Vegas slate.
_SCORE_ROW_FIELDS = ("day", "score", "status", "note")
MAX_SCORE_ROWS = 32


@router.post("/internal/scores", summary="Store the current week's scoreboard")
async def save_scores(
    payload: VegasIn,
    x_sync_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> dict:
    """Pushed by the sync-feeds runner beside the Vegas slate (ESPN 403s
    Vercel's IPs). Rows are rebuilt field-by-field: this renders into the
    page's Week review tab, so only the known string columns pass."""
    _require_sync_token(settings, x_sync_token)

    games = []
    for row in (payload.state.get("games") or [])[:MAX_SCORE_ROWS]:
        if not isinstance(row, dict) or not row.get("score"):
            continue
        games.append({field: str(row.get(field) or "") for field in _SCORE_ROW_FIELDS})
    if not games:
        raise HTTPException(status_code=422, detail="No usable rows in state.games.")

    data = await store.load()
    data["scores"] = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "week_label": str(payload.state.get("week_label") or "")[:40],
        "range": str(payload.state.get("range") or "")[:60],
        "games": games,
    }
    await store.save(data)
    return {"stored": len(games), "week_label": data["scores"]["week_label"]}


@router.post("/internal/pred-reviews", summary="Store AI checks of the TD leans")
async def save_pred_reviews(
    payload: PredReviewsIn,
    x_sync_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> dict:
    """A one-line sanity check per TD lean, drafted against the live line.

    Keyed by the player name as the page spells it, and only kept for names
    the committed PREDICTIONS table actually carries -- the model cannot
    introduce a row by inventing a player. The lean itself is never touched:
    these render as a separate "AI check:" clause so a disagreement is
    visible without the owner's call being quietly rewritten.
    """
    _require_sync_token(settings, x_sync_token)

    known = {p["name"] for p in vegas.curated_predictions()}
    accepted = {
        name: text.strip()[:MAX_REVIEW_CHARS]
        for name, text in list(payload.reviews.items())[:MAX_REVIEWS]
        if name in known and text.strip()
    }
    if not accepted:
        raise HTTPException(status_code=422, detail="No reviews matched a known prediction.")

    data = await store.load()
    data["pred_reviews"] = accepted
    await store.save(data)
    return {"stored": len(accepted)}


class CapsulesIn(BaseModel):
    capsules: dict[str, dict]


class MoverReadsIn(BaseModel):
    reads: dict[str, str]


# Same shape as a pred-review: one clause appended to an existing card.
MAX_MOVER_READ_CHARS = 110


@router.get("/api/capsules/pending", summary="Top-300 players still needing an AI capsule")
async def capsules_pending(
    limit: int = Query(default=capsules.BATCH, ge=1, le=40),
    store: FeedStore = Depends(get_feed_store),
) -> dict:
    """The hourly capsule job's work list: uncovered top-300 players, best
    rank first, each row carrying every number the model is allowed to use
    (Sleeper rank, live ADP, '25 usage, injury flag, newest wire word).
    Assembled server-side so the prompt can only cite figures we fetched.
    """
    data = await store.load()
    index = await store.load_players()
    covered = data.get("capsules") or {}
    work = capsules.pending(
        index,
        (data.get("adp") or {}).get("state"),
        data.get("stats"),
        data.get("items", []),
        covered,
        limit=limit,
    )
    return {"players": work, "covered": len(covered)}


@router.post("/internal/capsules", summary="Store AI player capsules for the top-300 board")
async def save_capsules(
    payload: CapsulesIn,
    x_sync_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> dict:
    """One synthesis line per player, rendered "AI angle:" on the top-300
    board. Only ids the player index ranks in the top 300 are accepted --
    the model cannot add a row by inventing a player -- and each capsule
    remembers the wire item it saw, so the pending list re-drafts a player
    when his news changes instead of letting a stale line sit forever.
    """
    _require_sync_token(settings, x_sync_token)

    data = await store.load()
    index = await store.load_players()
    accepted = capsules.accept(payload.capsules, index, data.get("capsules"))
    if payload.capsules and not any(pid in accepted for pid in payload.capsules):
        raise HTTPException(status_code=422, detail="No capsules matched a top-300 player.")

    data["capsules"] = accepted
    await store.save(data)
    return {"stored": len(accepted)}


class PreviewsIn(BaseModel):
    previews: dict[str, str]


@router.get("/api/previews/pending", summary="Slate games still needing an AI matchup preview")
async def previews_pending(store: FeedStore = Depends(get_feed_store)) -> dict:
    """The preview job's work list: each slate game without a current
    preview, carrying the line (favorite, total, per-side implied points)
    and the '25 offense profiles for both teams. A stored preview re-queues
    when its game's line has genuinely moved, so the prose never cites a
    number the table no longer shows."""
    data = await store.load()
    work = previews.pending(data.get("vegas"), data.get("stats"), data.get("previews"))
    return {"games": work}


@router.post("/internal/previews", summary="Store AI matchup previews for the schedule tab")
async def save_previews(
    payload: PreviewsIn,
    x_sync_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> dict:
    """One short read per game, rendered on the schedule tab appended to the
    row's note prefixed "AI preview:". Only games the stored slate holds are
    accepted -- the model cannot invent a matchup -- and each preview
    snapshots the line it was drafted against for the freshness check."""
    _require_sync_token(settings, x_sync_token)

    data = await store.load()
    slate_keys = {r.get("game") for r in (data.get("vegas") or {}).get("games") or []}
    if payload.previews and not (set(payload.previews) & slate_keys):
        raise HTTPException(status_code=422, detail="No previews matched a slate game.")

    data["previews"] = previews.accept(payload.previews, data.get("vegas"), data.get("previews"))
    await store.save(data)
    return {"stored": len(data["previews"])}


@router.get("/api/leans/pending", summary="TD leans beside their live implied totals")
async def leans_pending(store: FeedStore = Depends(get_feed_store)) -> dict:
    """The annotate job's lean-review work list: each curated TD lean with
    the live implied total for its team. Unlike the other pending lists this
    one is re-reviewed every hour by design -- the check tracks a moving
    line, not a one-time fact."""
    data = await store.load()
    games = (data.get("vegas") or {}).get("games") or []
    return {"leans": vegas.lean_review_rows(games)}


@router.get("/api/movers/pending", summary="ADP movers still needing an AI read")
async def movers_pending(store: FeedStore = Depends(get_feed_store)) -> dict:
    """The mover-reads job's work list: each current riser/faller beside the
    newest wire story tagging that player. Movers with no story are absent
    by design -- an explanation without a source would be an invented cause.
    """
    data = await store.load()
    state = (data.get("adp") or {}).get("state") or {}
    history = (data.get("adp") or {}).get("history")
    work = adp.pending_reads(state, history, data.get("items", []), data.get("mover_reads"))
    return {"movers": work}


@router.post("/internal/mover-reads", summary="Store AI reads on the ADP movers")
async def save_mover_reads(
    payload: MoverReadsIn,
    x_sync_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> dict:
    """One clause per mover tying the move to its wire story, appended to
    the Scout card prefixed "AI read:". Only names that are movers right
    now are kept, and reads are pruned as their movers drop off the list --
    the model cannot annotate a card the page does not show.
    """
    _require_sync_token(settings, x_sync_token)

    data = await store.load()
    state = (data.get("adp") or {}).get("state") or {}
    history = (data.get("adp") or {}).get("history")
    current = {m["entry"]["name"] for m in adp.movers(state, history)}
    if payload.reads and not (set(payload.reads) & current):
        raise HTTPException(status_code=422, detail="No reads matched a current mover.")
    accepted = adp.accept_reads(
        payload.reads, state, history, data.get("mover_reads"), MAX_MOVER_READ_CHARS
    )

    data["mover_reads"] = accepted
    await store.save(data)
    return {"stored": len(accepted)}


MAX_VERDICT_CHARS = 200


@router.post("/internal/verdicts", summary="Store AI-drafted verdicts for wire items")
async def save_verdicts(
    payload: VerdictsIn,
    x_sync_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> dict:
    """Called by the scheduled GitHub Models job, never by the browser.

    Verdicts are keyed by wire-item id and only accepted for items we
    actually hold -- the model cannot invent a story by inventing an id.
    They render prefixed "AI draft:" so they never read as the owner's
    judgement, and they are pruned with the items they belong to.
    """
    _require_sync_token(settings, x_sync_token)

    data = await store.load()
    valid_ids = {item.get("id") for item in data.get("items", [])}
    accepted = {
        item_id: text.strip()[:MAX_VERDICT_CHARS]
        for item_id, text in payload.verdicts.items()
        if item_id in valid_ids and text.strip()
    }

    merged = {**(data.get("verdicts") or {}), **accepted}
    data["verdicts"] = {k: v for k, v in merged.items() if k in valid_ids}
    await store.save(data)

    return {"accepted": len(accepted), "stored": len(data["verdicts"])}


@router.post("/internal/sync", summary="Poll every source and merge new items")
async def sync(
    x_sync_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    store: FeedStore = Depends(get_feed_store),
) -> dict:
    _require_sync_token(settings, x_sync_token)

    polled = await poller.poll()

    # Tag items with the players they mention -- this is what makes the feed
    # answerable to "does this affect my board". The index is cached because
    # the source dump is ~14MB; a fetch failure degrades to untagged items
    # rather than failing the whole sync.
    index = await store.load_players()
    if index is None:
        try:
            index = await players.fetch_index()
            await store.save_players(index)
        except Exception as exc:  # noqa: BLE001
            log.warning("player index unavailable, items will be untagged: %s", exc)
            index = None
    if index:
        players.tag_items(polled["items"], index)

    existing = await store.load()
    merged = poller.merge(existing, polled["items"], datetime.now(UTC))

    # ADP rides the same hourly sync. A failed fetch keeps the previous board
    # and its history intact -- yesterday's ADP is still a usable draft board,
    # while a truncated history would silently kill the movers section.
    adp_prev = existing.get("adp") or {}
    adp_state = adp_prev.get("state") or {}
    adp_history = adp_prev.get("history") or []
    try:
        adp_state = await adp.fetch()
        adp_history = adp.update_history(adp_history, adp_state)
    except Exception as exc:  # noqa: BLE001 - ADP must never sink the news sync
        log.warning("ADP fetch failed, keeping previous board: %s", exc)

    # Vegas lines ride along under the same rule: stale lines with an honest
    # stamp beat no lines, so a failed fetch keeps the previous slate. On
    # Vercel the fetch is skipped outright -- ESPN 403s its IP range (see
    # /internal/vegas), so attempting it burns timeout budget and widens the
    # window in which a concurrent slate push can be clobbered.
    vegas_state = existing.get("vegas") or {}
    vegas_error = None
    if settings.vercel_env:
        vegas_error = "skipped: ESPN blocks Vercel IPs; slate arrives via /internal/vegas"
    else:
        try:
            vegas_state = await vegas.fetch()
        except Exception as exc:  # noqa: BLE001
            vegas_error = f"{type(exc).__name__}: {exc}"[:200]
            log.warning("Vegas fetch failed, keeping previous lines: %s", exc)

    # Verdicts travel with the items they annotate: carry them forward pruned
    # to items that survived the merge. Omitting this key wiped the verdict
    # store on every sync -- the hourly AI job's output lived for minutes.
    surviving = {item.get("id") for item in merged["items"]}
    verdicts = {k: v for k, v in (existing.get("verdicts") or {}).items() if k in surviving}
    # Not keyed to wire items, so nothing prunes them here -- but they must
    # survive the save, which is exactly what the verdicts bug was. Capsules
    # and mover reads are pruned where they are validated (their accept
    # functions), not on sync.
    pred_reviews = existing.get("pred_reviews") or {}
    capsule_state = existing.get("capsules") or {}
    mover_reads = existing.get("mover_reads") or {}
    preview_state = existing.get("previews") or {}
    scores_state = existing.get("scores") or {}

    # Season stats are final numbers, not a feed: refetch weekly (or when the
    # store lost them), keep the previous state on any failure. Same rule as
    # ADP -- last week's final-season stats are identical to this week's,
    # while an empty state would revert Team intel to its curated estimates.
    stats_state = existing.get("stats") or {}
    if stats.stale(stats_state, datetime.now(UTC)):
        try:
            stats_state = await stats.fetch()
        except Exception as exc:  # noqa: BLE001 - stats must never sink the news sync
            log.warning("season stats fetch failed, keeping previous state: %s", exc)

    await store.save(
        {
            "items": merged["items"],
            "sources": polled["sources"],
            "polled_at": polled["polled_at"],
            "adp": {"state": adp_state, "history": adp_history},
            "vegas": vegas_state,
            "verdicts": verdicts,
            "stats": stats_state,
            "pred_reviews": pred_reviews,
            "capsules": capsule_state,
            "mover_reads": mover_reads,
            "previews": preview_state,
            "scores": scores_state,
        }
    )

    failed = [k for k, v in polled["sources"].items() if not v["ok"]]
    log.info(
        "sync: %d new, %d total, %d sources failed",
        len(merged["new_ids"]),
        len(merged["items"]),
        len(failed),
    )
    tagged = sum(1 for i in merged["items"] if i.get("players"))
    return {
        "new": len(merged["new_ids"]),
        "total": len(merged["items"]),
        "tagged": tagged,
        "sources_ok": len(polled["sources"]) - len(failed),
        "sources_failed": failed,
        "adp_players": len(adp_state.get("players", [])),
        "vegas_games": len(vegas_state.get("games", [])),
        "vegas_error": vegas_error,
        "stats_teams": len(stats_state.get("teams", {})),
        "stats_usage_complete": stats.usage_reads(stats_state) is not None,
        # Team defenses, and how many carry a full points-allowed ladder.
        # In the sync's own response because a refetch that quietly
        # stored zero of them is the failure mode worth seeing in the
        # runner log rather than an hour later on a board.
        "stats_defenses": len(stats_state.get("defenses", {})),
        "stats_defenses_complete": (stats_state.get("coverage") or {}).get(
            "defense_pa_complete", 0
        ),
        "polled_at": polled["polled_at"],
    }
