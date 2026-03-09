"""Tests for intersection logic."""

import pytest

from src.intersection import compute_common_videos

pytestmark = pytest.mark.asyncio


async def test_intersection_empty_session(conn):
    """Session with no playlists returns empty list."""
    session = await conn.fetchrow(
        "INSERT INTO sessions (id, chat_id) VALUES (gen_random_uuid(), $1) RETURNING id",
        800,
    )
    common = await compute_common_videos(conn, str(session["id"]))
    assert common == []


async def test_intersection_single_playlist(conn):
    """With one playlist, all its videos are common."""
    session = await conn.fetchrow(
        "INSERT INTO sessions (id, chat_id) VALUES (gen_random_uuid(), $1) RETURNING id",
        801,
    )
    user = await conn.fetchrow(
        "INSERT INTO users (id, session_id, telegram_id) VALUES (gen_random_uuid(), $1, $2) RETURNING id",
        session["id"],
        111,
    )
    playlist = await conn.fetchrow(
        "INSERT INTO playlists (id, session_id, user_id, youtube_playlist_id, title, url) "
        "VALUES (gen_random_uuid(), $1, $2, $3, $4, $5) RETURNING id",
        session["id"],
        user["id"],
        "PL1",
        "Playlist 1",
        "https://...",
    )
    await conn.executemany(
        "INSERT INTO videos (id, playlist_id, youtube_video_id, title, url, position) "
        "VALUES (gen_random_uuid(), $1, $2, $3, $4, $5)",
        [
            (playlist["id"], "v1", "V1", "u1", 1),
            (playlist["id"], "v2", "V2", "u2", 2),
        ],
    )
    common = await compute_common_videos(conn, str(session["id"]))
    assert len(common) == 2
    ids = {v.youtube_video_id for v in common}
    assert ids == {"v1", "v2"}


async def test_intersection_multiple_common(conn):
    """Two playlists with some overlap."""
    session = await conn.fetchrow(
        "INSERT INTO sessions (id, chat_id) VALUES (gen_random_uuid(), $1) RETURNING id",
        802,
    )
    user = await conn.fetchrow(
        "INSERT INTO users (id, session_id, telegram_id) VALUES (gen_random_uuid(), $1, $2) RETURNING id",
        session["id"],
        222,
    )
    # Playlist A: v1, v2
    pA = await conn.fetchrow(
        "INSERT INTO playlists (id, session_id, user_id, youtube_playlist_id, title, url) "
        "VALUES (gen_random_uuid(), $1, $2, $3, $4, $5) RETURNING id",
        session["id"],
        user["id"],
        "PLA",
        "A",
        "urlA",
    )
    await conn.executemany(
        "INSERT INTO videos (id, playlist_id, youtube_video_id, title, url, position) "
        "VALUES (gen_random_uuid(), $1, $2, $3, $4, $5)",
        [
            (pA["id"], "v1", "V1", "u1", 1),
            (pA["id"], "v2", "V2", "u2", 2),
        ],
    )
    # Playlist B: v2, v3
    pB = await conn.fetchrow(
        "INSERT INTO playlists (id, session_id, user_id, youtube_playlist_id, title, url) "
        "VALUES (gen_random_uuid(), $1, $2, $3, $4, $5) RETURNING id",
        session["id"],
        user["id"],
        "PLB",
        "B",
        "urlB",
    )
    await conn.executemany(
        "INSERT INTO videos (id, playlist_id, youtube_video_id, title, url, position) "
        "Values (gen_random_uuid(), $1, $2, $3, $4, $5)",
        [
            (pB["id"], "v2", "V2", "u2", 1),
            (pB["id"], "v3", "V3", "u3", 2),
        ],
    )
    common = await compute_common_videos(conn, str(session["id"]))
    assert len(common) == 1
    assert common[0].youtube_video_id == "v2"


async def test_intersection_none(conn):
    """Three playlists with no common video."""
    session = await conn.fetchrow(
        "INSERT INTO sessions (id, chat_id) VALUES (gen_random_uuid(), $1) RETURNING id",
        803,
    )
    user = await conn.fetchrow(
        "INSERT INTO users (id, session_id, telegram_id) VALUES (gen_random_uuid(), $1, $2) RETURNING id",
        session["id"],
        333,
    )
    # Each playlist has distinct videos
    for i, vids in enumerate([["a"], ["b"], ["c"]]):
        pl = await conn.fetchrow(
            "INSERT INTO playlists (id, session_id, user_id, youtube_playlist_id, title, url) "
            "Values (gen_random_uuid(), $1, $2, $3, $4, $5) RETURNING id",
            session["id"],
            user["id"],
            f"PL{i}",
            f"P{i}",
            "url",
        )
        await conn.executemany(
            "INSERT INTO videos (id, playlist_id, youtube_video_id, title, url, position) "
            "Values (gen_random_uuid(), $1, $2, $3, $4, $5)",
            [(pl["id"], v, f"V{v}", f"u{v}", 1) for v in vids],
        )
    common = await compute_common_videos(conn, str(session["id"]))
    assert common == []