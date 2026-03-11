"""Database layer for Supabase Postgres using asyncpg."""

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Sequence, Set
from urllib.parse import parse_qs, urlsplit

import asyncpg

from .models import Playlist, Session, User, Video

logger = logging.getLogger(__name__)


class SessionLimitReachedError(Exception):
    """Raised when a user tries to create more sessions than allowed."""

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    chat_id BIGINT NOT NULL UNIQUE,
    owner_telegram_id BIGINT,
    short_code TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    telegram_id BIGINT NOT NULL,
    username TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(session_id, telegram_id)
);

CREATE TABLE IF NOT EXISTS playlists (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    youtube_playlist_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    playlist_id TEXT NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    youtube_video_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    duration_text TEXT,
    position INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_active_session (
    telegram_id BIGINT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_session_id ON users(session_id);
CREATE INDEX IF NOT EXISTS idx_playlists_session_id ON playlists(session_id);
CREATE INDEX IF NOT EXISTS idx_playlists_youtube_playlist_id ON playlists(youtube_playlist_id);
CREATE INDEX IF NOT EXISTS idx_videos_playlist_id ON videos(playlist_id);
CREATE INDEX IF NOT EXISTS idx_videos_youtube_id ON videos(youtube_video_id);
CREATE INDEX IF NOT EXISTS idx_user_active_session_session_id ON user_active_session(session_id);
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS owner_telegram_id BIGINT;
CREATE INDEX IF NOT EXISTS idx_sessions_owner_telegram_id ON sessions(owner_telegram_id);
ALTER TABLE videos ADD COLUMN IF NOT EXISTS duration_text TEXT;
"""


def str_to_dt(value: datetime) -> datetime:
    """Normalize asyncpg timestamps to naive UTC datetimes used by the models."""
    return value.replace(tzinfo=None) if value.tzinfo else value


def _build_pool_kwargs(database_url: str) -> dict:
    parsed = urlsplit(database_url)
    query = parse_qs(parsed.query)
    pool_kwargs = {
        "dsn": database_url,
        "min_size": 1,
        "max_size": 10,
        "statement_cache_size": 0,
    }

    # Supabase requires SSL on direct connections. Leave explicit DSN settings untouched.
    has_ssl_setting = any(key in query for key in ("sslmode", "ssl"))
    if parsed.hostname and parsed.hostname.endswith(".supabase.co") and not has_ssl_setting:
        pool_kwargs["ssl"] = "require"

    return pool_kwargs


async def create_pool(database_url: str) -> asyncpg.Pool:
    """Create an asyncpg pool for a Postgres-compatible database."""
    if not database_url.startswith(("postgresql://", "postgres://")):
        raise ValueError("DATABASE_URL must be a PostgreSQL connection string")

    pool = await asyncpg.create_pool(**_build_pool_kwargs(database_url))
    logger.info("Postgres pool created for %s", urlsplit(database_url).hostname)
    return pool


async def create_tables(pool: asyncpg.Pool) -> None:
    """Create all tables and indexes if they do not exist."""
    async with pool.acquire() as conn:
        await conn.execute(CREATE_TABLES_SQL)
    logger.info("Database tables ensured")


async def close_pool(pool: asyncpg.Pool) -> None:
    """Close the database pool."""
    await pool.close()
    logger.info("Database pool closed")


async def get_session_by_chat_id(conn: asyncpg.Connection, chat_id: int) -> Session | None:
    row = await conn.fetchrow(
        "SELECT id, chat_id, short_code, created_at FROM sessions WHERE chat_id = $1",
        chat_id,
    )
    if row is None:
        return None
    return Session(
        id=row["id"],
        chat_id=row["chat_id"],
        short_code=row["short_code"],
        created_at=str_to_dt(row["created_at"]),
    )


async def get_session_owner_telegram_id(conn: asyncpg.Connection, session_id: str) -> int | None:
    """Return owner telegram ID for a session."""
    return await conn.fetchval(
        "SELECT owner_telegram_id FROM sessions WHERE id = $1",
        session_id,
    )


async def count_sessions_owned_by_user(conn: asyncpg.Connection, telegram_id: int) -> int:
    return await conn.fetchval(
        "SELECT COUNT(*) FROM sessions WHERE owner_telegram_id = $1",
        telegram_id,
    )


async def lock_session_quota_for_user(conn: asyncpg.Connection, telegram_id: int) -> None:
    """Serialize session creation checks per owner within the current transaction."""
    await conn.execute("SELECT pg_advisory_xact_lock($1::bigint)", telegram_id)


async def create_session(
    conn: asyncpg.Connection,
    chat_id: int,
    owner_telegram_id: int,
    short_code: str | None = None,
) -> Session:
    session_id = str(uuid.uuid4())
    short_code = short_code or uuid.uuid4().hex[:12]
    row = await conn.fetchrow(
        """
        INSERT INTO sessions (id, chat_id, owner_telegram_id, short_code)
        VALUES ($1, $2, $3, $4)
        RETURNING id, chat_id, short_code, created_at
        """,
        session_id,
        chat_id,
        owner_telegram_id,
        short_code,
    )
    return Session(
        id=row["id"],
        chat_id=row["chat_id"],
        short_code=row["short_code"],
        created_at=str_to_dt(row["created_at"]),
    )


async def get_or_create_session(
    conn: asyncpg.Connection, chat_id: int, owner_telegram_id: int
) -> Session:
    session = await get_session_by_chat_id(conn, chat_id)
    if session is not None:
        return session
    await lock_session_quota_for_user(conn, owner_telegram_id)
    session = await get_session_by_chat_id(conn, chat_id)
    if session is not None:
        return session
    if await count_sessions_owned_by_user(conn, owner_telegram_id) >= 5:
        raise SessionLimitReachedError("Session creation limit reached")
    return await create_session(conn, chat_id, owner_telegram_id)


async def get_user_by_telegram_id(
    conn: asyncpg.Connection, session_id: str, telegram_id: int
) -> User | None:
    row = await conn.fetchrow(
        """
        SELECT id, session_id, telegram_id, username, created_at
        FROM users
        WHERE session_id = $1 AND telegram_id = $2
        """,
        session_id,
        telegram_id,
    )
    if row is None:
        return None
    return User(
        id=row["id"],
        session_id=row["session_id"],
        telegram_id=row["telegram_id"],
        username=row["username"],
        created_at=str_to_dt(row["created_at"]),
    )


async def create_user(
    conn: asyncpg.Connection, session_id: str, telegram_id: int, username: str | None
) -> User:
    user_id = str(uuid.uuid4())
    row = await conn.fetchrow(
        """
        INSERT INTO users (id, session_id, telegram_id, username)
        VALUES ($1, $2, $3, $4)
        RETURNING id, session_id, telegram_id, username, created_at
        """,
        user_id,
        session_id,
        telegram_id,
        username,
    )
    return User(
        id=row["id"],
        session_id=row["session_id"],
        telegram_id=row["telegram_id"],
        username=row["username"],
        created_at=str_to_dt(row["created_at"]),
    )


async def get_or_create_user(
    conn: asyncpg.Connection, session_id: str, telegram_id: int, username: str | None
) -> User:
    user = await get_user_by_telegram_id(conn, session_id, telegram_id)
    if user is not None:
        return user
    return await create_user(conn, session_id, telegram_id, username)


async def create_playlist(
    conn: asyncpg.Connection,
    session_id: str,
    user_id: str,
    youtube_playlist_id: str,
    title: str,
    url: str,
) -> Playlist:
    playlist_id = str(uuid.uuid4())
    row = await conn.fetchrow(
        """
        INSERT INTO playlists (id, session_id, user_id, youtube_playlist_id, title, url)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, session_id, user_id, youtube_playlist_id, title, url, created_at
        """,
        playlist_id,
        session_id,
        user_id,
        youtube_playlist_id,
        title,
        url,
    )
    return Playlist(
        id=row["id"],
        session_id=row["session_id"],
        user_id=row["user_id"],
        youtube_playlist_id=row["youtube_playlist_id"],
        title=row["title"],
        url=row["url"],
        created_at=str_to_dt(row["created_at"]),
    )


async def get_playlists_for_session(conn: asyncpg.Connection, session_id: str) -> List[Playlist]:
    rows = await conn.fetch(
        """
        SELECT id, session_id, user_id, youtube_playlist_id, title, url, created_at
        FROM playlists
        WHERE session_id = $1
        ORDER BY created_at ASC
        """,
        session_id,
    )
    return [
        Playlist(
            id=row["id"],
            session_id=row["session_id"],
            user_id=row["user_id"],
            youtube_playlist_id=row["youtube_playlist_id"],
            title=row["title"],
            url=row["url"],
            created_at=str_to_dt(row["created_at"]),
        )
        for row in rows
    ]


async def get_playlists_for_user_in_session(
    conn: asyncpg.Connection, session_id: str, telegram_id: int
) -> List[Playlist]:
    rows = await conn.fetch(
        """
        SELECT
            p.id,
            p.session_id,
            p.user_id,
            p.youtube_playlist_id,
            p.title,
            p.url,
            p.created_at,
            COUNT(v.id) AS video_count
        FROM playlists p
        JOIN users u ON u.id = p.user_id
        LEFT JOIN videos v ON v.playlist_id = p.id
        WHERE p.session_id = $1 AND u.telegram_id = $2
        GROUP BY p.id, p.session_id, p.user_id, p.youtube_playlist_id, p.title, p.url, p.created_at
        ORDER BY p.created_at ASC
        """,
        session_id,
        telegram_id,
    )
    return [
        Playlist(
            id=row["id"],
            session_id=row["session_id"],
            user_id=row["user_id"],
            youtube_playlist_id=row["youtube_playlist_id"],
            title=row["title"],
            url=row["url"],
            created_at=str_to_dt(row["created_at"]),
            video_count=row["video_count"],
        )
        for row in rows
    ]


async def delete_all_playlists_in_session(conn: asyncpg.Connection, session_id: str) -> int:
    rows = await conn.fetch(
        "DELETE FROM playlists WHERE session_id = $1 RETURNING id",
        session_id,
    )
    return len(rows)


async def delete_playlist_by_youtube_id(
    conn: asyncpg.Connection, session_id: str, youtube_playlist_id: str
) -> int:
    rows = await conn.fetch(
        """
        DELETE FROM playlists
        WHERE session_id = $1 AND youtube_playlist_id = $2
        RETURNING id
        """,
        session_id,
        youtube_playlist_id,
    )
    return len(rows)


async def delete_session(conn: asyncpg.Connection, session_id: str) -> bool:
    row = await conn.fetchrow(
        "DELETE FROM sessions WHERE id = $1 RETURNING id",
        session_id,
    )
    return row is not None


async def create_videos_bulk(
    conn: asyncpg.Connection,
    playlist_id: str,
    videos: Sequence[dict],
) -> None:
    records = [
        (
            str(uuid.uuid4()),
            playlist_id,
            video["youtube_video_id"],
            video["title"],
            video["url"],
            video.get("duration_text"),
            video["position"],
        )
        for video in videos
    ]
    if not records:
        return
    await conn.executemany(
        """
        INSERT INTO videos (id, playlist_id, youtube_video_id, title, url, duration_text, position)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        records,
    )


async def get_videos_for_playlist(conn: asyncpg.Connection, playlist_id: str) -> List[Video]:
    rows = await conn.fetch(
        """
        SELECT id, playlist_id, youtube_video_id, title, url, duration_text, position, created_at
        FROM videos
        WHERE playlist_id = $1
        ORDER BY position ASC
        """,
        playlist_id,
    )
    return [
        Video(
            id=row["id"],
            playlist_id=row["playlist_id"],
            youtube_video_id=row["youtube_video_id"],
            title=row["title"],
            url=row["url"],
            position=row["position"],
            created_at=str_to_dt(row["created_at"]),
            duration_text=row["duration_text"],
        )
        for row in rows
    ]


async def get_video_sets_for_session(conn: asyncpg.Connection, session_id: str) -> List[Set[str]]:
    """Return one deduplicated video-id set per user who has at least one playlist in the session."""
    rows = await conn.fetch(
        """
        SELECT u.id AS user_id, p.id AS playlist_id, v.youtube_video_id
        FROM users u
        JOIN playlists p ON p.user_id = u.id
        LEFT JOIN videos v ON v.playlist_id = p.id
        WHERE u.session_id = $1
        """,
        session_id,
    )
    sets_by_user: dict[str, Set[str]] = {}
    for row in rows:
        user_id = row["user_id"]
        sets_by_user.setdefault(user_id, set())
        if row["youtube_video_id"] is not None:
            sets_by_user[user_id].add(row["youtube_video_id"])
    return list(sets_by_user.values())


async def get_videos_by_youtube_ids(
    conn: asyncpg.Connection, youtube_video_ids: Sequence[str]
) -> List[Video]:
    if not youtube_video_ids:
        return []
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (youtube_video_id)
            id, playlist_id, youtube_video_id, title, url, duration_text, position, created_at
        FROM videos
        WHERE youtube_video_id = ANY($1::text[])
        ORDER BY youtube_video_id, created_at ASC
        """,
        list(youtube_video_ids),
    )
    return [
        Video(
            id=row["id"],
            playlist_id=row["playlist_id"],
            youtube_video_id=row["youtube_video_id"],
            title=row["title"],
            url=row["url"],
            position=row["position"],
            created_at=str_to_dt(row["created_at"]),
            duration_text=row["duration_text"],
        )
        for row in rows
    ]


async def get_session_by_short_code(conn: asyncpg.Connection, short_code: str) -> Session | None:
    row = await conn.fetchrow(
        "SELECT id, chat_id, short_code, created_at FROM sessions WHERE short_code = $1",
        short_code,
    )
    if row is None:
        return None
    return Session(
        id=row["id"],
        chat_id=row["chat_id"],
        short_code=row["short_code"],
        created_at=str_to_dt(row["created_at"]),
    )


async def get_active_session_for_user(conn: asyncpg.Connection, telegram_id: int) -> Session | None:
    row = await conn.fetchrow(
        """
        SELECT s.id, s.chat_id, s.short_code, s.created_at
        FROM user_active_session uas
        JOIN sessions s ON s.id = uas.session_id
        WHERE uas.telegram_id = $1
        """,
        telegram_id,
    )
    if row is None:
        return None
    return Session(
        id=row["id"],
        chat_id=row["chat_id"],
        short_code=row["short_code"],
        created_at=str_to_dt(row["created_at"]),
    )


async def set_active_session_for_user(conn: asyncpg.Connection, telegram_id: int, session_id: str) -> None:
    await conn.execute(
        """
        INSERT INTO user_active_session (telegram_id, session_id, updated_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (telegram_id)
        DO UPDATE SET session_id = EXCLUDED.session_id, updated_at = NOW()
        """,
        telegram_id,
        session_id,
    )


async def clear_active_session_for_user(conn: asyncpg.Connection, telegram_id: int) -> None:
    await conn.execute(
        "DELETE FROM user_active_session WHERE telegram_id = $1",
        telegram_id,
    )


async def remove_user_from_session(conn: asyncpg.Connection, session_id: str, telegram_id: int) -> bool:
    """Remove a user from a session, cascading their playlists and videos."""
    row = await conn.fetchrow(
        """
        DELETE FROM users
        WHERE session_id = $1 AND telegram_id = $2
        RETURNING id
        """,
        session_id,
        telegram_id,
    )
    return row is not None


async def get_sessions_for_user(conn: asyncpg.Connection, telegram_id: int) -> List[Session]:
    rows = await conn.fetch(
        """
        SELECT DISTINCT s.id, s.chat_id, s.short_code, s.created_at
        FROM sessions s
        JOIN users u ON u.session_id = s.id
        WHERE u.telegram_id = $1
        ORDER BY s.created_at DESC
        """,
        telegram_id,
    )
    return [
        Session(
            id=row["id"],
            chat_id=row["chat_id"],
            short_code=row["short_code"],
            created_at=str_to_dt(row["created_at"]),
        )
        for row in rows
    ]


async def get_session_user_stats(conn: asyncpg.Connection, session_id: str) -> List[dict]:
    rows = await conn.fetch(
        """
        SELECT
            u.telegram_id,
            u.username,
            COUNT(p.id) AS playlist_count
        FROM users u
        LEFT JOIN playlists p ON p.user_id = u.id
        WHERE u.session_id = $1
        GROUP BY u.telegram_id, u.username, u.created_at
        ORDER BY u.created_at ASC
        """,
        session_id,
    )
    return [
        {
            "telegram_id": row["telegram_id"],
            "username": row["username"],
            "playlist_count": row["playlist_count"],
        }
        for row in rows
    ]


async def get_common_video_count(conn: asyncpg.Connection, session_id: str) -> int:
    video_sets = await get_video_sets_for_session(conn, session_id)
    if not video_sets:
        return 0
    return len(set.intersection(*video_sets))


async def user_is_member_of_session(conn: asyncpg.Connection, telegram_id: int, session_id: str) -> bool:
    row = await conn.fetchrow(
        """
        SELECT 1
        FROM users
        WHERE session_id = $1 AND telegram_id = $2
        LIMIT 1
        """,
        session_id,
        telegram_id,
    )
    return row is not None


@asynccontextmanager
async def transaction(conn: asyncpg.Connection):
    """Async context manager for database transactions."""
    tx = conn.transaction()
    await tx.start()
    try:
        yield
    except Exception:
        await tx.rollback()
        raise
    else:
        await tx.commit()
