# FB Bible — Yahoo league link (Phase 2)

The small backend behind the Fantasy Bible. It does one job: hold a Yahoo
OAuth token so the app can read **live rosters, draft results and opponent
picks** for the two leagues, instead of them being typed in by hand.

This is phase 2 of the [productization plan](docs/PHASE2_SPEC.md) — the first
piece that leaves the browser.

```
browser app  ──►  this server  ──►  Yahoo Fantasy API
                  (token exchange
                   + refresh)
```

## Quick start

```bash
python -m venv .venv && .venv/Scripts/activate
pip install -r requirements-dev.txt
cp .env.example .env
```

Generate the token encryption key and put it in `.env`:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Add your Yahoo credentials — see **[docs/YAHOO_SETUP.md](docs/YAHOO_SETUP.md)**,
which also covers Yahoo's HTTPS-only redirect requirement.

```bash
uvicorn app.main:app --reload
```

Then open <http://localhost:8000/auth/yahoo/login> to link the account, and
<http://localhost:8000/docs> for the interactive API.

## Endpoints

| Method | Path | What |
|---|---|---|
| GET | `/health` | Liveness **and** config state — reports missing credentials rather than failing silently |
| GET | `/auth/yahoo/login` | Start the OAuth flow |
| GET | `/auth/yahoo/callback` | Yahoo returns here with the code |
| GET | `/auth/yahoo/status` | Is an account linked? |
| POST | `/auth/yahoo/logout` | Forget the stored tokens |
| GET | `/api/leagues` | Leagues on the linked account |
| GET | `/api/leagues/configured` | Just Sunday Gravy and The Trenches |
| GET | `/api/leagues/{key}/teams` | Every team in a league |
| GET | `/api/leagues/{key}/draft` | Every pick, in pick order |
| GET | `/api/leagues/{key}/scoreboard?week=N` | Matchups |
| GET | `/api/leagues/{key}/transactions` | Adds, drops, trades |
| GET | `/api/teams/{key}/roster?week=N` | Live roster |
| GET | `/api/raw/{path}` | Unparsed passthrough, for exploring |

League keys are `nfl.l.192426` (Sunday Gravy) and `nfl.l.811739` (The
Trenches). The bare `nfl` game code means "current season", so they don't need
updating each year.

## How it's put together

```
app/
├── main.py            FastAPI app — also the Vercel entrypoint via api/index.py
├── config.py          Settings from env/.env
├── deps.py            Dependency wiring
├── yahoo/
│   ├── oauth.py       Three-legged OAuth2: authorize, exchange, refresh
│   ├── client.py      Authed client; refreshes on demand and retries one 401
│   └── parse.py       Flattens Yahoo's index-keyed, split-object JSON
└── store/
    ├── base.py        TokenStore protocol + TokenSet
    ├── crypto.py      Fernet encryption — tokens are never stored in the clear
    ├── file_store.py  Local dev
    └── redis_store.py Serverless
```

Three decisions worth knowing about:

**Tokens are encrypted at rest and stored behind an interface.** A Yahoo
refresh token is long-lived and grants read access to the account, so it's
never written in plaintext. The interface exists because serverless has no
writable disk — and because Phase 3 moves this to Postgres.

**The OAuth `state` is self-verifying.** It's a nonce + timestamp + HMAC rather
than a server-side session, because serverless has nowhere to park a nonce
between the login redirect and the callback. Ten-minute TTL.

**Yahoo's JSON gets flattened at the edge.** Collections come back as objects
keyed by stringified indices, and single entities as lists mixing metadata
dicts with sub-resources. `parse.normalize` collapses both so the browser app
never has to know.

## Running it

**Serverless (Vercel)** — the current target:

```bash
vercel deploy
```

`vercel.json` routes everything to `api/index.py`. Set `TOKEN_STORE=redis` and
`REDIS_URL` in the project's environment variables, along with the Yahoo
credentials and `TOKEN_ENCRYPTION_KEY` — a file store won't survive between
invocations.

**Container** — the Phase 3 shape, when cron jobs and web push need a process
that stays up:

```bash
docker build -t fb-bible . && docker run -p 8000:8000 --env-file .env fb-bible
```

Same app, same entrypoint. Nothing about the code changes.

## Tests

```bash
pytest        # 17 tests, no network, no credentials needed
ruff check .
```

Coverage is deliberately concentrated on the two things most likely to break:
the OAuth state signing (forgery, tampering, expiry) and Yahoo's JSON shape.
