"""Tests for bot handlers."""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import re

import pytest

from src.bot import extract_playlist_url, handle_playlist_url, cmd_start

pytestmark = pytest.mark.asyncio


def test_extract_playlist_url():
    assert extract_playlist_url("https://www.youtube.com/playlist?list=PL123") == "https://www.youtube.com/playlist?list=PL123"
    assert extract_playlist_url("http://youtube.com/playlist?list=PL456&feature=share") == "https://www.youtube.com/playlist?list=PL456"
    assert extract_playlist_url("Check this: www.youtube.com/playlist?list=PL789") == "https://www.youtube.com/playlist?list=PL789"
    assert extract_playlist_url("Just a normal message") is None
    assert extract_playlist_url("") is None


async def test_handle_playlist_url(mock_bot):
    # Create a mock message with a playlist URL
    msg = MagicMock()
    msg.text = "Here: https://www.youtube.com/playlist?list=PLABC"
    msg.chat = MagicMock()
    msg.chat.id = 12345
    msg.from_user = MagicMock()
    msg.from_user.id = 999
    msg.from_user.username = "tester"
    msg.reply = AsyncMock()

    bot = mock_bot
    # Prepare a dummy DB pool acquire that yields a dummy connection
    class DummyConn:
        pass

    class DummyACM:
        async def __aenter__(self):
            return DummyConn()
        async def __aexit__(self, exc_type, exc, tb):
            return False

    bot["db_pool"] = MagicMock()
    bot["db_pool"].acquire = lambda: DummyACM()

    # Mock database functions and youtube fetch
    mock_session = MagicMock(id="session1")
    mock_user = MagicMock(id="user1")
    mock_playlist = MagicMock(id="playlist1")
    mock_common = [
        MagicMock(youtube_video_id="v1", title="Video 1", url="https://youtu.be/v1"),
        MagicMock(youtube_video_id="v2", title="Video 2", url="https://youtu.be/v2"),
    ]

    with patch("src.bot.get_or_create_session", return_value=mock_session) as m_session, \
         patch("src.bot.get_or_create_user", return_value=mock_user) as m_user, \
         patch("src.bot.create_playlist", return_value=mock_playlist) as m_pl, \
         patch("src.bot.create_videos_bulk") as m_videos, \
         patch("src.bot.compute_common_videos", return_value=mock_common) as m_common, \
         patch("src.bot.fetch_playlist_info") as m_fetch:

        m_fetch.return_value = {
            "youtube_playlist_id": "PLABC",
            "title": "Test Playlist",
            "url": "https://www.youtube.com/playlist?list=PLABC",
            "videos": [
                {"youtube_video_id": "v1", "title": "Video 1", "url": "u1", "position": 1},
            ],
        }

        await handle_playlist_url(msg, bot)

    # Assertions
    m_session.assert_awaited_once()
    m_user.assert_awaited_once()
    m_pl.assert_awaited_once()
    m_videos.assert_awaited_once()
    m_common.assert_awaited_once()
    m_fetch.assert_awaited_once()
    msg.reply.assert_awaited_once()
    reply_text = msg.reply.call_args[0][0]
    assert "Common videos in this session:" in reply_text
    assert "Video 1" in reply_text
    assert "Video 2" in reply_text
    assert "https://youtu.be/v1" in reply_text
    assert "https://youtu.be/v2" in reply_text


async def test_cmd_start(mock_bot):
    bot = mock_bot
    bot["db_pool"] = MagicMock()

    class DummyConn:
        pass

    class DummyACM:
        async def __aenter__(self):
            return DummyConn()
        async def __aexit__(self, exc_type, exc, tb):
            return False

    bot["db_pool"].acquire = lambda: DummyACM()

    msg = MagicMock()
    msg.chat = MagicMock()
    msg.chat.id = 123
    msg.reply = AsyncMock()

    with patch("src.bot.get_or_create_session", return_value=MagicMock(id="s1", chat_id=123)) as m_session:
        await cmd_start(msg, bot)

    m_session.assert_awaited_once()
    msg.reply.assert_awaited_once()
    reply_text = msg.reply.call_args[0][0]
    assert "Hello!" in reply_text or "YouTube" in reply_text