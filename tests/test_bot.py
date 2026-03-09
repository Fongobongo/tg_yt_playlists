"""Tests for bot handlers."""

import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import re

import pytest

from src.bot import (
    extract_playlist_url,
    handle_playlist_url,
    cmd_start,
    cmd_session,
    cmd_playlists,
    cmd_clear_playlists,
    cmd_delete_playlist,
    cmd_clear,
    cmd_leave,
)

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
    msg.chat.type = "group"  # not private => group branch
    msg.from_user = MagicMock()
    msg.from_user.id = 999
    msg.from_user.username = "tester"
    msg.reply = AsyncMock()

    bot = mock_bot
    # Prepare a dummy DB pool acquire that yields a dummy connection
    class DummyConn:
        async def transaction(self):
            # Return an async context manager that yields self
            return self
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False

    class DummyACM:
        async def __aenter__(self):
            return DummyConn()
        async def __aexit__(self, exc_type, exc, tb):
            return False

    bot.db_pool = MagicMock()
    bot.db_pool.acquire = lambda: DummyACM()

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

    class DummyConn:
        pass

    class DummyACM:
        async def __aenter__(self):
            return DummyConn()
        async def __aexit__(self, exc_type, exc, tb):
            return False

    bot.db_pool = MagicMock()
    bot.db_pool.acquire = lambda: DummyACM()

    msg = MagicMock()
    msg.chat = MagicMock()
    msg.chat.id = 123
    msg.chat.type = "group"  # group chat, no active session
    msg.from_user = MagicMock(id=111, username="user")
    msg.reply = AsyncMock()

    mock_session = MagicMock(id="s1", chat_id=123, short_code="abc123")
    mock_user = MagicMock(id="u1")

    with patch("src.bot.get_or_create_session", return_value=mock_session) as m_session, \
         patch("src.bot.get_or_create_user", return_value=mock_user) as m_user:
        await cmd_start(msg, bot)

    m_session.assert_awaited_once()
    m_user.assert_awaited_once()
    msg.reply.assert_awaited_once()
    reply_text = msg.reply.call_args[0][0]
    assert "Hello!" in reply_text or "YouTube" in reply_text
    assert "/session" in reply_text  # includes new command


async def test_cmd_playlists(mock_bot):
    bot = mock_bot

    class DummyConn:
        pass

    class DummyConnWithAcquire:
        def __init__(self, conn):
            self.conn = conn
        async def __aenter__(self):
            return self.conn
        async def __aexit__(self, exc_type, exc, tb):
            return False

    bot.db_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.fetchrow = AsyncMock(return_value={"id": "sess123"})
    bot.db_pool.acquire = lambda: DummyConnWithAcquire(mock_conn)

    msg = MagicMock()
    msg.chat = MagicMock()
    msg.chat.id = 123
    msg.reply = AsyncMock()

    mock_playlists = [
        MagicMock(title="Playlist A", youtube_playlist_id="PL_A", url="https://youtube.com/playlist?list=PL_A"),
        MagicMock(title="Playlist B", youtube_playlist_id="PL_B", url="https://youtube.com/playlist?list=PL_B"),
    ]

    with patch("src.bot.get_playlists_for_session", return_value=mock_playlists):
        await cmd_playlists(msg, bot)

    msg.reply.assert_awaited_once()
    reply_text = msg.reply.call_args[0][0]
    assert "Playlists in this session:" in reply_text
    assert "Playlist A" in reply_text
    assert "PL_A" in reply_text
    assert "Playlist B" in reply_text


async def test_cmd_clear_playlists_success(mock_bot):
    bot = mock_bot

    class DummyConnWithAcquire:
        def __init__(self, conn):
            self.conn = conn
        async def __aenter__(self):
            return self.conn
        async def __aexit__(self, exc_type, exc, tb):
            return False

    bot.db_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.fetchrow = AsyncMock(return_value={"id": "sess123"})
    mock_conn.execute = AsyncMock(return_value="DELETE 2")
    bot.db_pool.acquire = lambda: DummyConnWithAcquire(mock_conn)

    msg = MagicMock()
    msg.chat = MagicMock()
    msg.chat.id = 123
    msg.reply = AsyncMock()

    with patch("src.bot.delete_all_playlists_in_session", return_value=2) as m_delete:
        await cmd_clear_playlists(msg, bot)

    m_delete.assert_awaited_once()
    # Check that we passed the session_id to delete_all_playlists_in_session
    call_args = m_delete.call_args[0]
    assert call_args[1] == "sess123"  # second arg is session_id
    msg.reply.assert_awaited_once()
    reply_text = msg.reply.call_args[0][0]
    assert "Deleted 2 playlist(s) from this session." in reply_text


async def test_cmd_clear_playlists_no_session(mock_bot):
    bot = mock_bot

    class DummyConnWithAcquire:
        def __init__(self, conn):
            self.conn = conn
        async def __aenter__(self):
            return self.conn
        async def __aexit__(self, exc_type, exc, tb):
            return False

    bot.db_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.fetchrow = AsyncMock(return_value=None)  # No session
    bot.db_pool.acquire = lambda: DummyConnWithAcquire(mock_conn)

    msg = MagicMock()
    msg.chat = MagicMock()
    msg.chat.id = 123
    msg.reply = AsyncMock()

    await cmd_clear_playlists(msg, bot)

    msg.reply.assert_awaited_once()
    reply_text = msg.reply.call_args[0][0]
    assert "No session found." in reply_text


async def test_cmd_delete_playlist_success(mock_bot):
    bot = mock_bot

    class DummyConn:
        pass

    class DummyConnWithAcquire:
        def __init__(self, conn):
            self.conn = conn
        async def __aenter__(self):
            return self.conn
        async def __aexit__(self, exc_type, exc, tb):
            return False

    bot.db_pool = MagicMock()
    mock_conn = MagicMock()
    # session exists
    mock_conn.fetchrow = AsyncMock(return_value={"id": "sess123"})
    # execute returns "DELETE 1"
    mock_conn.execute = AsyncMock(return_value="DELETE 1")
    bot.db_pool.acquire = lambda: DummyConnWithAcquire(mock_conn)

    msg = MagicMock()
    msg.chat = MagicMock()
    msg.chat.id = 123
    msg.text = "/delete PL_TO_DELETE"
    msg.reply = AsyncMock()

    await cmd_delete_playlist(msg, bot)

    mock_conn.execute.assert_awaited_once()
    # Check the query args
    call_args = mock_conn.execute.call_args[0]
    assert "DELETE FROM playlists WHERE session_id = $1 AND youtube_playlist_id = $2" in call_args[0]
    assert call_args[1] == "sess123"
    assert call_args[2] == "PL_TO_DELETE"
    msg.reply.assert_awaited_once()
    reply_text = msg.reply.call_args[0][0]
    assert "Deleted 1 playlist(s) with YouTube ID 'PL_TO_DELETE'" in reply_text


async def test_cmd_delete_playlist_not_found(mock_bot):
    bot = mock_bot

    class DummyConn:
        pass

    class DummyConnWithAcquire:
        def __init__(self, conn):
            self.conn = conn
        async def __aenter__(self):
            return self.conn
        async def __aexit__(self, exc_type, exc, tb):
            return False

    bot.db_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.fetchrow = AsyncMock(return_value={"id": "sess123"})
    mock_conn.execute = AsyncMock(return_value="DELETE 0")
    bot.db_pool.acquire = lambda: DummyConnWithAcquire(mock_conn)

    msg = MagicMock()
    msg.chat = MagicMock()
    msg.chat.id = 123
    msg.text = "/delete UNKNOWN"
    msg.reply = AsyncMock()

    await cmd_delete_playlist(msg, bot)

    msg.reply.assert_awaited_once()
    reply_text = msg.reply.call_args[0][0]
    assert "No playlist with YouTube ID 'UNKNOWN' found" in reply_text


class DummyConnWithAcquire:
    def __init__(self, conn):
        self.conn = conn
    async def __aenter__(self):
        return self.conn
    async def __aexit__(self, exc_type, exc, tb):
        return False


async def test_cmd_session_group(mock_bot):
    bot = mock_bot
    bot.db_pool = MagicMock()
    mock_conn = MagicMock()
    mock_conn.fetchrow = AsyncMock(return_value={"id": "sess1", "chat_id": 123, "short_code": "abc"})
    bot.db_pool.acquire = lambda: DummyConnWithAcquire(mock_conn)

    msg = MagicMock()
    msg.chat = MagicMock()
    msg.chat.id = 123
    msg.chat.type = "group"
    msg.reply = AsyncMock()

    await cmd_session(msg, bot)

    msg.reply.assert_awaited_once()
    reply_text = msg.reply.call_args[0][0]
    assert "Session ID: sess1" in reply_text
    assert "Chat ID: 123" in reply_text
    assert "Short code: abc" in reply_text


async def test_cmd_session_private_with_active(mock_bot):
    bot = mock_bot
    bot.db_pool = MagicMock()
    mock_conn = MagicMock()
    # First fetch active session returns a row
    # It will call get_active_session_for_user -> fetchrow returns session dict
    # The implementation uses two queries? Actually get_active_session_for_user joins. So we can patch get_active_session_for_user at the function level.
    # Simpler: patch at database level: we'll mock get_active_session_for_user's result by having the bot code call it and we return session.
    # But we cannot easily patch the function inside cmd_session via conftest; better to patch at module level.
    # We'll instead just test that join resulted in session being set by patching set_active_session_for_user.
    # Let's test the /start join flow separately.
    # For cmd_session, we'll test the private branch when there is no active session, and when there is.
    # Let's do two tests: one with active session, one without.
    # We'll create mock session object and patch get_active_session_for_user and get_session_by_chat_id, using return values.
    mock_session = MagicMock(id="sess_priv", chat_id=456, short_code="code456")
    with patch("src.bot.get_active_session_for_user", return_value=mock_session) as mock_get_active, \
         patch("src.bot.get_session_by_chat_id", return_value=None):
        bot = mock_bot
        bot.db_pool = MagicMock()
        bot.db_pool.acquire = lambda: DummyConnWithAcquire(MagicMock())
        msg = MagicMock()
        msg.chat = MagicMock()
        msg.chat.id = 456
        msg.chat.type = "private"
        msg.reply = AsyncMock()
        await cmd_session(msg, bot)
        mock_get_active.assert_awaited_once()
    msg.reply.assert_awaited_once()
    reply_text = msg.reply.call_args[0][0]
    assert "sess_priv" in reply_text


async def test_cmd_start_join_code_private(mock_bot):
    bot = mock_bot
    bot.db_pool = MagicMock()
    mock_conn = MagicMock()
    bot.db_pool.acquire = lambda: DummyConnWithAcquire(mock_conn)
    # Mock get_session_by_short_code to return a session
    mock_session = MagicMock(id="joined_sess", chat_id=789, short_code="JOINME")
    msg = MagicMock()
    msg.chat = MagicMock()
    msg.chat.id = 999
    msg.chat.type = "private"
    msg.from_user = MagicMock(id=555, username="joiner")
    msg.text = "/start JOINME"
    msg.reply = AsyncMock()

    with patch("src.bot.get_session_by_short_code", return_value=mock_session) as mock_get_code, \
         patch("src.bot.get_or_create_user") as mock_user_cre, \
         patch("src.bot.set_active_session_for_user") as mock_set_active:
        await cmd_start(msg, bot)
    mock_get_code.assert_awaited_once()
    mock_user_cre.assert_awaited_once()
    mock_set_active.assert_awaited_once()
    msg.reply.assert_awaited_once()
    reply_text = msg.reply.call_args[0][0]
    assert "joined session" in reply_text


async def test_cmd_leave_private(mock_bot):
    bot = mock_bot
    bot.db_pool = MagicMock()
    mock_conn = MagicMock()
    bot.db_pool.acquire = lambda: DummyConnWithAcquire(mock_conn)
    msg = MagicMock()
    msg.chat = MagicMock()
    msg.chat.type = "private"
    msg.from_user = MagicMock(id=111)
    msg.reply = AsyncMock()
    with patch("src.bot.clear_active_session_for_user") as mock_clear:
        await cmd_leave(msg, bot)
    mock_clear.assert_awaited_once()
    msg.reply.assert_awaited_once()
    assert "left" in msg.reply.call_args[0][0]


async def test_cmd_leave_not_private(mock_bot):
    bot = mock_bot
    msg = MagicMock()
    msg.chat = MagicMock()
    msg.chat.type = "group"
    msg.reply = AsyncMock()
    await cmd_leave(msg, bot)
    msg.reply.assert_awaited_once()
    assert "only in private" in msg.reply.call_args[0][0]


async def test_cmd_delete_playlist_missing_arg(mock_bot):
    bot = mock_bot
    bot.db_pool = MagicMock()

    class DummyConn:
        pass

    class DummyACM:
        async def __aenter__(self):
            return DummyConn()
        async def __aexit__(self, exc_type, exc, tb):
            return False

    bot.db_pool.acquire = lambda: DummyACM()

    msg = MagicMock()
    msg.chat = MagicMock()
    msg.chat.id = 123
    msg.text = "/delete"
    msg.reply = AsyncMock()

    await cmd_delete_playlist(msg, bot)

    msg.reply.assert_awaited_once()
    reply_text = msg.reply.call_args[0][0]
    assert "Usage: /delete <youtube_playlist_id>" in reply_text