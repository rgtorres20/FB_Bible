"""League data endpoints.

Everything here is what the blueprint's phase 2 promises: live rosters, draft
results and opponent picks, instead of hand-entering them into the page.

Responses are already flattened by app.yahoo.parse, so the browser app never
has to learn Yahoo's JSON shape. Raw passthrough stays available under
/api/raw/... for the shapes we haven't modelled yet.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..config import Settings, get_settings
from ..deps import get_yahoo
from ..yahoo import NotAuthenticated, YahooAPIError, YahooClient, parse

router = APIRouter(prefix="/api", tags=["league"])


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, NotAuthenticated):
        return HTTPException(status_code=401, detail="Yahoo not linked. Visit /auth/yahoo/login.")
    if isinstance(exc, YahooAPIError):
        return HTTPException(status_code=502, detail=str(exc))
    raise exc


@router.get("/leagues", summary="Leagues on the linked Yahoo account")
async def leagues(yahoo: YahooClient = Depends(get_yahoo)) -> dict:
    try:
        payload = await yahoo.user_leagues()
    except (NotAuthenticated, YahooAPIError) as exc:
        raise _handle(exc) from exc
    return {"leagues": parse.parse_leagues(payload)}


@router.get("/leagues/configured", summary="Just the two leagues from the blueprint")
async def configured_leagues(
    settings: Settings = Depends(get_settings),
    yahoo: YahooClient = Depends(get_yahoo),
) -> dict:
    out = []
    for key in settings.league_keys:
        try:
            out.append(parse.content(await yahoo.league(key)))
        except (NotAuthenticated, YahooAPIError) as exc:
            raise _handle(exc) from exc
    return {"leagues": out}


@router.get("/leagues/{league_key}/teams", summary="Every team in a league")
async def teams(league_key: str, yahoo: YahooClient = Depends(get_yahoo)) -> dict:
    try:
        return parse.content(await yahoo.league_teams(league_key))
    except (NotAuthenticated, YahooAPIError) as exc:
        raise _handle(exc) from exc


@router.get("/teams/{team_key}/roster", summary="Live roster for a team")
async def roster(
    team_key: str,
    week: int | None = Query(default=None, ge=1, le=18),
    yahoo: YahooClient = Depends(get_yahoo),
) -> dict:
    try:
        payload = await yahoo.roster(team_key, week)
    except (NotAuthenticated, YahooAPIError) as exc:
        raise _handle(exc) from exc
    return {"team_key": team_key, "week": week, "players": parse.parse_roster(payload)}


@router.get("/leagues/{league_key}/draft", summary="Every pick, in pick order")
async def draft(league_key: str, yahoo: YahooClient = Depends(get_yahoo)) -> dict:
    try:
        payload = await yahoo.draft_results(league_key)
    except (NotAuthenticated, YahooAPIError) as exc:
        raise _handle(exc) from exc
    return {"league_key": league_key, "picks": parse.parse_draft_results(payload)}


@router.get("/leagues/{league_key}/scoreboard", summary="Matchups for a week")
async def scoreboard(
    league_key: str,
    week: int | None = Query(default=None, ge=1, le=18),
    yahoo: YahooClient = Depends(get_yahoo),
) -> dict:
    try:
        return parse.content(await yahoo.scoreboard(league_key, week))
    except (NotAuthenticated, YahooAPIError) as exc:
        raise _handle(exc) from exc


@router.get("/leagues/{league_key}/transactions", summary="Adds, drops and trades")
async def transactions(league_key: str, yahoo: YahooClient = Depends(get_yahoo)) -> dict:
    try:
        return parse.content(await yahoo.transactions(league_key))
    except (NotAuthenticated, YahooAPIError) as exc:
        raise _handle(exc) from exc


@router.get("/raw/{path:path}", summary="Unparsed passthrough to the Yahoo API")
async def raw(path: str, yahoo: YahooClient = Depends(get_yahoo)) -> dict:
    """Escape hatch for resources not modelled above -- keeps exploration in
    the browser instead of requiring a code change."""
    try:
        return await yahoo.get(path)
    except (NotAuthenticated, YahooAPIError) as exc:
        raise _handle(exc) from exc
