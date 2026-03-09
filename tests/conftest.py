"""Pytest configuration and fixtures."""

import asyncio
import os

import asyncpg
import pytest
from aiogram import Bot
from aiogram.types import Message, User, Chat

from src.config import load_config
from src.database import create_pool, create_tables, close_pool

pytest_plugins = ["pytest_asyncio"]


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def pool():
    """Create a database pool for the test session."""
    cfg = load_config()
    # Allow overriding with TEST_DATABASE_URL
    db_url = os.getenv("TEST_DATABASE_URL", cfg.database_url)
    try:
        pool = await create_pool(db_url)
        await create_tables(pool)
        yield pool
    finally:
        if "pool" in locals():
            await close_pool(pool)


@pytest.fixture
async def conn(pool):
    """Provide a fresh transactional connection that rolls back after each test."""
    async with pool.acquire() as connection:
        async with connection.transaction():
            tr = connection.transaction()
            await tr.start()
            yield connection
            await tr.rollback()


@pytest.fixture
def mock_bot():
    """Provide a mock Bot instance with a db_pool attribute."""
    bot = Bot(token="123:ABC")
    bot.db_pool = None  # will be set by the test if needed
    return bot


@pytest.fixture
def mock_message(monkeypatch):
    """Create a mock Message object with minimal fields."""

    def _make_message(
        text="/start",
        from_user=None,
        chat=None,
        message_id=1,
    ):
        if from_user is None:
            from_user = User(id=123, is_bot=False, first_name="Test")
        if chat is None:
            chat = Chat(id=123, type="private")
        return Message(
            message_id=message_id,
            date=0,
            chat=chat,
            from_user=from_user,
            text=text,
        )

    return _make_message