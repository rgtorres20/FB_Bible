# Registering the Yahoo app

You need a Yahoo developer app before any of this runs. Ten minutes, once.

## 1. Create the app

Go to <https://developer.yahoo.com/apps/create/> and fill in:

| Field | Value |
|---|---|
| Application Name | `FB Bible` (anything) |
| Application Type | **Web Application** |
| Redirect URI(s) | see below — must match `YAHOO_REDIRECT_URI` exactly |
| API Permissions | tick **Fantasy Sports**, then **Read** |

"Read" maps to the `fspt-r` scope. Only pick Read/Write if you later want the
server setting lineups — Phase 2 doesn't.

You'll get a **Client ID** and **Client Secret**. Those go in `.env`.

## 2. The redirect URI catch

**Yahoo requires HTTPS for the redirect URI.** A plain `http://localhost:8000/...`
callback will be rejected at app-registration time. Three ways around it:

**a. Register your deployed URL and develop against it** — simplest if you're
deploying to Vercel anyway:

```
https://<your-project>.vercel.app/auth/yahoo/callback
```

**b. Tunnel to localhost** — good for iterating on the callback handler:

```bash
ngrok http 8000
```

Register the `https://<subdomain>.ngrok-free.app/auth/yahoo/callback` URL and
set `YAHOO_REDIRECT_URI` to match. Note that a free ngrok subdomain changes on
every restart, and you have to re-register each time.

**c. Local HTTPS with a self-signed cert** — no external dependency:

```bash
openssl req -x509 -newkey rsa:2048 -nodes -keyout key.pem -out cert.pem -days 365 -subj "/CN=localhost"
uvicorn app.main:app --ssl-keyfile key.pem --ssl-certfile cert.pem --port 8000
```

Then register `https://localhost:8000/auth/yahoo/callback`. Your browser will
warn about the cert; accept it once.

Yahoo matches the redirect URI **exactly** — trailing slashes, scheme and port
all count. A mismatch shows up as `error=invalid_request` on the callback.

## 3. Fill in .env

```bash
cp .env.example .env
```

Generate the encryption key (tokens are never written in the clear):

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Put that in `TOKEN_ENCRYPTION_KEY`, then add your Client ID, Client Secret and
the redirect URI you registered. Set `SESSION_SECRET` to any long random
string.

## 4. Link the account

Start the server, then visit `/auth/yahoo/login`. Yahoo will ask you to approve
the app; approving lands you back on `/auth/yahoo/callback`, which stores the
token pair and shows a confirmation page.

Check it took:

```bash
curl http://localhost:8000/auth/yahoo/status
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| 503 "Yahoo credentials are not configured" | `YAHOO_CLIENT_ID`/`SECRET` missing from `.env` |
| 400 "Invalid or expired OAuth state" | The login page sat open >10 min, or the callback was reached directly. Start again at `/auth/yahoo/login`. |
| `error=invalid_request` from Yahoo | `YAHOO_REDIRECT_URI` doesn't exactly match the registered one |
| 401 from `/api/*` after it worked | Refresh token revoked (password change, or app removed in Yahoo account settings). Re-link. |
| Empty `leagues` list | The Yahoo account signed in isn't the one in those leagues, or the season's game code has rolled and `nfl` now points at a season you're not in. |
