"""Telegram bot entry point and handlers."""

import logging
import re
from typing import List

import asyncpg
from aiogram import Bot, Dispatcher, filters
from aiogram.filters import Command
from aiogram.types import Message

from .config import Config, load_config, setup_logging
from .database import (
    create_pool,
    create_tables,
    close_pool,
    get_or_create_session,
    get_or_create_user,
    create_playlist,
    create_videos_bulk,
    get_playlists_for_session,
    delete_all_playlists_in_session,
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
        # Preserve additional parameters? For simplicity, only the playlist ID matters.
        return f"https://www.youtube.com/playlist?list={playlist_id}"
    return None


async def startup(bot: Bot) -> None:
    """Initialize database connection pool and ensure tables exist."""
    config: Config = bot["config"]
    pool = await create_pool(config.database_url)
    await create_tables(pool)
    bot["db_pool"] = pool
    logger.info("Bot started and database initialized")


async def shutdown(bot: Bot) -> None:
    """Close database pool on shutdown."""
    pool: asyncpg.Pool = bot.get("db_pool")
    if pool:
        await close_pool(pool)
    logger.info("Bot shutdown")


async def cmd_start(message: Message, bot: Bot) -> None:
    """Handle /start command."""
    chat_id = message.chat.id
    async with bot["db_pool"].acquire() as conn:
        await get_or_create_session(conn, chat_id)
    await message.reply(
        f"Hello! I'm the YouTube Playlist Intersection Bot.\n"
        f"This chat (ID: {chat_id}) has its own session.\n"
        f"Send me a YouTube playlist URL and I'll add it to the session.\n"
        f"I'll then show videos that are common to all playlists in this session.\n"
        f"Commands: /start, /playlists, /clear_playlists, /delete <youtube_playlist_id>, /clear"
    )


async def cmd_playlists(message: Message, bot: Bot) -> None:
    """List all playlists added in this session."""
    chat_id = message.chat.id
    async with bot["db_pool"].acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM sessions WHERE chat_id = $1", chat_id
        )
        if not row:
            await message.reply("No playlists have been added yet. Send me a playlist URL to get started.")
            return
        session_id = str(row["id"])
        playlists = await get_playlists_for_session(conn, session_id)
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
    async with bot["db_pool"].acquire() as conn:
        # Get session ID
        row = await conn.fetchrow("SELECT id FROM sessions WHERE chat_id = $1", chat_id)
        if not row:
            await message.reply("No session found. Start one with /start.")
            return
        session_id = str(row["id"])
        count = await delete_all_playlists_in_session(conn, session_id)
        await message.reply(f"Deleted {count} playlist(s) from this session. The session remains active.")


async def cmd_clear(message: Message, bot: Bot) -> None:
    """Clear all data for the current session."""
    chat_id = message.chat.id
    async with bot["db_pool"].acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT id FROM sessions WHERE chat_id = $1", chat_id
            )
            if row:
                session_id = str(row["id"])
                await conn.execute("DELETE FROM sessions WHERE id = $1", session_id)
    await message.reply("Session data cleared. You can start fresh now.")


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

    async with bot["db_pool"].acquire() as conn:
        # Get current session
        session_row = await conn.fetchrow(
            "SELECT id FROM sessions WHERE chat_id = $1", chat_id
        )
        if not session_row:
            await message.reply("No session found. Start one with /start.")
            return

        session_id = str(session_row["id"])

        # Delete playlists with this YouTube ID in this session
        result = await conn.execute(
            "DELETE FROM playlists WHERE session_id = $1 AND youtube_playlist_id = $2",
            session_id,
            youtube_playlist_id,
        )
        # result format: "DELETE <count>"
        count = int(result.split()[1]) if result and result.startswith("DELETE") else 0

        if count == 0:
            await message.reply(
                f"No playlist with YouTube ID '{youtube_playlist_id}' found in this session."
            )
        else:
            await message.reply(
                f"Deleted {count} playlist(s) with YouTube ID '{youtube_playlist_id}'."
            )


async def handle_playlist_url(message: Message, bot: Bot) -> None:
    """Handle any message containing a YouTube playlist URL."""
    text = message.text or message.caption or ""
    url = extract_playlist_url(text)
    if not url:
        return  # Not a playlist URL; ignore.

    chat_id = message.chat.id
    user = message.from_user
    telegram_id = user.id
    username = user.username

    try:
        playlist_info = await fetch_playlist_info(url)
    except Exception as e:
        logger.exception("Failed to fetch playlist from %s", url)
        await message.reply(f"Failed to fetch playlist: {e}")
        return

    async with bot["db_pool"].acquire() as conn:
        async with conn.transaction():
            # Get or create session for this chat
            session = await get_or_create_session(conn, chat_id)
            # Get or create user
            user_obj = await get_or_create_user(conn, session.id, telegram_id, username)
            # Create playlist record
            playlist_obj = await create_playlist(
                conn,
                session_id=session.id,
                user_id=user_obj.id,
                youtube_playlist_id=playlist_info["youtube_playlist_id"],
                title=playlist_info["title"],
                url=playlist_info["url"],
            )
            # Insert videos
            if playlist_info["videos"]:
                await create_videos_bulk(conn, playlist_obj.id, playlist_info["videos"])

            # Compute common videos
            common_videos = await compute_common_videos(conn, session.id)

        # Format reply
        if not common_videos:
            reply_text = "No common videos found across all playlists in this session yet."
        else:
            lines = [f"{video.title}\n{video.url}" for video in common_videos]
            reply_text = "Common videos in this session:\n\n" + "\n".join(lines)

        await message.reply(reply_text)


def create_dispatcher(config: Config) -> Dispatcher:
    """Create and configure the Aiogram Dispatcher."""
    bot = Bot(token=config.telegram_bot_token)
    bot["config"] = config
    dp = Dispatcher()
    dp.bot = bot

    # Register lifecycle hooks
    dp.startup.register(startup)
    dp.shutdown.register(shutdown)

    # Command handlers
    dp.message.register(cmd_start, Command("start"))
    dp.message.register(cmd_playlists, Command("playlists"))
    dp.message.register(cmd_clear_playlists, Command("clear_playlists"))
    dp.message.register(cmd_delete_playlist, Command("delete"))
    dp.message.register(cmd_clear, Command("clear"))

    # Handle any text message that may contain a playlist URL
    dp.message.register(handle_playlist_url, filters.TEXT)

    return dp


async def main() -> None:
    """Application entry point."""
    config = load_config()
    setup_logging(config.log_level)
    dp = create_dispatcher(config)
    try:
        await dp.start_polling()
    finally:
        await dp.storage.close()
        await dp.storage.wait_closed()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())