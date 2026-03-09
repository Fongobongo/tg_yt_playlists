"""Database layer using asyncpg."""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import List, Set

import asyncpg

from .models import Playlist, Session, User, Video

logger = logging.getLogger(__name__)

# SQL for table creation
CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id BIGINT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    telegram_id BIGINT NOT NULL,
    username TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(session_id, telegram_id)
);

CREATE TABLE IF NOT EXISTS playlists (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    youtube_playlist_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS videos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    playlist_id UUID NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    youtube_video_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    position INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_users_session_id ON users(session_id);
CREATE INDEX IF NOT EXISTS idx_playlists_session_id ON playlists(session_id);
CREATE INDEX IF NOT EXISTS idx_videos_playlist_id ON videos(playlist_id);
CREATE INDEX IF NOT EXISTS idx_videos_youtube_id ON videos(youtube_video_id);
"""


async def create_pool(database_url: str) -> asyncpg.Pool:
    """Create and return an asyncpg connection pool."""
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=10)
    logger.info("Database connection pool created")
    return pool


async def create_tables(pool: asyncpg.Pool) -> None:
    """Create all tables and indexes if they do not exist."""
    async with pool.acquire() as conn:
        await conn.execute(CREATE_TABLES_SQL)
        logger.info("Database tables ensured")


async def close_pool(pool: asyncpg.Pool) -> None:
    """Close the connection pool."""
    await pool.close()
    logger.info("Database connection pool closed")


# Session operations
async def get_session_by_chat_id(conn: asyncpg.Connection, chat_id: int) -> Session | None:
    row = await conn.fetchrow(
        "SELECT id, chat_id, created_at FROM sessions WHERE chat_id = $1", chat_id
    )
    if row:
        return Session(id=str(row["id"]), chat_id=row["chat_id"], created_at=row["created_at"])
    return None


async def create_session(conn: asyncpg.Connection, chat_id: int) -> Session:
    session_id = uuid.uuid4()
    created_at = datetime.utcnow()
    await conn.execute(
        "INSERT INTO sessions (id, chat_id, created_at) VALUES ($1, $2, $3)",
        session_id,
        chat_id,
        created_at,
    )
    return Session(id=str(session_id), chat_id=chat_id, created_at=created_at)


async def get_or_create_session(conn: asyncpg.Connection, chat_id: int) -> Session:
    session = await get_session_by_chat_id(conn, chat_id)
    if session:
        return session
    return await create_session(conn, chat_id)


# User operations
async def get_user_by_telegram_id(
    conn: asyncpg.Connection, session_id: str, telegram_id: int
) -> User | None:
    row = await conn.fetchrow(
        "SELECT id, session_id, telegram_id, username, created_at FROM users WHERE session_id = $1 AND telegram_id = $2",
        session_id,
        telegram_id,
    )
    if row:
        return User(
            id=str(row["id"]),
            session_id=str(row["session_id"]),
            telegram_id=row["telegram_id"],
            username=row["username"],
            created_at=row["created_at"],
        )
    return None


async def create_user(
    conn: asyncpg.Connection, session_id: str, telegram_id: int, username: str | None
) -> User:
    user_id = uuid.uuid4()
    created_at = datetime.utcnow()
    await conn.execute(
        "INSERT INTO users (id, session_id, telegram_id, username, created_at) VALUES ($1, $2, $3, $4, $5)",
        user_id,
        session_id,
        telegram_id,
        username,
        created_at,
    )
    return User(
        id=str(user_id),
        session_id=session_id,
        telegram_id=telegram_id,
        username=username,
        created_at=created_at,
    )


async def get_or_create_user(
    conn: asyncpg.Connection, session_id: str, telegram_id: int, username: str | None
) -> User:
    user = await get_user_by_telegram_id(conn, session_id, telegram_id)
    if user:
        return user
    return await create_user(conn, session_id, telegram_id, username)


# Playlist operations
async def create_playlist(
    conn: asyncpg.Connection,
    session_id: str,
    user_id: str,
    youtube_playlist_id: str,
    title: str,
    url: str,
) -> Playlist:
    playlist_id = uuid.uuid4()
    created_at = datetime.utcnow()
    await conn.execute(
        "INSERT INTO playlists (id, session_id, user_id, youtube_playlist_id, title, url, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7)",
        playlist_id,
        session_id,
        user_id,
        youtube_playlist_id,
        title,
        url,
        created_at,
    )
    return Playlist(
        id=str(playlist_id),
        session_id=session_id,
        user_id=user_id,
        youtube_playlist_id=youtube_playlist_id,
        title=title,
        url=url,
        created_at=created_at,
    )


async def get_playlists_for_session(
    conn: asyncpg.Connection, session_id: str
) -> List[Playlist]:
    rows = await conn.fetch(
        "SELECT id, session_id, user_id, youtube_playlist_id, title, url, created_at FROM playlists WHERE session_id = $1",
        session_id,
    )
    return [
        Playlist(
            id=str(row["id"]),
            session_id=str(row["session_id"]),
            user_id=str(row["user_id"]),
            youtube_playlist_id=row["youtube_playlist_id"],
            title=row["title"],
            url=row["url"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


# Video operations
async def create_videos_bulk(
    conn: asyncpg.Connection,
    playlist_id: str,
    videos: List[dict],
) -> None:
    """
    Bulk insert videos for a playlist.

    `videos` is a list of dict with keys: youtube_video_id, title, url, position.
    """
    values = []
    now = datetime.utcnow()
    for v in videos:
        video_id = uuid.uuid4()
        values.append(
            (
                video_id,
                playlist_id,
                v["youtube_video_id"],
                v["title"],
                v["url"],
                v["position"],
                now,
            )
        )
    # executemany
    await conn.executemany(
        "INSERT INTO videos (id, playlist_id, youtube_video_id, title, url, position, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7)",
        values,
    )


async def get_videos_for_playlist(
    conn: asyncpg.Connection, playlist_id: str
) -> List[Video]:
    rows = await conn.fetch(
        "SELECT id, playlist_id, youtube_video_id, title, url, position, created_at FROM videos WHERE playlist_id = $1 ORDER BY position",
        playlist_id,
    )
    return [
        Video(
            id=str(row["id"]),
            playlist_id=str(row["playlist_id"]),
            youtube_video_id=row["youtube_video_id"],
            title=row["title"],
            url=row["url"],
            position=row["position"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


async def get_video_sets_for_session(
    conn: asyncpg.Connection, session_id: str
) -> List[Set[str]]:
    """
    For the given session, return a list of sets of YouTube video IDs,
    one set per playlist in the session.
    """
    rows = await conn.fetch(
        """
        SELECT v.playlist_id, v.youtube_video_id
        FROM videos v
        JOIN playlists p ON v.playlist_id = p.id
        WHERE p.session_id = $1
        """,
        session_id,
    )
    sets = {}
    for row in rows:
        pid = str(row["playlist_id"])
        vid = row["youtube_video_id"]
        if pid not in sets:
            sets[pid] = set()
        sets[pid].add(vid)
    return list(sets.values())


async def get_videos_by_youtube_ids(
    conn: asyncpg.Connection, youtube_video_ids: List[str]
) -> List[Video]:
    """Return distinct Video entries for the given YouTube video IDs (any playlist occurrence)."""
    if not youtube_video_ids:
        return []
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (youtube_video_id) id, playlist_id, youtube_video_id, title, url, position, created_at
        FROM videos
        WHERE youtube_video_id = ANY($1)
        ORDER BY youtube_video_id, created_at ASC
        """,
        youtube_video_ids,
    )
    return [
        Video(
            id=str(row["id"]),
            playlist_id=str(row["playlist_id"]),
            youtube_video_id=row["youtube_video_id"],
            title=row["title"],
            url=row["url"],
            position=row["position"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


