"""Integration tests for database operations."""

import pytest

from src.database import (
    SessionLimitReachedError,
    count_sessions_owned_by_user,
    create_playlist,
    create_videos_bulk,
    delete_all_playlists_in_session,
    delete_playlist_by_youtube_id,
    delete_session,
    get_or_create_session,
    get_or_create_user,
    get_playlists_for_session,
    get_video_sets_for_session,
    get_videos_by_youtube_ids,
    get_videos_for_playlist,
)
from src.intersection import compute_common_videos
from src.models import Playlist, Session, User

pytestmark = pytest.mark.asyncio


async def test_get_or_create_session(conn):
    session1 = await get_or_create_session(conn, chat_id=100, owner_telegram_id=1000)
    session2 = await get_or_create_session(conn, chat_id=100, owner_telegram_id=1000)

    assert isinstance(session1, Session)
    assert session1.id == session2.id
    assert session1.chat_id == 100


async def test_get_or_create_user(conn):
    session = await get_or_create_session(conn, chat_id=200, owner_telegram_id=1000)
    user1 = await get_or_create_user(conn, session.id, 1000, "alice")
    user2 = await get_or_create_user(conn, session.id, 1000, "alice2")

    assert isinstance(user1, User)
    assert user1.id == user2.id
    assert user1.username == "alice"


async def test_create_playlist(conn):
    session = await get_or_create_session(conn, chat_id=300, owner_telegram_id=12345)
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
    session = await get_or_create_session(conn, chat_id=400, owner_telegram_id=222)
    user = await get_or_create_user(conn, session.id, 222, None)
    playlist = await create_playlist(conn, session.id, user.id, "PL456", "Test", "url")

    await create_videos_bulk(
        conn,
        playlist.id,
        [
            {"youtube_video_id": "v1", "title": "Video 1", "url": "https://youtu.be/v1", "position": 1},
            {"youtube_video_id": "v2", "title": "Video 2", "url": "https://youtu.be/v2", "position": 2},
        ],
    )

    fetched = await get_videos_for_playlist(conn, playlist.id)
    assert [video.youtube_video_id for video in fetched] == ["v1", "v2"]


async def test_get_video_sets_for_session(conn):
    session = await get_or_create_session(conn, chat_id=500, owner_telegram_id=333)
    user = await get_or_create_user(conn, session.id, 333, None)
    playlist_one = await create_playlist(conn, session.id, user.id, "PL1", "P1", "url")
    playlist_two = await create_playlist(conn, session.id, user.id, "PL2", "P2", "url")

    await create_videos_bulk(
        conn,
        playlist_one.id,
        [
            {"youtube_video_id": "v1", "title": "V1", "url": "u1", "position": 1},
            {"youtube_video_id": "v2", "title": "V2", "url": "u2", "position": 2},
        ],
    )
    await create_videos_bulk(
        conn,
        playlist_two.id,
        [
            {"youtube_video_id": "v2", "title": "V2", "url": "u2", "position": 1},
            {"youtube_video_id": "v3", "title": "V3", "url": "u3", "position": 2},
        ],
    )

    sets = await get_video_sets_for_session(conn, session.id)
    assert {"v1", "v2"} in sets
    assert {"v2", "v3"} in sets


async def test_get_videos_by_youtube_ids(conn):
    session = await get_or_create_session(conn, chat_id=600, owner_telegram_id=444)
    user = await get_or_create_user(conn, session.id, 444, None)
    playlist = await create_playlist(conn, session.id, user.id, "PL", "T", "url")

    await create_videos_bulk(
        conn,
        playlist.id,
        [
            {"youtube_video_id": "a", "title": "A", "url": "ua", "position": 1},
            {"youtube_video_id": "b", "title": "B", "url": "ub", "position": 2},
        ],
    )

    videos = await get_videos_by_youtube_ids(conn, ["a"])
    assert len(videos) == 1
    assert videos[0].youtube_video_id == "a"


async def test_compute_common_videos(conn):
    session = await get_or_create_session(conn, chat_id=700, owner_telegram_id=555)
    user = await get_or_create_user(conn, session.id, 555, None)

    for playlist_id, videos in (
        ("PL1", ["v1", "v2"]),
        ("PL2", ["v2", "v3"]),
        ("PL3", ["v2", "v4"]),
    ):
        playlist = await create_playlist(conn, session.id, user.id, playlist_id, playlist_id, "url")
        await create_videos_bulk(
            conn,
            playlist.id,
            [
                {
                    "youtube_video_id": video_id,
                    "title": f"Video {video_id}",
                    "url": f"url-{video_id}",
                    "position": index,
                }
                for index, video_id in enumerate(videos, start=1)
            ],
        )

    common = await compute_common_videos(conn, session.id)
    assert [video.youtube_video_id for video in common] == ["v2"]


async def test_compute_common_videos_with_empty_playlist(conn):
    session = await get_or_create_session(conn, chat_id=750, owner_telegram_id=556)
    user = await get_or_create_user(conn, session.id, 556, None)

    playlist = await create_playlist(conn, session.id, user.id, "PL1", "Filled", "url")
    await create_videos_bulk(
        conn,
        playlist.id,
        [{"youtube_video_id": "v1", "title": "Video 1", "url": "url1", "position": 1}],
    )
    await create_playlist(conn, session.id, user.id, "PLEMPTY", "Empty", "url")

    common = await compute_common_videos(conn, session.id)
    assert common == []


async def test_delete_playlist_by_youtube_id(conn):
    session = await get_or_create_session(conn, chat_id=800, owner_telegram_id=777)
    user = await get_or_create_user(conn, session.id, 777, None)
    playlist = await create_playlist(conn, session.id, user.id, "PLDEL", "Delete me", "url")
    await create_videos_bulk(
        conn,
        playlist.id,
        [{"youtube_video_id": "v1", "title": "Video 1", "url": "url1", "position": 1}],
    )

    deleted = await delete_playlist_by_youtube_id(conn, session.id, "PLDEL")
    remaining_playlists = await get_playlists_for_session(conn, session.id)

    assert deleted == 1
    assert remaining_playlists == []


async def test_delete_all_playlists_in_session(conn):
    session = await get_or_create_session(conn, chat_id=900, owner_telegram_id=888)
    user = await get_or_create_user(conn, session.id, 888, None)
    await create_playlist(conn, session.id, user.id, "PL1", "Playlist 1", "url")
    await create_playlist(conn, session.id, user.id, "PL2", "Playlist 2", "url")

    deleted = await delete_all_playlists_in_session(conn, session.id)

    assert deleted == 2
    assert await get_playlists_for_session(conn, session.id) == []


async def test_delete_session_cascades(conn):
    session = await get_or_create_session(conn, chat_id=1000, owner_telegram_id=999)
    user = await get_or_create_user(conn, session.id, 999, None)
    playlist = await create_playlist(conn, session.id, user.id, "PLC", "Cascade", "url")
    await create_videos_bulk(
        conn,
        playlist.id,
        [{"youtube_video_id": "v1", "title": "Video 1", "url": "url1", "position": 1}],
    )

    deleted = await delete_session(conn, session.id)
    session_row = await conn.fetchrow("SELECT 1 FROM sessions WHERE id = $1", session.id)
    playlist_row = await conn.fetchrow("SELECT 1 FROM playlists WHERE session_id = $1", session.id)
    user_row = await conn.fetchrow("SELECT 1 FROM users WHERE session_id = $1", session.id)

    assert deleted is True
    assert session_row is None
    assert playlist_row is None
    assert user_row is None


async def test_session_limit_per_owner(conn):
    for chat_id in range(1100, 1105):
        await get_or_create_session(conn, chat_id=chat_id, owner_telegram_id=4242)

    assert await count_sessions_owned_by_user(conn, 4242) == 5

    with pytest.raises(SessionLimitReachedError):
        await get_or_create_session(conn, chat_id=1105, owner_telegram_id=4242)
