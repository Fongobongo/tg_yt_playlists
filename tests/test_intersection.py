"""Tests for intersection logic across users."""

import pytest

from src.database import create_playlist, create_videos_bulk, get_or_create_session, get_or_create_user
from src.intersection import compute_common_videos

pytestmark = pytest.mark.asyncio


async def test_intersection_empty_session(conn):
    session = await get_or_create_session(conn, chat_id=801, owner_telegram_id=801)
    common = await compute_common_videos(conn, session.id)
    assert common == []


async def test_intersection_single_playlist(conn):
    session = await get_or_create_session(conn, chat_id=802, owner_telegram_id=802)
    user = await get_or_create_user(conn, session.id, 111, None)
    playlist = await create_playlist(conn, session.id, user.id, "PL1", "Playlist 1", "https://...")
    await create_videos_bulk(
        conn,
        playlist.id,
        [
            {"youtube_video_id": "v1", "title": "V1", "url": "u1", "position": 1},
            {"youtube_video_id": "v2", "title": "V2", "url": "u2", "position": 2},
        ],
    )

    common = await compute_common_videos(conn, session.id)
    assert {video.youtube_video_id for video in common} == {"v1", "v2"}


async def test_intersection_multiple_common(conn):
    session = await get_or_create_session(conn, chat_id=803, owner_telegram_id=803)
    user = await get_or_create_user(conn, session.id, 222, None)
    playlist_a = await create_playlist(conn, session.id, user.id, "PLA", "A", "urlA")
    playlist_b = await create_playlist(conn, session.id, user.id, "PLB", "B", "urlB")
    await create_videos_bulk(
        conn,
        playlist_a.id,
        [
            {"youtube_video_id": "v1", "title": "V1", "url": "u1", "position": 1},
            {"youtube_video_id": "v2", "title": "V2", "url": "u2", "position": 2},
        ],
    )
    await create_videos_bulk(
        conn,
        playlist_b.id,
        [
            {"youtube_video_id": "v2", "title": "V2", "url": "u2", "position": 1},
            {"youtube_video_id": "v3", "title": "V3", "url": "u3", "position": 2},
        ],
    )

    common = await compute_common_videos(conn, session.id)
    assert {video.youtube_video_id for video in common} == {"v1", "v2", "v3"}


async def test_intersection_none(conn):
    session = await get_or_create_session(conn, chat_id=804, owner_telegram_id=804)
    user = await get_or_create_user(conn, session.id, 333, None)

    for index, video_id in enumerate(("a", "b", "c"), start=1):
        playlist = await create_playlist(conn, session.id, user.id, f"PL{index}", f"P{index}", "url")
        await create_videos_bulk(
            conn,
            playlist.id,
            [{"youtube_video_id": video_id, "title": f"V{video_id}", "url": f"u{video_id}", "position": 1}],
        )

    common = await compute_common_videos(conn, session.id)
    assert {video.youtube_video_id for video in common} == {"a", "b", "c"}


async def test_intersection_across_users(conn):
    session = await get_or_create_session(conn, chat_id=805, owner_telegram_id=805)
    user_one = await get_or_create_user(conn, session.id, 444, None)
    user_two = await get_or_create_user(conn, session.id, 555, None)

    playlist_a = await create_playlist(conn, session.id, user_one.id, "PLA", "A", "urlA")
    playlist_b = await create_playlist(conn, session.id, user_one.id, "PLB", "B", "urlB")
    playlist_c = await create_playlist(conn, session.id, user_two.id, "PLC", "C", "urlC")

    await create_videos_bulk(
        conn,
        playlist_a.id,
        [
            {"youtube_video_id": "v1", "title": "V1", "url": "u1", "position": 1},
            {"youtube_video_id": "v2", "title": "V2", "url": "u2", "position": 2},
        ],
    )
    await create_videos_bulk(
        conn,
        playlist_b.id,
        [
            {"youtube_video_id": "v3", "title": "V3", "url": "u3", "position": 1},
        ],
    )
    await create_videos_bulk(
        conn,
        playlist_c.id,
        [
            {"youtube_video_id": "v2", "title": "V2", "url": "u2", "position": 1},
            {"youtube_video_id": "v3", "title": "V3", "url": "u3", "position": 2},
        ],
    )

    common = await compute_common_videos(conn, session.id)
    assert {video.youtube_video_id for video in common} == {"v2", "v3"}
