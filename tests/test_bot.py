"""Tests for bot handlers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot import (
    MENU_LABELS,
    SessionLimitReachedError,
    cmd_add_playlist,
    cmd_clear,
    cmd_clear_playlists,
    cmd_common,
    cmd_end_session,
    cmd_list_sessions,
    cmd_playlists,
    cmd_start,
    extract_join_code,
    extract_playlist_url,
    get_main_menu_keyboard,
    get_persistent_menu_keyboard,
    handle_add_playlist_input,
    handle_delete_playlist_input,
    handle_callback,
    handle_idle_text,
    notify_session_members_about_new_playlist,
    notify_session_members_about_common_videos,
    prompt_for_playlist_url,
)

pytestmark = pytest.mark.asyncio


class DummyTransaction:
    def __init__(self):
        self.start = AsyncMock()
        self.rollback = AsyncMock()
        self.commit = AsyncMock()


class DummyState:
    def __init__(self):
        self.set_state = AsyncMock()
        self.clear = AsyncMock()


class DummyAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


def make_message(text: str, chat_type: str = "group"):
    message = MagicMock()
    message.text = text
    message.chat = SimpleNamespace(id=123, type=chat_type)
    message.from_user = SimpleNamespace(id=456, username="tester")
    message.reply = AsyncMock()
    return message


async def test_extract_playlist_url():
    assert extract_playlist_url("g3h") == "https://upaste.de/g3h"
    assert extract_playlist_url("https://upaste.de/g3h") == "https://upaste.de/g3h"
    assert extract_playlist_url("upaste.de/g3h") == "https://upaste.de/g3h"
    assert extract_playlist_url("take this https://upaste.de/raw/g3h please") == "https://upaste.de/g3h"
    assert extract_playlist_url("Just a normal message") is None


async def test_extract_join_code():
    assert extract_join_code("85fb5b2b7d50") == "85fb5b2b7d50"
    assert (
        extract_join_code(
            "https://t.me/watch_yt_together_bot?start=a570fb97e2d8",
            "watch_yt_together_bot",
        )
        == "a570fb97e2d8"
    )
    assert extract_join_code("https://t.me/other_bot?start=a570fb97e2d8", "watch_yt_together_bot") is None
    assert extract_join_code("hello") is None


async def test_prompt_for_playlist_url_sets_state():
    message = make_message("/add_playlist")
    state = DummyState()

    await prompt_for_playlist_url(message, state)

    state.set_state.assert_awaited_once()
    message.reply.assert_awaited_once()
    assert "Send an upaste.de playlist export URL" in message.reply.call_args[0][0]
    assert "Open the playlist in YouTube" in message.reply.call_args[0][0]
    assert "chromewebstore.google.com" in message.reply.call_args[0][0]


async def test_cmd_add_playlist_without_argument_prompts_for_url(mock_bot):
    message = make_message("/add_playlist")
    state = DummyState()

    await cmd_add_playlist(message, mock_bot, state)

    state.set_state.assert_awaited_once()
    message.reply.assert_awaited_once()


async def test_add_playlist_menu_button_prompts_for_url(mock_bot):
    message = make_message(MENU_LABELS["add_playlist"], chat_type="private")
    state = DummyState()

    await cmd_add_playlist(message, mock_bot, state)

    state.set_state.assert_awaited_once()
    message.reply.assert_awaited_once()
    assert "Send an upaste.de playlist export URL" in message.reply.call_args[0][0]


async def test_cmd_add_playlist_with_argument_processes_url(mock_bot):
    message = make_message("/add_playlist https://upaste.de/g3h")
    state = DummyState()

    with patch("src.bot.add_playlist_to_session", new=AsyncMock()) as add_playlist:
        await cmd_add_playlist(message, mock_bot, state)

    state.clear.assert_awaited_once()
    add_playlist.assert_awaited_once_with(
        message,
        mock_bot,
        "https://upaste.de/g3h",
        actor=None,
    )


async def test_handle_add_playlist_input_accepts_only_playlist_urls(mock_bot):
    message = make_message("not a playlist")
    state = DummyState()

    await handle_add_playlist_input(message, mock_bot, state)

    state.clear.assert_not_called()
    message.reply.assert_awaited_once()
    assert "I need an upaste.de playlist export URL" in message.reply.call_args[0][0]
    assert "Upload text file" in message.reply.call_args[0][0]
    assert "chromewebstore.google.com" in message.reply.call_args[0][0]


async def test_handle_add_playlist_input_acknowledges_processing(mock_bot):
    message = make_message("g3h", chat_type="private")
    state = DummyState()

    with patch("src.bot.add_playlist_to_session", new=AsyncMock()) as add_playlist:
        await handle_add_playlist_input(message, mock_bot, state)

    state.clear.assert_awaited_once()
    message.reply.assert_awaited_once()
    assert "Processing playlist export..." in message.reply.call_args[0][0]
    add_playlist.assert_awaited_once_with(message, mock_bot, "https://upaste.de/g3h")


async def test_handle_idle_text_restores_keyboard():
    message = make_message("hello", chat_type="private")
    mock_bot = MagicMock()
    mock_bot.my_username = "watch_yt_together_bot"

    await handle_idle_text(message, mock_bot)

    message.reply.assert_awaited_once()
    assert "Use the menu buttons or /help" in message.reply.call_args[0][0]


async def test_handle_idle_text_joins_session_from_invite_link(mock_bot):
    message = make_message("https://t.me/watch_yt_together_bot?start=a570fb97e2d8", chat_type="private")
    mock_bot.my_username = "watch_yt_together_bot"

    with patch("src.bot.join_session_by_code", new=AsyncMock(return_value=True)) as join_session:
        await handle_idle_text(message, mock_bot)

    join_session.assert_awaited_once_with(message, mock_bot, "a570fb97e2d8")


async def test_handle_idle_text_joins_session_from_bare_code(mock_bot):
    message = make_message("85fb5b2b7d50", chat_type="private")
    mock_bot.my_username = "watch_yt_together_bot"

    with patch("src.bot.join_session_by_code", new=AsyncMock(return_value=True)) as join_session:
        await handle_idle_text(message, mock_bot)

    join_session.assert_awaited_once_with(message, mock_bot, "85fb5b2b7d50")


async def test_notify_session_members_about_common_videos(mock_bot):
    conn = MagicMock()
    mock_bot.db_pool = MagicMock()
    mock_bot.db_pool.acquire = lambda: DummyAcquire(conn)
    mock_bot.send_message = AsyncMock()
    common_videos = [
        SimpleNamespace(title="Video A", url="https://youtu.be/a", duration_text="42 минуты"),
    ]
    user_stats = [
        {"telegram_id": 111, "username": "alice", "playlist_count": 1},
        {"telegram_id": 222, "username": "bob", "playlist_count": 1},
    ]

    with patch("src.bot.get_session_user_stats", new=AsyncMock(return_value=user_stats)):
        await notify_session_members_about_common_videos(mock_bot, "sess123", common_videos)

    assert mock_bot.send_message.await_count == 2
    assert "Based on playlists from: @alice, @bob" in mock_bot.send_message.await_args.kwargs["text"]


async def test_notify_session_members_about_new_playlist(mock_bot):
    conn = MagicMock()
    mock_bot.db_pool = MagicMock()
    mock_bot.db_pool.acquire = lambda: DummyAcquire(conn)
    mock_bot.send_message = AsyncMock()
    user_stats = [
        {"telegram_id": 111, "username": "alice", "playlist_count": 1},
        {"telegram_id": 222, "username": "bob", "playlist_count": 0},
    ]

    with patch("src.bot.get_session_user_stats", new=AsyncMock(return_value=user_stats)):
        await notify_session_members_about_new_playlist(mock_bot, "sess123", "@alice", "Watch Later")

    assert mock_bot.send_message.await_count == 2
    assert "New playlist added by @alice" in mock_bot.send_message.await_args.kwargs["text"]


async def test_cmd_start_group_creates_session(mock_bot):
    message = make_message("/start", chat_type="group")
    conn = MagicMock()
    conn.transaction.return_value = DummyTransaction()
    mock_bot.db_pool = MagicMock()
    mock_bot.db_pool.acquire = lambda: DummyAcquire(conn)
    session = SimpleNamespace(id="s1", short_code="abc123", chat_id=123)

    with patch("src.bot.get_or_create_session", new=AsyncMock(return_value=session)) as get_session, patch(
        "src.bot.get_or_create_user", new=AsyncMock()
    ):
        await cmd_start(message, mock_bot)

    get_session.assert_awaited_once()
    message.reply.assert_awaited_once()
    assert "Group session is ready." in message.reply.call_args[0][0]


async def test_cmd_start_rejects_session_limit(mock_bot):
    message = make_message("/start", chat_type="group")
    conn = MagicMock()
    conn.transaction.return_value = DummyTransaction()
    mock_bot.db_pool = MagicMock()
    mock_bot.db_pool.acquire = lambda: DummyAcquire(conn)

    with patch(
        "src.bot.get_or_create_session",
        new=AsyncMock(side_effect=SessionLimitReachedError("limit")),
    ):
        await cmd_start(message, mock_bot)

    assert "at most 5 sessions" in message.reply.call_args[0][0]


async def test_cmd_playlists_renders_list(mock_bot):
    message = make_message("/playlists")
    conn = MagicMock()
    conn.transaction.return_value = DummyTransaction()
    session = SimpleNamespace(id="sess123")
    mock_bot.db_pool = MagicMock()
    mock_bot.db_pool.acquire = lambda: DummyAcquire(conn)

    with patch("src.bot.get_session_by_chat_id", new=AsyncMock(return_value=session)), patch(
        "src.bot.get_playlists_for_user_in_session",
        new=AsyncMock(
            return_value=[
                SimpleNamespace(title="Playlist A", youtube_playlist_id="PL_A", url="https://youtube.com/a", video_count=3),
                SimpleNamespace(title="Playlist B", youtube_playlist_id="PL_B", url="https://youtube.com/b", video_count=7),
            ]
        ),
    ):
        await cmd_playlists(message, mock_bot)

    message.reply.assert_awaited_once()
    reply_text = message.reply.call_args[0][0]
    assert "Your playlists in this session" in reply_text
    assert "Playlist A" in reply_text
    assert "PL_B" in reply_text
    assert "Videos: 7" in reply_text


async def test_cmd_common_renders_common_videos(mock_bot):
    message = make_message("/common")
    conn = MagicMock()
    session = SimpleNamespace(id="sess123")
    mock_bot.db_pool = MagicMock()
    mock_bot.db_pool.acquire = lambda: DummyAcquire(conn)

    with patch("src.bot.get_session_by_chat_id", new=AsyncMock(return_value=session)), patch(
        "src.bot.compute_common_videos",
        new=AsyncMock(
            return_value=[
                SimpleNamespace(title="Video A", url="https://youtu.be/a", duration_text="42 минуты"),
                SimpleNamespace(title="Video B", url="https://youtu.be/b", duration_text=None),
            ]
        ),
    ), patch(
        "src.bot.get_session_user_stats",
        new=AsyncMock(
            return_value=[
                {"telegram_id": 111, "username": "alice", "playlist_count": 1},
                {"telegram_id": 222, "username": "bob", "playlist_count": 1},
            ]
        ),
    ):
        await cmd_common(message, mock_bot)

    reply_text = message.reply.call_args[0][0]
    assert "Common videos in this session: 2" in reply_text
    assert "Based on playlists from: @alice, @bob" in reply_text
    assert "1. Video A (42 минуты)" in reply_text
    assert "2. Video B" in reply_text


async def test_cmd_clear_playlists_success(mock_bot):
    message = make_message("/clear_playlists")
    conn = MagicMock()
    conn.transaction.return_value = DummyTransaction()
    session = SimpleNamespace(id="sess123")
    mock_bot.db_pool = MagicMock()
    mock_bot.db_pool.acquire = lambda: DummyAcquire(conn)

    with patch("src.bot.get_session_by_chat_id", new=AsyncMock(return_value=session)), patch(
        "src.bot.delete_all_playlists_in_session", new=AsyncMock(return_value=2)
    ) as delete_all:
        await cmd_clear_playlists(message, mock_bot)

    delete_all.assert_awaited_once_with(conn, "sess123")
    assert "Deleted 2 playlist(s)" in message.reply.call_args[0][0]


async def test_cmd_clear_deletes_session(mock_bot):
    message = make_message("/clear")
    conn = MagicMock()
    conn.transaction.return_value = DummyTransaction()
    session = SimpleNamespace(id="sess123")
    mock_bot.db_pool = MagicMock()
    mock_bot.db_pool.acquire = lambda: DummyAcquire(conn)

    with patch("src.bot.get_session_by_chat_id", new=AsyncMock(return_value=session)), patch(
        "src.bot.get_session_owner_telegram_id", new=AsyncMock(return_value=456)
    ), patch(
        "src.bot.clear_active_session_for_user", new=AsyncMock()
    ), patch(
        "src.bot.delete_session", new=AsyncMock(return_value=True)
    ) as delete_session:
        await cmd_clear(message, mock_bot)

    delete_session.assert_awaited_once_with(conn, "sess123")
    assert "Session deleted for all participants." in message.reply.call_args[0][0]


async def test_cmd_clear_rejected_for_shared_private_session(mock_bot):
    message = make_message("/clear", chat_type="private")
    conn = MagicMock()
    conn.transaction.return_value = DummyTransaction()
    session = SimpleNamespace(id="sess123", chat_id=999)
    mock_bot.db_pool = MagicMock()
    mock_bot.db_pool.acquire = lambda: DummyAcquire(conn)

    with patch("src.bot.get_active_session_for_user", new=AsyncMock(return_value=session)), patch(
        "src.bot.get_session_owner_telegram_id", new=AsyncMock(return_value=999)
    ), patch(
        "src.bot.clear_active_session_for_user", new=AsyncMock()
    ), patch("src.bot.remove_user_from_session", new=AsyncMock(return_value=True)) as leave_session, patch(
        "src.bot.delete_session", new=AsyncMock()
    ) as delete_session:
        await cmd_clear(message, mock_bot)

    delete_session.assert_not_awaited()
    leave_session.assert_awaited_once_with(conn, "sess123", 456)
    assert "You left this session." in message.reply.call_args[0][0]


async def test_cmd_clear_rejected_for_group_non_owner(mock_bot):
    message = make_message("/clear", chat_type="group")
    conn = MagicMock()
    conn.transaction.return_value = DummyTransaction()
    session = SimpleNamespace(id="sess123")
    mock_bot.db_pool = MagicMock()
    mock_bot.db_pool.acquire = lambda: DummyAcquire(conn)

    with patch("src.bot.get_session_by_chat_id", new=AsyncMock(return_value=session)), patch(
        "src.bot.get_session_owner_telegram_id", new=AsyncMock(return_value=999)
    ), patch(
        "src.bot.clear_active_session_for_user", new=AsyncMock()
    ), patch("src.bot.remove_user_from_session", new=AsyncMock(return_value=True)) as leave_session, patch(
        "src.bot.delete_session", new=AsyncMock()
    ) as delete_session:
        await cmd_clear(message, mock_bot)

    delete_session.assert_not_awaited()
    leave_session.assert_awaited_once_with(conn, "sess123", 456)
    assert "You left this session." in message.reply.call_args[0][0]


async def test_cmd_end_session_private(mock_bot):
    message = make_message("/end_session", chat_type="private")
    conn = MagicMock()
    conn.transaction.return_value = DummyTransaction()
    mock_bot.db_pool = MagicMock()
    mock_bot.db_pool.acquire = lambda: DummyAcquire(conn)

    with patch("src.bot.clear_active_session_for_user", new=AsyncMock()) as clear_active:
        await cmd_end_session(message, mock_bot)

    clear_active.assert_awaited_once_with(conn, 456)
    assert "Current session closed" in message.reply.call_args[0][0]


async def test_cmd_end_session_rejected_in_group(mock_bot):
    message = make_message("/end_session", chat_type="group")

    await cmd_end_session(message, mock_bot)

    message.reply.assert_awaited_once()
    assert "works only in private chats" in message.reply.call_args[0][0]


async def test_cmd_list_sessions_includes_user_and_common_stats(mock_bot):
    message = make_message("/list_sessions", chat_type="private")
    conn = MagicMock()
    mock_bot.db_pool = MagicMock()
    mock_bot.db_pool.acquire = lambda: DummyAcquire(conn)
    sessions = [SimpleNamespace(id="sess123", chat_id=123, created_at=SimpleNamespace(date=lambda: "2026-03-11"), short_code="abc123")]
    active = None
    user_stats = [
        {"telegram_id": 111, "username": "alice", "playlist_count": 2},
        {"telegram_id": 222, "username": None, "playlist_count": 1},
    ]

    with patch("src.bot.get_sessions_for_user", new=AsyncMock(return_value=sessions)), patch(
        "src.bot.get_active_session_for_user", new=AsyncMock(return_value=active)
    ), patch("src.bot.get_session_user_stats", new=AsyncMock(return_value=user_stats)), patch(
        "src.bot.get_common_video_count", new=AsyncMock(return_value=3)
    ), patch(
        "src.bot.get_session_owner_telegram_id", new=AsyncMock(return_value=456)
    ):
        await cmd_list_sessions(message, mock_bot)

    reply_text = message.reply.call_args[0][0]
    assert "Users: @alice, user-without-username" in reply_text
    assert "Playlists per user: @alice: 2, user-without-username: 1" in reply_text
    assert "Common videos: 3" in reply_text
    reply_markup = message.reply.call_args.kwargs["reply_markup"]
    assert reply_markup.inline_keyboard[0][1].text == "Delete"


async def test_handle_delete_playlist_input_deletes_playlist(mock_bot):
    message = make_message("PL123")
    state = DummyState()

    with patch("src.bot.delete_playlist_from_current_session", new=AsyncMock()) as delete_playlist:
        await handle_delete_playlist_input(message, mock_bot, state)

    state.clear.assert_awaited_once()
    delete_playlist.assert_awaited_once_with(message, mock_bot, "PL123")


async def test_group_keyboard_hides_my_sessions():
    keyboard = get_main_menu_keyboard(False)
    texts = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "My sessions" not in texts
    assert "🎬 Common videos" in texts


async def test_private_keyboard_uses_icon_labels():
    keyboard = get_main_menu_keyboard(True)
    texts = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "🧭 Session" in texts
    assert "🗂 My sessions" in texts
    assert "➕ Add playlist" in texts


async def test_persistent_keyboard_is_available():
    keyboard = get_persistent_menu_keyboard(True)
    texts = [button.text for row in keyboard.keyboard for button in row]
    assert MENU_LABELS["session"] in texts
    assert MENU_LABELS["list_sessions"] in texts
    assert keyboard.is_persistent is True


async def test_delete_session_callback_requires_owner(mock_bot):
    callback = MagicMock()
    callback.data = "delete_session:sess123"
    callback.from_user = SimpleNamespace(id=456)
    callback.message = make_message("button", chat_type="private")
    callback.answer = AsyncMock()
    state = DummyState()
    conn = MagicMock()
    conn.transaction.return_value = DummyTransaction()
    mock_bot.db_pool = MagicMock()
    mock_bot.db_pool.acquire = lambda: DummyAcquire(conn)

    with patch("src.bot.user_is_member_of_session", new=AsyncMock(return_value=True)), patch(
        "src.bot.get_session_owner_telegram_id", new=AsyncMock(return_value=999)
    ), patch(
        "src.bot.clear_active_session_for_user", new=AsyncMock()
    ), patch("src.bot.remove_user_from_session", new=AsyncMock(return_value=True)) as leave_session, patch(
        "src.bot.delete_session", new=AsyncMock()
    ) as delete_session:
        await handle_callback(callback, mock_bot, state)

    delete_session.assert_not_awaited()
    leave_session.assert_awaited_once_with(conn, "sess123", 456)
    callback.answer.assert_awaited()
    assert "You left the session." in callback.answer.call_args[0][0]


async def test_list_sessions_callback_uses_callback_user_not_message_author(mock_bot):
    callback = MagicMock()
    callback.data = "cmd:list_sessions"
    callback.from_user = SimpleNamespace(id=456, username="tester")
    callback.message = make_message("button", chat_type="private")
    callback.message.from_user = SimpleNamespace(id=999999, username="watch_yt_together_bot")
    callback.answer = AsyncMock()
    state = DummyState()
    conn = MagicMock()
    mock_bot.db_pool = MagicMock()
    mock_bot.db_pool.acquire = lambda: DummyAcquire(conn)
    sessions = [
        SimpleNamespace(
            id="sess123",
            chat_id=123,
            created_at=SimpleNamespace(date=lambda: "2026-03-11"),
            short_code="abc123",
        )
    ]
    active = SimpleNamespace(id="sess123")

    with patch("src.bot.get_sessions_for_user", new=AsyncMock(return_value=sessions)) as get_sessions, patch(
        "src.bot.get_active_session_for_user", new=AsyncMock(return_value=active)
    ), patch("src.bot.get_session_user_stats", new=AsyncMock(return_value=[])), patch(
        "src.bot.get_common_video_count", new=AsyncMock(return_value=0)
    ), patch(
        "src.bot.get_session_owner_telegram_id", new=AsyncMock(return_value=999)
    ):
        await handle_callback(callback, mock_bot, state)

    get_sessions.assert_awaited_once_with(conn, 456)
    callback.message.reply.assert_awaited_once()
    callback.answer.assert_awaited()
