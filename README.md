# Telegram YouTube Playlist Intersection Bot

Telegram bot for collecting YouTube playlist links inside a shared session and showing videos that are present in every submitted playlist.

## Stack

- Python 3.12+
- aiogram 3
- asyncpg
- Supabase Postgres
- yt-dlp

## What Changed

- The project now uses only PostgreSQL-compatible databases.
- The intended target is Supabase Postgres via `DATABASE_URL`.
- All SQLite-specific code and config were removed from the application.
- The bot now runs as a webhook-based web service instead of long polling.
- Playlist links are accepted only through `/add_playlist <url>` or through the `Add playlist` button, which prompts for the next message.
- A single user can own at most 5 sessions.

## Environment

Create `.env` from `.env.example` and set:

```env
TELEGRAM_BOT_TOKEN=your_bot_token
DATABASE_URL=postgresql://postgres.[PROJECT-REF]:[URL_ENCODED_PASSWORD]@aws-1-eu-west-1.pooler.supabase.com:5432/postgres?sslmode=require
WEBHOOK_BASE_URL=https://your-render-app.onrender.com
WEBHOOK_SECRET=long_random_secret
WEBHOOK_PATH=/telegram/webhook
PORT=8080
LOG_LEVEL=INFO
```

Notes:

- For Supabase, prefer the IPv4 session pooler connection string from the `Connect` screen.
- Direct `db.[project-ref].supabase.co` hosts may be IPv6-only depending on the environment.
- The connection pool is async and uses `asyncpg`.
- `WEBHOOK_BASE_URL` must be the public HTTPS origin of your deployed app.
- Telegram will deliver updates to `WEBHOOK_BASE_URL + WEBHOOK_PATH`.

## Running

Local:

```bash
uv sync --dev
uv run python -m src.bot
```

The application exposes:

- `GET /healthz` for liveness checks
- `POST /telegram/webhook` by default for Telegram updates

Docker:

```bash
docker compose up --build
```

`docker-compose.yml` now expects `DATABASE_URL` from your environment and does not provision a local database.

## Bot Flow

- `/start` creates a session in the current group or private chat.
- `/start <code>` joins a private session by invite code.
- `/add_playlist <url>` adds a playlist immediately.
- `/common` or the `Common videos` button shows the current intersection for the session.
- `Add playlist` button switches the bot into “waiting for URL” mode; the next playlist link message is processed.
- `Delete playlist` button switches the bot into “waiting for playlist ID” mode; the next message is treated as the playlist ID to remove.
- Plain text messages with playlist links are ignored unless the bot is explicitly waiting after `Add playlist`.

## Render Deploy

This project is now a regular web service, which fits Render better than long polling.

Set these environment variables in Render:

- `TELEGRAM_BOT_TOKEN`
- `DATABASE_URL`
- `WEBHOOK_BASE_URL=https://<your-app>.onrender.com`
- `WEBHOOK_SECRET`
- `WEBHOOK_PATH=/telegram/webhook`
- `PORT=8080`

Start command:

```bash
uv run python -m src.bot
```

Render should probe `GET /healthz`. On startup the bot will call Telegram `setWebhook` automatically.

The repo includes [render.yaml](/home/fong/.openclaw/workspace/tg_yt/render.yaml) for Blueprint-style deploys.

Operational caveat:

- Render free web services spin down after inactivity, so the first webhook after idle time may see a cold start delay.

## Main Commands

- `/start`
- `/session`
- `/playlists`
- `/add_playlist <url>`
- `/common`
- `/clear_playlists`
- `/delete_playlist <youtube_playlist_id>`
- `/clear`
- `/end_session`
- `/list_sessions`
- `/help`

## Tests

DB-backed tests require `TEST_DATABASE_URL`:

```bash
export TEST_DATABASE_URL=postgresql://postgres:password@localhost:5432/tg_yt_test
uv run pytest
```

If `TEST_DATABASE_URL` is missing, DB integration tests are skipped.

## uv Workflow

- `.python-version` pins Python 3.12.
- `pyproject.toml` is the single source of truth for dependencies.
- `uv.lock` is generated for reproducible installs.
- Use `uv sync --dev` for local development.
- Use `uv run ...` for commands, for example `uv run pytest` or `uv run python -m src.bot`.
