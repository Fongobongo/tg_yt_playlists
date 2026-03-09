"""Tests for database operations."""

import uuid
from datetime import datetime

import pytest

from src.database import (
    get_or_create_session,
    get_or_create_user,
    create_playlist,
    create_videos_bulk,
    get_playlists_for_session,
    get_video_sets_for_session,
    get_videos_by_youtube_ids,
    compute_common_videos,
)
from src.models import Session, User, Playlist, Video

pytestmark = pytest.mark.asyncio


async def test_get_or_create_session(conn):
    # First call creates
    session1 = await get_or_create_session(conn, chat_id=100)
    assert isinstance(session1, Session)
    assert session1.chat_id == 100
    assert session1.id is not None

    # Second call returns same
    session2 = await get_or_create_session(conn, chat_id=100)
    assert session2.id == session1.id


async def test_get_or_create_user(conn):
    session = await get_or_create_session(conn, chat_id=200)
    user1 = await get_or_create_user(conn, session_id=session.id, telegram_id=1000, username="alice")
    assert isinstance(user1, User)
    assert user1.telegram_id == 1000
    assert user1.username == "alice"
    assert user1.session_id == session.id

    user2 = await get_or_create_user(conn, session_id=session.id, telegram_id=1000, username="alice2")
    assert user2.id == user1.id
    assert user2.username == "alice"  # original username retained


async def test_create_playlist(conn):
    session = await get_or_create_session(conn, chat_id=300)
    user = await get_or_create_user(conn, session.id, 12345, None)
    playlist = await create_playlist(
        conn,
        session_id=session.id,
        user_id=user.id,
        youtube_playlist_id="PL123",
        title="My Playlist",
        url="https://www.youtube.com/playlist?list=PL123",
    )
    assert isinstance(playlist, Playlist)
    assert playlist.youtube_playlist_id == "PL123"
    assert playlist.title == "My Playlist"


async def test_create_and_get_videos(conn):
    session = await get_or_create_session(conn, chat_id=400)
    user = await get_or_create_user(conn, session.id, 222, None)
    playlist = await create_playlist(conn, session.id, user.id, "PL456", "Test", "url")
    videos_data = [
        {"youtube_video_id": "v1", "title": "Video 1", "url": "https://youtu.be/v1", "position": 1},
        {"youtube_video_id": "v2", "title": "Video 2", "url": "https://youtu.be/v2", "position": 2},
    ]
    await create_videos_bulk(conn, playlist.id, videos_data)

    fetched = await get_videos_for_playlist(conn, playlist.id)
    assert len(fetched) == 2
    assert fetched[0].youtube_video_id == "v1"
    assert fetched[1].youtube_video_id == "v2"


async def test_get_video_sets_for_session(conn):
    session = await get_or_create_session(conn, chat_id=500)
    user = await get_or_create_user(conn, session.id, 333, None)
    # Two playlists
    p1 = await create_playlist(conn, session.id, user.id, "PL1", "P1", "url")
    p2 = await create_playlist(conn, session.id, user.id, "PL2", "P2", "url")
    # Videos: p1 has v1, v2; p2 has v2, v3
    await create_videos_bulk(conn, p1.id, [
        {"youtube_video_id": "v1", "title": "V1", "url": "u1", "position": 1},
        {"youtube_video_id": "v2", "title": "V2", "url": "u2", "position": 2},
    ])
    await create_videos_bulk(conn, p2.id, [
        {"youtube_video_id": "v2", "title": "V2", "url": "u2", "position": 1},
        {"youtube_video_id": "v3", "title": "V3", "url": "u3", "position": 2},
    ])
    sets = await get_video_sets_for_session(conn, session.id)
    assert len(sets) == 2
    assert {"v1", "v2"} in sets
    assert {"v2", "v3"} in sets


async def test_get_videos_by_youtube_ids(conn):
    session = await get_or_create_session(conn, chat_id=600)
    user = await get_or_create_user(conn, session.id, 444, None)
    pl = await create_playlist(conn, session.id, user.id, "PL", "T", "url")
    await create_videos_bulk(conn, pl.id, [
        {"youtube_video_id": "a", "title": "A", "url": "ua", "position": 1},
        {"youtube_video_id": "b", "title": "B", "url": "ub", "position": 2},
    ])
    videos = await get_videos_by_youtube_ids(conn, ["a"])
    assert len(videos) == 1
    assert videos[0].youtube_video_id == "a"


async def test_compute_common_videos(conn):
    session = await get_or_create_session(conn, chat_id=700)
    user = await get_or_create_user(conn, session.id, 555, None)
    # Playlist 1: v1, v2
    p1 = await create_playlist(conn, session.id, user.id, "PL1", "P1", "url")
    await create_videos_bulk(conn, p1.id, [
        {"youtube_video_id": "v1", "title": "Video 1", "url": "url1", "position": 1},
        {"youtube_video_id": "v2", "title": "Video 2", "url": "url2", "position": 2},
    ])
    # Playlist 2: v2, v3
    p2 = await create_playlist(conn, session.id, user.id, "PL2", "P2", "url")
    await create_videos_bulk(conn, p2.id, [
        {"youtube_video_id": "v2", "title": "Video 2", "url": "url2", "position": 1},
        {"youtube_video_id": "v3", "title": "Video 3", "url": "url3", "position": 2},
    ])
    # Playlist 3: v2, v4
    p3 = await create_playlist(conn, session.id, user.id, "PL3", "P3", "url")
    await create_videos_bulk(conn, p3.id, [
        {"youtube_video_id": "v2", "title": "Video 2", "url": "url2", "position": 1},
        {"youtube_video_id": "v4", "title": "Video 4", "url": "url4", "position": 2},
    ])
    common = await compute_common_videos(conn, session.id)
    # Only v2 appears in all three playlists
    assert len(common) == 1
    assert common[0].youtube_video_id == "v2"

    # Add another playlist without v2 -> intersection empty
    p4 = await create_playlist(conn, session.id, user.id, "PL4", "P4", "url")
    await create_videos_bulk(conn, p4.id, [
        {"youtube_video_id": "v5", "title": "Video 5", "url": "url5", "position": 1},
    ])
    common2 = await compute_common_videos(conn, session.id)
    assert len(common2) == 0