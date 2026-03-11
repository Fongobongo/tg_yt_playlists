"""Pytest configuration and fixtures."""

import os

import pytest
from aiogram import Bot

from src.database import close_pool, create_pool, create_tables

pytest_plugins = ["pytest_asyncio"]


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Return the test database URL or skip DB-backed tests."""
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not set")
    return database_url


@pytest.fixture(scope="session")
async def pool(test_database_url):
    """Create a database pool for integration tests."""
    pool = await create_pool(test_database_url)
    await create_tables(pool)
    try:
        yield pool
    finally:
        await close_pool(pool)


@pytest.fixture
async def conn(pool):
    """Provide a transactional connection per test."""
    async with pool.acquire() as connection:
        tx = connection.transaction()
        await tx.start()
        try:
            yield connection
        finally:
            await tx.rollback()


@pytest.fixture
def mock_bot():
    """Provide a Bot instance with mutable attributes used by handlers."""
    bot = Bot(token="123:ABC")
    bot.db_pool = None
    bot.my_username = "test_bot"
    return bot
