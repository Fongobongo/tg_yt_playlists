"""Telegram bot entry point and handlers."""

import logging
import re
from typing import List

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, Message

from .config import Config, load_config, setup_logging
from .database import (
    create_pool,
    create_tables,
    close_pool,
    get_or_create_session,
    get_session_by_chat_id,
    get_or_create_user,
    create_playlist,
    create_videos_bulk,
    get_playlists_for_session,
    get_session_by_short_code,
    get_active_session_for_user,
    set_active_session_for_user,
    clear_active_session_for_user,
    delete_all_playlists_in_session,
    transaction,
)
from .intersection import compute_common_videos
from .youtube import fetch_playlist_info

logger = logging.getLogger(__name__)

# Regex to match YouTube playlist URLs
YOUTUBE_PLAYLIST_REGEX = re.compile(
    r"(?:https?://)?(?:www\.)?youtube\.com/playlist\?list=([^&\s]+)"
)


def extract_playlist_url(text: str) -> str | None:
    """
    Extract a YouTube playlist URL from text.

    Returns a full URL with https scheme if found, otherwise None.
    """
    match = YOUTUBE_PLAYLIST_REGEX.search(text)
    if match:
        playlist_id = match.group(1)
        return f"https://www.youtube.com/playlist?list={playlist_id}"
    return None


def get_main_menu_keyboard(is_private: bool) -> InlineKeyboardMarkup:
    """Return inline keyboard with main commands."""
    buttons = [
        [InlineKeyboardButton(text="📋 Session", callback_data="cmd:session"),
         InlineKeyboardButton(text="📚 Playlists", callback_data="cmd:playlists")],
        [InlineKeyboardButton(text="➕ Add", callback_data="cmd:add"),
         InlineKeyboardButton(text="🗑 Clear playlists", callback_data="cmd:clear_playlists")],
        [InlineKeyboardButton(text="❌ Delete", callback_data="cmd:delete"),
         InlineKeyboardButton(text="💥 Clear all", callback_data="cmd:clear")],
        [InlineKeyboardButton(text="❓ Help", callback_data="cmd:help")],
    ]
    if is_private:
        buttons.append([InlineKeyboardButton(text="🛑 End session", callback_data="cmd:end_session")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def startup(bot: Bot) -> None:
    """Initialize database connection pool and ensure tables exist."""
    config: Config = bot.config
    pool = await create_pool(config.database_url)
    await create_tables(pool)
    bot.db_pool = pool
    try:
        me = await bot.me()
        bot.my_username = me.username if me else None
    except Exception as e:
        logger.warning("Failed to fetch bot info: %s", e)
        bot.my_username = None
    # Register bot commands for Telegram UI
    commands = [
        BotCommand(command="start", description="Create/join a session"),
        BotCommand(command="session", description="Show current session"),
        BotCommand(command="playlists", description="List playlists"),
        BotCommand(command="add", description="Add playlist by URL"),
        BotCommand(command="clear_playlists", description="Delete all playlists"),
        BotCommand(command="delete_playlist", description="Delete one playlist"),
        BotCommand(command="clear", description="Delete session entirely"),
        BotCommand(command="end_session", description="End current session (private)"),
        BotCommand(command="help", description="Help info"),
    ]
    try:
        await bot.set_my_commands(commands)
        logger.info("Bot commands registered")
    except Exception as e:
        logger.warning("Failed to set bot commands: %s", e)
    logger.info("Bot started and database initialized")


async def shutdown(bot: Bot) -> None:
    """Close database pool on shutdown."""
    pool = getattr(bot, "db_pool", None)
    if pool:
        await close_pool(pool)
    logger.info("Bot shutdown")


async def cmd_start(message: Message, bot: Bot) -> None:
    """Handle /start command with optional session join code."""
    chat_id = message.chat.id
    telegram_id = message.from_user.id
    username = message.from_user.username
    is_private = message.chat.type == "private"

    args = message.text.split(maxsplit=1)
    join_code = args[1].strip() if len(args) > 1 else None

    async with bot.db_pool.acquire() as conn:
        if join_code and is_private:
            session = await get_session_by_short_code(conn, join_code)
            if not session:
                await message.reply(f"❌ Session with code '{join_code}' not found.")
                return
            async with transaction(conn):
                await get_or_create_user(conn, session.id, telegram_id, username)
                await set_active_session_for_user(conn, telegram_id, session.id)
            await message.reply(
                f"✅ You have joined session {session.id} (chat ID: {session.chat_id}).\n"
                f"Now you can send playlists and they will be added to this session."
            )
            return

        async with transaction(conn):
            session = await get_or_create_session(conn, chat_id)
            if is_private:
                await set_active_session_for_user(conn, telegram_id, session.id)
            await get_or_create_user(conn, session.id, telegram_id, username)

        if is_private:
            if session.short_code:
                bot_username = getattr(bot, "my_username", None)
                invite_link = f"https://t.me/{bot_username}?start={session.short_code}" if bot_username else f"Code: {session.short_code}"
                reply_text = (
                    f"Welcome! This is your private session (ID: {session.id}).\n"
                    f"Share this link to let others join your session:\n{invite_link}\n\n"
                    f"Commands: /session, /playlists, /add, /clear_playlists, /delete_playlist <youtube_id>, /clear, /end_session, /help"
                )
            else:
                reply_text = (
                    f"Welcome! This is your private session (ID: {session.id}).\n"
                    f"Commands: /session, /playlists, /add, /clear_playlists, /delete_playlist <youtube_id>, /clear, /end_session, /help"
                )
        else:
            reply_text = (
                f"Hello! I'm the YouTube Playlist Intersection Bot.\n"
                f"This group (ID: {chat_id}) has its own session.\n"
                f"Send me a YouTube playlist URL (or use /add) and I'll add it to the session.\n"
                f"I'll then show videos that are common to all playlists in this session.\n"
                f"Commands: /start, /session, /playlists, /add, /clear_playlists, /delete_playlist <youtube_id>, /clear, /help"
            )
        await message.reply(reply_text, reply_markup=get_main_menu_keyboard(is_private))


async def cmd_session(message: Message, bot: Bot) -> None:
    """Show current session information."""
    chat_id = message.chat.id
    telegram_id = message.from_user.id
    is_private = message.chat.type == "private"
    async with bot.db_pool.acquire() as conn:
        if is_private:
            session = await get_active_session_for_user(conn, telegram_id)
            if not session:
                await message.reply("No active session. Use /start to begin.")
                return
        else:
            session = await get_session_by_chat_id(conn, chat_id)
            if not session:
                await message.reply("No session found for this chat. Use /start to begin.")
                return

        info = [
            f"Session ID: {session.id}",
            f"Chat ID: {session.chat_id}",
        ]
        if session.short_code:
            info.append(f"Short code: {session.short_code}")
            bot_username = getattr(bot, "my_username", None)
            if bot_username and is_private:
                invite_link = f"https://t.me/{bot_username}?start={session.short_code}"
                info.append(f"Invite link: {invite_link}")
        await message.reply("\n".join(info))


async def cmd_playlists(message: Message, bot: Bot) -> None:
    """List all playlists added in this session."""
    chat_id = message.chat.id
    telegram_id = message.from_user.id
    is_private = message.chat.type == "private"
    async with bot.db_pool.acquire() as conn:
        if is_private:
            session = await get_active_session_for_user(conn, telegram_id)
            if not session:
                await message.reply("No active session. Use /start to begin.")
                return
        else:
            session = await get_session_by_chat_id(conn, chat_id)
            if not session:
                await message.reply("No session found for this chat. Use /start to begin.")
                return

        playlists = await get_playlists_for_session(conn, session.id)
        if not playlists:
            await message.reply("No playlists added yet.")
            return
        lines = [
            f"• {p.title}\n  YouTube ID: {p.youtube_playlist_id}\n  URL: {p.url}"
            for p in playlists
        ]
        await message.reply("Playlists in this session:\n\n" + "\n".join(lines))


async def cmd_clear_playlists(message: Message, bot: Bot) -> None:
    """Delete all playlists (and their videos) in the current session, but keep the session and users."""
    chat_id = message.chat.id
    telegram_id = message.from_user.id
    is_private = message.chat.type == "private"
    async with bot.db_pool.acquire() as conn:
        if is_private:
            session = await get_active_session_for_user(conn, telegram_id)
            if not session:
                await message.reply("No active session. Use /start to begin.")
                return
        else:
            session = await get_session_by_chat_id(conn, chat_id)
            if not session:
                await message.reply("No session for this chat. Use /start to begin.")
                return

        async with transaction(conn):
            count = await delete_all_playlists_in_session(conn, session.id)
        await message.reply(f"Deleted {count} playlist(s) from this session. The session remains active.")


async def cmd_clear(message: Message, bot: Bot) -> None:
    """Clear all data for the current session (deletes the session entirely)."""
    chat_id = message.chat.id
    telegram_id = message.from_user.id
    is_private = message.chat.type == "private"
    async with bot.db_pool.acquire() as conn:
        if is_private:
            session = await get_active_session_for_user(conn, telegram_id)
            if not session:
                await message.reply("No active session to clear.")
                return
        else:
            session = await get_session_by_chat_id(conn, chat_id)
            if not session:
                await message.reply("No session for this chat.")
                return

        async with transaction(conn):
            await conn.execute("DELETE FROM sessions WHERE id = ?", (session.id,))
            if is_private:
                await clear_active_session_for_user(conn, telegram_id)
        await message.reply("Session data cleared. You can start fresh now.")


async def cmd_end_session(message: Message, bot: Bot) -> None:
    """End current active session (private chats only)."""
    if message.chat.type != "private":
        await message.reply("The /end_session command works only in private chats.")
        return
    telegram_id = message.from_user.id
    async with bot.db_pool.acquire() as conn:
        async with transaction(conn):
            await clear_active_session_for_user(conn, telegram_id)
    await message.reply("You have ended the current session. Use /start to create a new session or join another with a code.")


async def cmd_delete_playlist(message: Message, bot: Bot) -> None:
    """Delete a playlist by its YouTube playlist ID from the current session."""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply(
            "Usage: /delete <youtube_playlist_id>\n"
            "You can find the YouTube playlist ID in the /playlists list."
        )
        return

    youtube_playlist_id = args[1].strip()
    chat_id = message.chat.id
    telegram_id = message.from_user.id
    is_private = message.chat.type == "private"

    async with bot.db_pool.acquire() as conn:
        if is_private:
            session = await get_active_session_for_user(conn, telegram_id)
            if not session:
                await message.reply("No active session. Use /start to begin.")
                return
        else:
            session = await get_session_by_chat_id(conn, chat_id)
            if not session:
                await message.reply("No session for this chat. Use /start to begin.")
                return

        async with transaction(conn):
            result = await conn.execute(
                "DELETE FROM playlists WHERE session_id = ? AND youtube_playlist_id = ?",
                (session.id, youtube_playlist_id),
            )
            count = int(result.split()[1]) if result and result.startswith("DELETE") else 0

        if count == 0:
            await message.reply(
                f"No playlist with YouTube ID '{youtube_playlist_id}' found in this session."
            )
        else:
            await message.reply(
                f"Deleted {count} playlist(s) with YouTube ID '{youtube_playlist_id}'."
            )


async def cmd_add(message: Message, bot: Bot) -> None:
    """Add a YouTube playlist by URL to the current session."""
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Usage: /add <youtube_playlist_url>\nExample: /add https://www.youtube.com/playlist?list=PLxxx")
        return

    url = extract_playlist_url(args[1])
    if not url:
        await message.reply("Invalid YouTube playlist URL.\nExample: /add https://www.youtube.com/playlist?list=PLxxx")
        return

    chat_id = message.chat.id
    telegram_id = message.from_user.id
    username = message.from_user.username
    is_private = message.chat.type == "private"

    try:
        playlist_info = await fetch_playlist_info(url)
    except Exception as e:
        logger.exception("Failed to fetch playlist from %s", url)
        await message.reply(f"Failed to fetch playlist: {e}")
        return

    async with bot.db_pool.acquire() as conn:
        async with transaction(conn):
            if is_private:
                session = await get_active_session_for_user(conn, telegram_id)
                if not session:
                    await message.reply("No active session. Use /start to begin.")
                    return
            else:
                session = await get_or_create_session(conn, chat_id)

            user_obj = await get_or_create_user(conn, session.id, telegram_id, username)
            playlist_obj = await create_playlist(
                conn,
                session_id=session.id,
                user_id=user_obj.id,
                youtube_playlist_id=playlist_info["youtube_playlist_id"],
                title=playlist_info["title"],
                url=playlist_info["url"],
            )
            if playlist_info["videos"]:
                await create_videos_bulk(conn, playlist_obj.id, playlist_info["videos"])

            common_videos = await compute_common_videos(conn, session.id)

        if not common_videos:
            reply_text = "No common videos found across all playlists in this session yet."
        else:
            lines = [f"{video.title}\n{video.url}" for video in common_videos]
            reply_text = "Common videos in this session:\n\n" + "\n".join(lines)

        await message.reply(reply_text)


async def cmd_help(message: Message, bot: Bot) -> None:
    """Show help information."""
    help_text = (
        "📖 Commands:\n\n"
        "/start — Create a session or join via code\n"
        "/session — Show current session info\n"
        "/playlists — List playlists in this session\n"
        "/add <url> — Add a YouTube playlist\n"
        "/clear_playlists — Delete all playlists (keeps session)\n"
        "/delete_playlist <youtube_id> — Delete one playlist\n"
        "/clear — Delete the entire session\n"
        "/end_session — End current session (private only)\n"
        "/help — Show this help"
    )
    is_private = message.chat.type == "private"
    await message.reply(help_text, reply_markup=get_main_menu_keyboard(is_private))


async def handle_playlist_url(message: Message, bot: Bot) -> None:
    """Handle any message containing a YouTube playlist URL."""
    text = message.text or message.caption or ""
    url = extract_playlist_url(text)
    if not url:
        return

    chat_id = message.chat.id
    telegram_id = message.from_user.id
    username = message.from_user.username
    is_private = message.chat.type == "private"

    try:
        playlist_info = await fetch_playlist_info(url)
    except Exception as e:
        logger.exception("Failed to fetch playlist from %s", url)
        await message.reply(f"Failed to fetch playlist: {e}")
        return

    async with bot.db_pool.acquire() as conn:
        async with transaction(conn):
            if is_private:
                session = await get_active_session_for_user(conn, telegram_id)
                if not session:
                    await message.reply("No active session. Use /start to begin.")
                    return
            else:
                session = await get_or_create_session(conn, chat_id)

            user_obj = await get_or_create_user(conn, session.id, telegram_id, username)
            playlist_obj = await create_playlist(
                conn,
                session_id=session.id,
                user_id=user_obj.id,
                youtube_playlist_id=playlist_info["youtube_playlist_id"],
                title=playlist_info["title"],
                url=playlist_info["url"],
            )
            if playlist_info["videos"]:
                await create_videos_bulk(conn, playlist_obj.id, playlist_info["videos"])

            common_videos = await compute_common_videos(conn, session.id)

        if not common_videos:
            reply_text = "No common videos found across all playlists in this session yet."
        else:
            lines = [f"{video.title}\n{video.url}" for video in common_videos]
            reply_text = "Common videos in this session:\n\n" + "\n".join(lines)

        await message.reply(reply_text)


async def handle_callback(callback: CallbackQuery, bot: Bot) -> None:
    """Handle inline button callbacks."""
    data = callback.data
    if not data.startswith("cmd:"):
        await callback.answer("Unknown action")
        return
    cmd = data.split(":", 1)[1]
    message = callback.message
    try:
        if cmd == "session":
            await cmd_session(message, bot)
        elif cmd == "playlists":
            await cmd_playlists(message, bot)
        elif cmd == "add":
            await cmd_add(message, bot)
        elif cmd == "clear_playlists":
            await cmd_clear_playlists(message, bot)
        elif cmd == "delete":
            await cmd_delete_playlist(message, bot)
        elif cmd == "clear":
            await cmd_clear(message, bot)
        elif cmd == "end_session":
            await cmd_end_session(message, bot)
        elif cmd == "help":
            await cmd_help(message, bot)
        else:
            await callback.answer("Command not implemented")
            return
        await callback.answer()
    except Exception as e:
        logger.exception("Callback command failed")
        await callback.answer(f"Error: {e}", show_alert=True)


def create_dispatcher() -> Dispatcher:
    """Create and configure the Aiogram Dispatcher."""
    dp = Dispatcher()

    dp.startup.register(startup)
    dp.shutdown.register(shutdown)

    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_session, Command("session"))
    dp.message.register(cmd_playlists, Command("playlists"))
    dp.message.register(cmd_delete_playlist, Command("delete_playlist"))
    dp.message.register(cmd_clear, Command("clear"))
    dp.message.register(cmd_end_session, Command("end_session"))
    # Command handlers
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_session, Command("session"))
    dp.message.register(cmd_playlists, Command("playlists"))
    dp.message.register(cmd_clear_playlists, Command("clear_playlists"))
    dp.message.register(cmd_delete_playlist, Command("delete_playlist"))
    dp.message.register(cmd_clear, Command("clear"))
    dp.message.register(cmd_end_session, Command("end_session"))
    dp.message.register(cmd_add, Command("add"))
    dp.message.register(cmd_help, Command("help"))
    dp.message.register(handle_playlist_url)
    dp.callback_query.register(handle_callback)

    return dp


async def main() -> None:
    """Application entry point."""
    config = load_config()
    setup_logging(config.log_level)
    bot = Bot(token=config.telegram_bot_token)
    bot.config = config
    bot.db_pool = None
    dp = create_dispatcher()
    try:
        await dp.start_polling(bot)
    finally:
        await dp.storage.close()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())