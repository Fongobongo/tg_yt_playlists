"""Telegram bot entry point and handlers."""

import logging
import re

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

from .config import Config, load_config, setup_logging
from .database import (
    SessionLimitReachedError,
    clear_active_session_for_user,
    close_pool,
    create_playlist,
    create_pool,
    create_tables,
    create_videos_bulk,
    delete_all_playlists_in_session,
    delete_playlist_by_youtube_id,
    delete_session,
    get_common_video_count,
    get_active_session_for_user,
    get_or_create_session,
    get_or_create_user,
    get_playlists_for_session,
    get_session_by_chat_id,
    get_session_owner_telegram_id,
    get_session_by_short_code,
    get_session_user_stats,
    get_sessions_for_user,
    set_active_session_for_user,
    transaction,
    user_is_member_of_session,
)
from .intersection import compute_common_videos
from .youtube import fetch_playlist_info, normalize_upaste_url

logger = logging.getLogger(__name__)

YOUTUBE_PLAYLIST_REGEX = re.compile(
    r"(?:https?://)?(?:www\.)?youtube\.com/playlist\?list=([^&\s]+)"
)


class AddPlaylistFlow(StatesGroup):
    waiting_for_url = State()
    waiting_for_delete_id = State()


def resolve_actor(message: Message, actor: User | None = None) -> User:
    """Return the user on whose behalf the command should run."""
    if actor is not None:
        return actor
    if message.from_user is None:
        raise ValueError("Message has no user context")
    return message.from_user


def extract_playlist_url(text: str) -> str | None:
    """Extract a supported playlist source URL from text."""
    upaste_url = normalize_upaste_url(text)
    if upaste_url is not None:
        return upaste_url
    match = YOUTUBE_PLAYLIST_REGEX.search(text)
    if not match:
        return None
    playlist_id = match.group(1)
    return f"https://www.youtube.com/playlist?list={playlist_id}"


def get_main_menu_keyboard(is_private: bool) -> InlineKeyboardMarkup:
    """Return inline keyboard with main commands."""
    buttons = [[InlineKeyboardButton(text="🧭 Session", callback_data="cmd:session")]]
    if is_private:
        buttons[0].append(InlineKeyboardButton(text="🗂 My sessions", callback_data="cmd:list_sessions"))
    buttons.extend(
        [
            [InlineKeyboardButton(text="🎵 Playlists", callback_data="cmd:playlists")],
            [InlineKeyboardButton(text="🎬 Common videos", callback_data="cmd:common")],
            [
                InlineKeyboardButton(text="➕ Add playlist", callback_data="cmd:add_playlist"),
                InlineKeyboardButton(text="🧹 Clear playlists", callback_data="cmd:clear_playlists"),
            ],
            [
                InlineKeyboardButton(text="🗑 Delete playlist", callback_data="cmd:delete"),
                InlineKeyboardButton(text="💥 End all sessions", callback_data="cmd:clear"),
            ],
            [InlineKeyboardButton(text="❓ Help", callback_data="cmd:help")],
        ]
    )
    if is_private:
        buttons.append([InlineKeyboardButton(text="🚪 End session", callback_data="cmd:end_session")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_session_member_label(user: dict) -> str:
    """Return a privacy-safe label for a session member."""
    if user["username"]:
        return f"@{user['username']}"
    return "user-without-username"


async def startup(bot: Bot, dispatcher: Dispatcher) -> None:
    """Initialize database connection pool and ensure tables exist."""
    config: Config = bot.config
    pool = await create_pool(config.database_url)
    await create_tables(pool)
    bot.db_pool = pool
    try:
        me = await bot.me()
        bot.my_username = me.username if me else None
    except Exception as exc:
        logger.warning("Failed to fetch bot info: %s", exc)
        bot.my_username = None

    commands = [
        BotCommand(command="start", description="🚀 Create or join a session"),
        BotCommand(command="session", description="🧭 Show current session"),
        BotCommand(command="playlists", description="🎵 List playlists"),
        BotCommand(command="common", description="🎬 Show common videos"),
        BotCommand(command="add_playlist", description="➕ Add playlist by URL"),
        BotCommand(command="clear_playlists", description="🧹 Delete all playlists"),
        BotCommand(command="delete_playlist", description="🗑 Delete one playlist"),
        BotCommand(command="clear", description="💥 Delete the current session"),
        BotCommand(command="end_session", description="🚪 Leave the current private session"),
        BotCommand(command="list_sessions", description="🗂 List your sessions"),
        BotCommand(command="help", description="❓ Show help"),
    ]
    try:
        await bot.set_my_commands(commands)
    except Exception as exc:
        logger.warning("Failed to set bot commands: %s", exc)
    webhook_url = f"{config.webhook_base_url}{config.webhook_path}"
    try:
        await bot.set_webhook(
            webhook_url,
            secret_token=config.webhook_secret,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    except Exception as exc:
        logger.exception("Failed to set webhook to %s", webhook_url)
        raise RuntimeError(f"Failed to set webhook: {exc}") from exc
    logger.info("Bot started and database initialized")


async def shutdown(bot: Bot) -> None:
    """Close database pool on shutdown."""
    pool = getattr(bot, "db_pool", None)
    if pool:
        await close_pool(pool)
    await bot.session.close()
    logger.info("Bot shutdown")


async def prompt_for_playlist_url(message: Message, state: FSMContext) -> None:
    """Ask the user for a playlist URL and switch the FSM into input mode."""
    await state.set_state(AddPlaylistFlow.waiting_for_url)
    await message.reply(
        "Send an upaste.de playlist export URL.\n"
        "Example: https://upaste.de/g3h or https://upaste.de/raw/g3h"
    )


async def prompt_for_delete_playlist_id(message: Message, state: FSMContext) -> None:
    """Ask the user for a playlist ID and switch the FSM into delete mode."""
    await state.set_state(AddPlaylistFlow.waiting_for_delete_id)
    await message.reply(
        "Send the YouTube playlist ID to delete.\n"
        "Use /playlists to see the available IDs."
    )


async def add_playlist_to_session(message: Message, bot: Bot, url: str, actor: User | None = None) -> None:
    """Fetch, store, and compute the intersection for a playlist source URL."""
    chat_id = message.chat.id
    user = resolve_actor(message, actor)
    telegram_id = user.id
    username = user.username
    is_private = message.chat.type == "private"

    try:
        playlist_info = await fetch_playlist_info(url)
    except Exception as exc:
        logger.exception("Failed to fetch playlist from %s", url)
        await message.reply(f"Failed to fetch playlist: {exc}")
        return

    async with bot.db_pool.acquire() as conn:
        async with transaction(conn):
            if is_private:
                session = await get_active_session_for_user(conn, telegram_id)
                if session is None:
                    await message.reply("No active session. Use /start to begin.")
                    return
            else:
                try:
                    session = await get_or_create_session(conn, chat_id, telegram_id)
                except SessionLimitReachedError:
                    await message.reply("You can own at most 5 sessions. Delete one before creating another.")
                    return

            user = await get_or_create_user(conn, session.id, telegram_id, username)
            playlist = await create_playlist(
                conn,
                session_id=session.id,
                user_id=user.id,
                youtube_playlist_id=playlist_info["youtube_playlist_id"],
                title=playlist_info["title"],
                url=playlist_info["url"],
            )
            await create_videos_bulk(conn, playlist.id, playlist_info["videos"])
            common_videos = await compute_common_videos(conn, session.id)

    if not common_videos:
        await message.reply("No common videos found across all playlists in this session yet.")
        return

    lines = [f"{video.title}\n{video.url}" for video in common_videos]
    await message.reply("Common videos in this session:\n\n" + "\n".join(lines))


async def show_common_videos(message: Message, bot: Bot, actor: User | None = None) -> None:
    """Show common videos in the current session."""
    chat_id = message.chat.id
    telegram_id = resolve_actor(message, actor).id
    is_private = message.chat.type == "private"

    async with bot.db_pool.acquire() as conn:
        if is_private:
            session = await get_active_session_for_user(conn, telegram_id)
            if session is None:
                await message.reply("No active session. Use /start to begin.")
                return
        else:
            session = await get_session_by_chat_id(conn, chat_id)
            if session is None:
                await message.reply("No session found for this chat. Use /start to begin.")
                return
        common_videos = await compute_common_videos(conn, session.id)

    if not common_videos:
        await message.reply("No common videos found in this session.")
        return

    lines = [f"{video.title}\n{video.url}" for video in common_videos]
    await message.reply("Common videos in this session:\n\n" + "\n".join(lines))


async def delete_playlist_from_current_session(
    message: Message, bot: Bot, youtube_playlist_id: str, actor: User | None = None
) -> None:
    """Delete playlists by YouTube playlist ID from the current session."""
    chat_id = message.chat.id
    telegram_id = resolve_actor(message, actor).id
    is_private = message.chat.type == "private"

    async with bot.db_pool.acquire() as conn:
        if is_private:
            session = await get_active_session_for_user(conn, telegram_id)
            if session is None:
                await message.reply("No active session. Use /start to begin.")
                return
        else:
            session = await get_session_by_chat_id(conn, chat_id)
            if session is None:
                await message.reply("No session for this chat. Use /start to begin.")
                return

        async with transaction(conn):
            count = await delete_playlist_by_youtube_id(conn, session.id, youtube_playlist_id)

    if count == 0:
        await message.reply(f"No playlist with YouTube ID '{youtube_playlist_id}' found in this session.")
        return
    await message.reply(f"Deleted {count} playlist(s) with YouTube ID '{youtube_playlist_id}'.")


async def cmd_start(message: Message, bot: Bot, actor: User | None = None) -> None:
    """Handle /start command with optional session join code."""
    chat_id = message.chat.id
    user = resolve_actor(message, actor)
    telegram_id = user.id
    username = user.username
    is_private = message.chat.type == "private"

    args = (message.text or "").split(maxsplit=1)
    join_code = args[1].strip() if len(args) > 1 else None

    async with bot.db_pool.acquire() as conn:
        if join_code and is_private:
            session = await get_session_by_short_code(conn, join_code)
            if session is None:
                await message.reply(f"Session with code '{join_code}' not found.")
                return
            async with transaction(conn):
                await get_or_create_user(conn, session.id, telegram_id, username)
                await set_active_session_for_user(conn, telegram_id, session.id)
            await message.reply(
                f"You have joined session {session.id}.\n"
                "Use /add_playlist or the Add playlist button to send a playlist."
            )
            return

        async with transaction(conn):
            try:
                session = await get_or_create_session(conn, chat_id, telegram_id)
            except SessionLimitReachedError:
                await message.reply("You can own at most 5 sessions. Delete one before creating another.")
                return
            await get_or_create_user(conn, session.id, telegram_id, username)
            if is_private:
                await set_active_session_for_user(conn, telegram_id, session.id)

    if is_private:
        bot_username = getattr(bot, "my_username", None)
        invite_link = (
            f"https://t.me/{bot_username}?start={session.short_code}"
            if bot_username and session.short_code
            else None
        )
        lines = [
            f"Private session created: {session.id}",
            "Use /add_playlist or the Add playlist button to submit a playlist.",
        ]
        if session.short_code:
            lines.append(f"Join code: {session.short_code}")
        if invite_link:
            lines.append(f"Invite link: {invite_link}")
        reply_text = "\n".join(lines)
    else:
        reply_text = (
            "Group session is ready.\n"
            "Use /add_playlist or the Add playlist button to submit a playlist."
        )

    await message.reply(reply_text, reply_markup=get_main_menu_keyboard(is_private))


async def cmd_session(message: Message, bot: Bot, actor: User | None = None) -> None:
    """Show current session information."""
    chat_id = message.chat.id
    telegram_id = resolve_actor(message, actor).id
    is_private = message.chat.type == "private"

    async with bot.db_pool.acquire() as conn:
        if is_private:
            session = await get_active_session_for_user(conn, telegram_id)
            if session is None:
                await message.reply("No active session. Use /start to begin.")
                return
        else:
            session = await get_session_by_chat_id(conn, chat_id)
            if session is None:
                await message.reply("No session found for this chat. Use /start to begin.")
                return

    lines = [f"Session ID: {session.id}", f"Chat ID: {session.chat_id}"]
    if session.short_code:
        lines.append(f"Join code: {session.short_code}")
        bot_username = getattr(bot, "my_username", None)
        if bot_username and is_private:
            lines.append(f"Invite link: https://t.me/{bot_username}?start={session.short_code}")
    await message.reply("\n".join(lines))


async def cmd_playlists(message: Message, bot: Bot, actor: User | None = None) -> None:
    """List all playlists in the current session."""
    chat_id = message.chat.id
    telegram_id = resolve_actor(message, actor).id
    is_private = message.chat.type == "private"

    async with bot.db_pool.acquire() as conn:
        if is_private:
            session = await get_active_session_for_user(conn, telegram_id)
            if session is None:
                await message.reply("No active session. Use /start to begin.")
                return
        else:
            session = await get_session_by_chat_id(conn, chat_id)
            if session is None:
                await message.reply("No session found for this chat. Use /start to begin.")
                return
        playlists = await get_playlists_for_session(conn, session.id)

    if not playlists:
        await message.reply("No playlists added yet.")
        return

    lines = [
        f"• {playlist.title}\n  YouTube ID: {playlist.youtube_playlist_id}\n  URL: {playlist.url}"
        for playlist in playlists
    ]
    await message.reply("Playlists in this session:\n\n" + "\n".join(lines))


async def cmd_common(message: Message, bot: Bot, actor: User | None = None) -> None:
    """Show common videos in the current session."""
    await show_common_videos(message, bot, actor=actor)


async def cmd_list_sessions(message: Message, bot: Bot, actor: User | None = None) -> None:
    """List all sessions the user is a member of."""
    if message.chat.type != "private":
        await message.reply("The /list_sessions command works only in private chats.")
        return

    telegram_id = resolve_actor(message, actor).id
    async with bot.db_pool.acquire() as conn:
        sessions = await get_sessions_for_user(conn, telegram_id)
        active_session = await get_active_session_for_user(conn, telegram_id)

    if not sessions:
        await message.reply("You are not a member of any sessions yet. Use /start to create or join one.")
        return

    lines = []
    async with bot.db_pool.acquire() as conn:
        for session in sessions:
            user_stats = await get_session_user_stats(conn, session.id)
            common_video_count = await get_common_video_count(conn, session.id)
            suffix = " [current]" if active_session and session.id == active_session.id else ""
            users_line = ", ".join(
                format_session_member_label(user)
                for user in user_stats
            ) or "-"
            playlists_line = ", ".join(
                f"{format_session_member_label(user)}: {user['playlist_count']}"
                for user in user_stats
            ) or "-"
            lines.append(
                f"• {session.id}{suffix}\n"
                f"  Chat ID: {session.chat_id}\n"
                f"  Created: {session.created_at.date()}\n"
                f"  Join code: {session.short_code or '-'}\n"
                f"  Users: {users_line}\n"
                f"  Playlists per user: {playlists_line}\n"
                f"  Common videos: {common_video_count}"
            )
    await message.reply("Your sessions:\n\n" + "\n\n".join(lines))


async def cmd_clear_playlists(message: Message, bot: Bot, actor: User | None = None) -> None:
    """Delete all playlists from the current session."""
    chat_id = message.chat.id
    telegram_id = resolve_actor(message, actor).id
    is_private = message.chat.type == "private"

    async with bot.db_pool.acquire() as conn:
        if is_private:
            session = await get_active_session_for_user(conn, telegram_id)
            if session is None:
                await message.reply("No active session. Use /start to begin.")
                return
        else:
            session = await get_session_by_chat_id(conn, chat_id)
            if session is None:
                await message.reply("No session for this chat. Use /start to begin.")
                return
        async with transaction(conn):
            count = await delete_all_playlists_in_session(conn, session.id)

    await message.reply(f"Deleted {count} playlist(s) from this session. The session remains active.")


async def cmd_delete_playlist(message: Message, bot: Bot, actor: User | None = None) -> None:
    """Delete playlists by YouTube playlist ID from the current session."""
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.reply(
            "Usage: /delete_playlist <youtube_playlist_id>\n"
            "Use /playlists to see the available IDs."
        )
        return

    youtube_playlist_id = args[1].strip()
    await delete_playlist_from_current_session(message, bot, youtube_playlist_id, actor=actor)


async def cmd_clear(message: Message, bot: Bot, actor: User | None = None) -> None:
    """Delete the current session entirely."""
    chat_id = message.chat.id
    telegram_id = resolve_actor(message, actor).id
    is_private = message.chat.type == "private"

    async with bot.db_pool.acquire() as conn:
        if is_private:
            session = await get_active_session_for_user(conn, telegram_id)
            if session is None:
                await message.reply("No active session to clear.")
                return
            if session.chat_id != telegram_id:
                await message.reply("Only the session owner can delete a shared private session.")
                return
        else:
            session = await get_session_by_chat_id(conn, chat_id)
            if session is None:
                await message.reply("No session for this chat.")
                return
            owner_telegram_id = await get_session_owner_telegram_id(conn, session.id)
            if owner_telegram_id is not None and owner_telegram_id != telegram_id:
                await message.reply("Only the session owner can delete this group session.")
                return

        async with transaction(conn):
            await delete_session(conn, session.id)
            if is_private:
                await clear_active_session_for_user(conn, telegram_id)

    await message.reply("Session data cleared. Use /start to create a new one.")


async def cmd_end_session(message: Message, bot: Bot, actor: User | None = None) -> None:
    """Clear the active session pointer for a private user."""
    if message.chat.type != "private":
        await message.reply("The /end_session command works only in private chats.")
        return

    telegram_id = resolve_actor(message, actor).id
    async with bot.db_pool.acquire() as conn:
        async with transaction(conn):
            await clear_active_session_for_user(conn, telegram_id)
    await message.reply("Current session closed. Use /start to create or join another session.")


async def cmd_add_playlist(
    message: Message, bot: Bot, state: FSMContext, actor: User | None = None
) -> None:
    """Handle /add_playlist as either a direct command or a prompt entrypoint."""
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await prompt_for_playlist_url(message, state)
        return

    url = extract_playlist_url(args[1])
    if url is None:
        await message.reply(
            "Invalid playlist source URL.\n"
            "Example: /add_playlist https://upaste.de/g3h"
        )
        return

    await state.clear()
    await add_playlist_to_session(message, bot, url, actor=actor)


async def handle_add_playlist_input(message: Message, bot: Bot, state: FSMContext) -> None:
    """Handle the next message after the user pressed Add playlist."""
    url = extract_playlist_url(message.text or "")
    if url is None:
        await message.reply(
            "I need an upaste.de playlist export URL.\n"
            "Example: https://upaste.de/g3h"
        )
        return

    await state.clear()
    await add_playlist_to_session(message, bot, url)


async def handle_delete_playlist_input(message: Message, bot: Bot, state: FSMContext) -> None:
    """Handle the next message after the user pressed Delete playlist."""
    playlist_id = (message.text or "").strip()
    if not playlist_id:
        await message.reply(
            "I need a YouTube playlist ID.\n"
            "Use /playlists to see the available IDs."
        )
        return

    await state.clear()
    await delete_playlist_from_current_session(message, bot, playlist_id)


async def cmd_help(message: Message) -> None:
    """Show help information."""
    help_text = (
        "Commands:\n\n"
        "/start - Create a session or join by code\n"
        "/session - Show current session\n"
        "/playlists - List playlists in the session\n"
        "/common - Show common videos in the session\n"
        "/add_playlist <url> - Add an upaste.de playlist export\n"
        "/clear_playlists - Delete all playlists from the session\n"
        "/delete_playlist <youtube_id> - Delete one playlist\n"
        "/clear - Delete the current session\n"
        "/end_session - Leave the current private session\n"
        "/list_sessions - List your sessions\n"
        "/help - Show this help"
    )
    await message.reply(help_text, reply_markup=get_main_menu_keyboard(message.chat.type == "private"))


async def handle_callback(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    """Handle inline button callbacks."""
    data = callback.data or ""
    message = callback.message
    if message is None:
        await callback.answer("Message not found.", show_alert=True)
        return

    try:
        if data.startswith("select_session:"):
            session_id = data.split(":", 1)[1]
            async with bot.db_pool.acquire() as conn:
                if not await user_is_member_of_session(conn, callback.from_user.id, session_id):
                    await callback.answer("Access denied.", show_alert=True)
                    return
                async with transaction(conn):
                    await set_active_session_for_user(conn, callback.from_user.id, session_id)
            await callback.answer("Session selected.")
            return

        if data.startswith("delete_session:"):
            session_id = data.split(":", 1)[1]
            async with bot.db_pool.acquire() as conn:
                if not await user_is_member_of_session(conn, callback.from_user.id, session_id):
                    await callback.answer("Access denied.", show_alert=True)
                    return
                owner_telegram_id = await get_session_owner_telegram_id(conn, session_id)
                if owner_telegram_id != callback.from_user.id:
                    await callback.answer("Only the session owner can delete this session.", show_alert=True)
                    return
                async with transaction(conn):
                    await delete_session(conn, session_id)
                    await clear_active_session_for_user(conn, callback.from_user.id)
            await callback.answer("Session deleted.")
            return

        if not data.startswith("cmd:"):
            await callback.answer("Unknown action.", show_alert=True)
            return

        command = data.split(":", 1)[1]
        if command == "session":
            await cmd_session(message, bot, actor=callback.from_user)
        elif command == "playlists":
            await cmd_playlists(message, bot, actor=callback.from_user)
        elif command == "common":
            await cmd_common(message, bot, actor=callback.from_user)
        elif command == "add_playlist":
            await prompt_for_playlist_url(message, state)
        elif command == "clear_playlists":
            await cmd_clear_playlists(message, bot, actor=callback.from_user)
        elif command == "delete":
            await prompt_for_delete_playlist_id(message, state)
        elif command == "clear":
            await cmd_clear(message, bot, actor=callback.from_user)
        elif command == "end_session":
            await cmd_end_session(message, bot, actor=callback.from_user)
        elif command == "list_sessions":
            await cmd_list_sessions(message, bot, actor=callback.from_user)
        elif command == "help":
            await cmd_help(message)
        else:
            await callback.answer("Command not implemented.", show_alert=True)
            return

        await callback.answer()
    except Exception as exc:
        logger.exception("Callback command failed")
        await callback.answer("Request failed. Try again later.", show_alert=True)


def create_dispatcher() -> Dispatcher:
    """Create and configure the aiogram dispatcher."""
    dp = Dispatcher()

    dp.startup.register(startup)
    dp.shutdown.register(shutdown)

    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_session, Command("session"))
    dp.message.register(cmd_playlists, Command("playlists"))
    dp.message.register(cmd_common, Command("common"))
    dp.message.register(cmd_clear_playlists, Command("clear_playlists"))
    dp.message.register(cmd_delete_playlist, Command("delete_playlist"))
    dp.message.register(cmd_clear, Command("clear"))
    dp.message.register(cmd_end_session, Command("end_session"))
    dp.message.register(cmd_add_playlist, Command("add_playlist"))
    dp.message.register(cmd_help, Command("help"))
    dp.message.register(cmd_list_sessions, Command("list_sessions"))
    dp.message.register(handle_add_playlist_input, StateFilter(AddPlaylistFlow.waiting_for_url))
    dp.message.register(handle_delete_playlist_input, StateFilter(AddPlaylistFlow.waiting_for_delete_id))
    dp.callback_query.register(handle_callback)

    return dp


async def healthcheck(_: web.Request) -> web.Response:
    """Return a simple liveness response for the hosting platform."""
    return web.json_response({"status": "ok"})


def build_app(bot: Bot, dp: Dispatcher, config: Config) -> web.Application:
    """Build the aiohttp application used for Telegram webhooks."""
    app = web.Application()
    app.router.add_get("/healthz", healthcheck)

    webhook_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=config.webhook_secret,
    )
    webhook_handler.register(app, path=config.webhook_path)
    setup_application(app, dp, bot=bot)
    return app


def main() -> None:
    """Application entry point."""
    config = load_config()
    setup_logging(config.log_level)
    bot = Bot(token=config.telegram_bot_token)
    bot.config = config
    bot.db_pool = None
    bot.my_username = None
    dp = create_dispatcher()
    app = build_app(bot, dp, config)
    web.run_app(app, host="0.0.0.0", port=config.port)


if __name__ == "__main__":
    main()
