# Telegram YouTube Playlist Intersection Bot

A Telegram bot that collects YouTube playlist links from multiple users within a chat session and finds common videos across all provided playlists.

## Features

- Each Telegram chat (group or private) has its own isolated session.
- Users can submit YouTube playlist URLs.
- Bot stores playlists and their videos in a PostgreSQL database.
- Automatically computes the intersection of videos that appear in **every** playlist of the session.
- Replies with a list of common videos (title and link).
- Commands: `/start`, `/playlists`, `/clear`.
- Async runtime with aiogram 3.x.
- Dockerized for easy deployment.
- Full test suite with pytest.

## Tech Stack

- Python 3.12+
- [aiogram 3](https://github.com/aiogram/aiogram) — Telegram Bot Framework
- [asyncpg](https://github.com/MagicStack/asyncpg) —Async PostgreSQL driver
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) — YouTube metadata extraction
- PostgreSQL (Supabase compatible)
- Docker & Docker Compose

## Project Structure

```
tg_yt/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── requirements.txt
├── src/
│   ├── __init__.py
│   ├── config.py          # Environment configuration and logging
│   ├── models.py          # Data classes (Session, User, Playlist, Video)
│   ├── database.py        # asyncpg CRUD operations
│   ├── youtube.py         # yt-dlp integration
│   ├── intersection.py    # Intersection computation
│   └── bot.py             # aiogram bot, handlers, main entrypoint
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_database.py
    ├── test_intersection.py
    ├── test_youtube.py
    └── test_bot.py
```

## Setup and Installation

### Prerequisites

- Docker and Docker Compose
- Python 3.12+ (for local development)
- A Telegram Bot token from [BotFather](https://t.me/BotFather)

### Using Docker Compose (Recommended)

1. Clone the repository (or copy the project folder).
2. Copy `.env.example` to `.env` and fill in your `TELEGRAM_BOT_TOKEN`:
   ```bash
   cp .env.example .env
   # edit .env with your token
   ```
3. Start the services:
   ```bash
   docker-compose up --build
   ```
   This will build the bot image and start the PostgreSQL container.
4. The bot should connect and be ready to receive messages.

### Local Development (without Docker)

1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate  # or venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```
2. Set up a PostgreSQL database (Supabase cloud or local). Note the connection URL.
3. Create a `.env` file in the project root:
   ```env
   TELEGRAM_BOT_TOKEN=your_bot_token
   DATABASE_URL=postgresql://user:password@host:port/dbname
   LOG_LEVEL=INFO
   ```
4. Run the bot:
   ```bash
   python -m src.bot
   ```

## Usage

- In any Telegram chat, send `/start` to initialize the session.
- Send a YouTube playlist URL, e.g. `https://www.youtube.com/playlist?list=PL...`.
- The bot will fetch the playlist, store it, and reply with the list of videos that appear in **all** playlists added so far in this chat.
- Use `/playlists` to see all playlists added to the current session (includes YouTube playlist ID).
- Use `/clear_playlists` to delete all playlists in the current session (keeps the session and users).
- Use `/delete <youtube_playlist_id>` to remove a specific playlist from the session (e.g., `/delete PL123abc`).
- Use `/clear` to delete all data for the current session (anyone can use it; in production restrict to admins).

### Notes

- The bot accepts only valid YouTube playlist URLs. It uses `yt-dlp` to extract metadata; no YouTube API key required.
- Due to network constraints, fetching a playlist may take a few seconds.
- Videos are identified by YouTube video ID. Titles and URLs are taken from the first occurrence in the database.

## Database Schema

The bot uses four main tables:

- `sessions` – one row per Telegram chat (`chat_id`).
- `users` – users within a session (`telegram_id` scoped to session).
- `playlists` – each submitted playlist belongs to a user and a session.
- `videos` – individual videos belonging to a playlist.

Foreign keys with `ON DELETE CASCADE` ensure data integrity. Indexes on `session_id`, `playlist_id`, and `youtube_video_id` improve performance for intersection queries.

## Running Tests

Ensure a PostgreSQL instance is available. For best isolation, create a separate test database and set `TEST_DATABASE_URL`:

```bash
# Example: create a test database
createdb tg_yt_test  # or via psql: CREATE DATABASE tg_yt_test;
export TEST_DATABASE_URL=postgresql://postgres:password@localhost:5432/tg_yt_test
pytest
```

If `TEST_DATABASE_URL` is not set, the tests will use `DATABASE_URL`. Tests create needed tables and roll back changes within a transaction, so they won't persist data.

Alternatively, run tests inside the bot container:

```bash
docker compose run --rm bot pytest
```

The test suite covers:

- Database CRUD and intersection queries
- Intersection logic
- YouTube playlist fetching (with yt-dlp mocked)
- Bot handler behavior (with mocks)

## Environment Variables

| Variable           | Description                              | Required |
|--------------------|------------------------------------------|----------|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot token from BotFather        | Yes      |
| `DATABASE_URL`     | PostgreSQL connection string             | Yes      |
| `LOG_LEVEL`        | Logging level (DEBUG, INFO, WARNING, ERROR) | No (default INFO) |

## Docker Details

- **Base image**: `python:3.12-slim`
- System dependencies: `ffmpeg` (for yt-dlp), `gcc`, `libpq-dev` (for asyncpg).
- The bot container starts after the database health check passes.
- Data in PostgreSQL is persisted in a Docker volume (`postgres_data`).

## Development Tips

- Database tables are created automatically on startup if they don't exist.
- For local development, you can use `python -m src.bot` after setting up `.env`.
- Logs are printed to stdout in JSON-friendly format.
- The bot uses `aiogram`'s `Dispatcher` with a simple Router pattern.

## Limitations & Future Work

- No pagination for common videos list (if many).
- No support for private playlists requiring authentication.
- `/clear` command is unrestricted; in production restrict to chat administrators.
- No rate limiting; yt-dlp may be throttled by YouTube with many requests.
- Could add caching of playlists to avoid re-fetching if the same playlist is added multiple times.

## License

This project is provided as-is for educational purposes.
