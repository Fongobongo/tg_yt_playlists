"""Database layer using aiosqlite (SQLite)."""

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Set

import aiosqlite

from .models import Playlist, Session, User, Video

logger = logging.getLogger(__name__)

# SQL for table creation (SQLite)
CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    chat_id BIGINT NOT NULL UNIQUE,
    short_code TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    telegram_id BIGINT NOT NULL,
    username TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(session_id, telegram_id)
);

CREATE TABLE IF NOT EXISTS playlists (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    youtube_playlist_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    playlist_id TEXT NOT NULL,
    youtube_video_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    position INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_active_session (
    telegram_id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_users_session_id ON users(session_id);
CREATE INDEX IF NOT EXISTS idx_playlists_session_id ON playlists(session_id);
CREATE INDEX IF NOT EXISTS idx_videos_playlist_id ON videos(playlist_id);
CREATE INDEX IF NOT EXISTS idx_videos_youtube_id ON videos(youtube_video_id);
CREATE INDEX IF NOT EXISTS idx_sessions_short_code ON sessions(short_code);
CREATE INDEX IF NOT EXISTS idx_user_active_session_session_id ON user_active_session(session_id);
"""


class SQLitePool:
    """Simple pool-like wrapper for aiosqlite connections."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    @asynccontextmanager
    async def acquire(self):
        """Acquire a connection with Row factory set."""
        conn = await aiosqlite.connect(self.db_path)
        conn.row_factory = aiosqlite.Row
        try:
            yield conn
        finally:
            await conn.close()

    async def close(self):
        """No-op for SQLite; connections closed by context manager."""
        pass


async def create_pool(database_url: str) -> SQLitePool:
    """
    Create and return a SQLitePool.

    database_url format: sqlite:///path/to/file.db
    """
    if not database_url.startswith("sqlite:///"):
        raise ValueError("Only sqlite URLs are supported")
    db_path = database_url[len("sqlite:///"):]
    pool = SQLitePool(db_path)
    logger.info("SQLite pool created for %s", db_path)
    return pool


async def create_tables(pool: SQLitePool) -> None:
    """Create all tables and indexes if they do not exist."""
    async with pool.acquire() as conn:
        await conn.executescript(CREATE_TABLES_SQL)
        await conn.commit()
        logger.info("Database tables ensured")


async def close_pool(pool: SQLitePool) -> None:
    """Close the pool (no-op for SQLite)."""
    await pool.close()
    logger.info("Database pool closed")


# Helper to convert datetime to string for storage
def dt_to_str(dt: datetime) -> str:
    return dt.isoformat()


def str_to_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


# Session operations
async def get_session_by_chat_id(conn: aiosqlite.Connection, chat_id: int) -> Session | None:
    cursor = await conn.execute(
        "SELECT id, chat_id, short_code, created_at FROM sessions WHERE chat_id = ?",
        (chat_id,),
    )
    row = await cursor.fetchone()
    if row:
        return Session(
            id=str(row["id"]),
            chat_id=row["chat_id"],
            short_code=row["short_code"],
            created_at=str_to_dt(row["created_at"]),
        )
    return None


async def create_session(conn: aiosqlite.Connection, chat_id: int, short_code: str | None = None) -> Session:
    session_id = str(uuid.uuid4())
    now = dt_to_str(datetime.utcnow())
    if short_code is None:
        short_code = uuid.uuid4().hex
    await conn.execute(
        "INSERT INTO sessions (id, chat_id, short_code, created_at) VALUES (?, ?, ?, ?)",
        (session_id, chat_id, short_code, now),
    )
    return Session(
        id=session_id,
        chat_id=chat_id,
        short_code=short_code,
        created_at=datetime.utcnow(),
    )


async def get_or_create_session(conn: aiosqlite.Connection, chat_id: int) -> Session:
    session = await get_session_by_chat_id(conn, chat_id)
    if session:
        return session
    return await create_session(conn, chat_id)


# User operations
async def get_user_by_telegram_id(
    conn: aiosqlite.Connection, session_id: str, telegram_id: int
) -> User | None:
    cursor = await conn.execute(
        "SELECT id, session_id, telegram_id, username, created_at FROM users WHERE session_id = ? AND telegram_id = ?",
        (session_id, telegram_id),
    )
    row = await cursor.fetchone()
    if row:
        return User(
            id=str(row["id"]),
            session_id=str(row["session_id"]),
            telegram_id=row["telegram_id"],
            username=row["username"],
            created_at=str_to_dt(row["created_at"]),
        )
    return None


async def create_user(
    conn: aiosqlite.Connection, session_id: str, telegram_id: int, username: str | None
) -> User:
    user_id = str(uuid.uuid4())
    now = dt_to_str(datetime.utcnow())
    await conn.execute(
        "INSERT INTO users (id, session_id, telegram_id, username, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, session_id, telegram_id, username, now),
    )
    return User(
        id=user_id,
        session_id=session_id,
        telegram_id=telegram_id,
        username=username,
        created_at=datetime.utcnow(),
    )


async def get_or_create_user(
    conn: aiosqlite.Connection, session_id: str, telegram_id: int, username: str | None
) -> User:
    user = await get_user_by_telegram_id(conn, session_id, telegram_id)
    if user:
        return user
    return await create_user(conn, session_id, telegram_id, username)


# Playlist operations
async def create_playlist(
    conn: aiosqlite.Connection,
    session_id: str,
    user_id: str,
    youtube_playlist_id: str,
    title: str,
    url: str,
) -> Playlist:
    playlist_id = str(uuid.uuid4())
    now = dt_to_str(datetime.utcnow())
    await conn.execute(
        "INSERT INTO playlists (id, session_id, user_id, youtube_playlist_id, title, url, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (playlist_id, session_id, user_id, youtube_playlist_id, title, url, now),
    )
    return Playlist(
        id=playlist_id,
        session_id=session_id,
        user_id=user_id,
        youtube_playlist_id=youtube_playlist_id,
        title=title,
        url=url,
        created_at=datetime.utcnow(),
    )


async def get_playlists_for_session(
    conn: aiosqlite.Connection, session_id: str
) -> List[Playlist]:
    cursor = await conn.execute(
        "SELECT id, session_id, user_id, youtube_playlist_id, title, url, created_at FROM playlists WHERE session_id = ?",
        (session_id,),
    )
    rows = await cursor.fetchall()
    return [
        Playlist(
            id=str(row["id"]),
            session_id=str(row["session_id"]),
            user_id=str(row["user_id"]),
            youtube_playlist_id=row["youtube_playlist_id"],
            title=row["title"],
            url=row["url"],
            created_at=str_to_dt(row["created_at"]),
        )
        for row in rows
    ]


async def delete_all_playlists_in_session(
    conn: aiosqlite.Connection, session_id: str
) -> int:
    """
    Delete all playlists (and their videos) for the given session.
    Returns the number of playlists deleted.
    """
    # Delete videos first (cascade effect without foreign keys)
    await conn.execute(
        "DELETE FROM videos WHERE playlist_id IN (SELECT id FROM playlists WHERE session_id = ?)",
        (session_id,)
    )
    # Count and delete playlists
    cursor = await conn.execute(
        "SELECT COUNT(*) AS cnt FROM playlists WHERE session_id = ?", (session_id,)
    )
    row = await cursor.fetchone()
    count = row["cnt"] if row else 0
    await conn.execute("DELETE FROM playlists WHERE session_id = ?", (session_id,))
    return count


# Video operations
async def create_videos_bulk(
    conn: aiosqlite.Connection,
    playlist_id: str,
    videos: List[dict],
) -> None:
    """
    Bulk insert videos for a playlist.

    `videos` is a list of dict with keys: youtube_video_id, title, url, position.
    """
    now = dt_to_str(datetime.utcnow())
    await conn.executemany(
        "INSERT INTO videos (id, playlist_id, youtube_video_id, title, url, position, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (str(uuid.uuid4()), playlist_id, v["youtube_video_id"], v["title"], v["url"], v["position"], now)
            for v in videos
        ],
    )


async def get_videos_for_playlist(
    conn: aiosqlite.Connection, playlist_id: str
) -> List[Video]:
    cursor = await conn.execute(
        "SELECT id, playlist_id, youtube_video_id, title, url, position, created_at FROM videos WHERE playlist_id = ? ORDER BY position",
        (playlist_id,),
    )
    rows = await cursor.fetchall()
    return [
        Video(
            id=str(row["id"]),
            playlist_id=str(row["playlist_id"]),
            youtube_video_id=row["youtube_video_id"],
            title=row["title"],
            url=row["url"],
            position=row["position"],
            created_at=str_to_dt(row["created_at"]),
        )
        for row in rows
    ]


async def get_video_sets_for_session(
    conn: aiosqlite.Connection, session_id: str
) -> List[Set[str]]:
    """
    For the given session, return a list of sets of YouTube video IDs,
    one set per playlist in the session.
    """
    cursor = await conn.execute(
        """
        SELECT v.playlist_id, v.youtube_video_id
        FROM videos v
        JOIN playlists p ON v.playlist_id = p.id
        WHERE p.session_id = ?
        """,
        (session_id,),
    )
    rows = await cursor.fetchall()
    sets = {}
    for row in rows:
        pid = str(row["playlist_id"])
        vid = row["youtube_video_id"]
        if pid not in sets:
            sets[pid] = set()
        sets[pid].add(vid)
    return list(sets.values())


async def get_videos_by_youtube_ids(
    conn: aiosqlite.Connection, youtube_video_ids: List[str]
) -> List[Video]:
    """Return distinct Video entries for the given YouTube video IDs (any playlist occurrence)."""
    if not youtube_video_ids:
        return []
    placeholders = ",".join("?" for _ in youtube_video_ids)
    query = f"""
        SELECT DISTINCT youtube_video_id, id, playlist_id, title, url, position, created_at
        FROM videos
        WHERE youtube_video_id IN ({placeholders})
        ORDER BY youtube_video_id, created_at ASC
    """
    cursor = await conn.execute(query, youtube_video_ids)
    rows = await cursor.fetchall()
    # Need to group by youtube_video_id to get distinct. Since SQLite DISTINCT ON not supported, we'll do it manually:
    videos_map = {}
    for row in rows:
        vid_id = row["youtube_video_id"]
        if vid_id not in videos_map:
            videos_map[vid_id] = Video(
                id=str(row["id"]),
                playlist_id=str(row["playlist_id"]),
                youtube_video_id=row["youtube_video_id"],
                title=row["title"],
                url=row["url"],
                position=row["position"],
                created_at=str_to_dt(row["created_at"]),
            )
    return list(videos_map.values())


# Active session management
async def get_session_by_short_code(conn: aiosqlite.Connection, short_code: str) -> Session | None:
    cursor = await conn.execute(
        "SELECT id, chat_id, short_code, created_at FROM sessions WHERE short_code = ?",
        (short_code,),
    )
    row = await cursor.fetchone()
    if row:
        return Session(
            id=str(row["id"]),
            chat_id=row["chat_id"],
            short_code=row["short_code"],
            created_at=str_to_dt(row["created_at"]),
        )
    return None


async def get_active_session_for_user(conn: aiosqlite.Connection, telegram_id: int) -> Session | None:
    cursor = await conn.execute(
        """
        SELECT s.id, s.chat_id, s.short_code, s.created_at
        FROM user_active_session uas
        JOIN sessions s ON uas.session_id = s.id
        WHERE uas.telegram_id = ?
        """,
        (telegram_id,),
    )
    row = await cursor.fetchone()
    if row:
        return Session(
            id=str(row["id"]),
            chat_id=row["chat_id"],
            short_code=row["short_code"],
            created_at=str_to_dt(row["created_at"]),
        )
    return None


async def set_active_session_for_user(conn: aiosqlite.Connection, telegram_id: int, session_id: str) -> None:
    now = dt_to_str(datetime.utcnow())
    await conn.execute(
        """
        INSERT INTO user_active_session (telegram_id, session_id, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET session_id = excluded.session_id, updated_at = excluded.updated_at
        """,
        (telegram_id, session_id, now),
    )


async def clear_active_session_for_user(conn: aiosqlite.Connection, telegram_id: int) -> None:
    await conn.execute("DELETE FROM user_active_session WHERE telegram_id = ?", (telegram_id,))


async def compute_common_videos(conn: aiosqlite.Connection, session_id: str) -> List[Video]:
    """Compute a list of videos that appear in every playlist of the given session."""
    video_sets = await get_video_sets_for_session(conn, session_id)
    if not video_sets:
        return []
    common_ids = set.intersection(*video_sets)
    if not common_ids:
        return []
    return await get_videos_by_youtube_ids(conn, list(common_ids))


@asynccontextmanager
async def transaction(conn: aiosqlite.Connection):
    """Async context manager for database transactions."""
    await conn.execute("BEGIN")
    try:
        yield
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise
