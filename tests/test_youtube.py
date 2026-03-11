"""Tests for upaste playlist fetching."""

import json
from unittest.mock import patch

import pytest

from src.youtube import fetch_playlist_info, normalize_upaste_url

pytestmark = pytest.mark.asyncio


async def test_normalize_upaste_url_supports_regular_and_raw_links():
    assert normalize_upaste_url("https://upaste.de/g3h") == "https://upaste.de/g3h"
    assert normalize_upaste_url("https://upaste.de/raw/g3h") == "https://upaste.de/g3h"
    assert normalize_upaste_url("https://example.com/test") is None


async def test_fetch_playlist_info_from_upaste_json():
    payload = {
        "id": "WL",
        "title": "Watch Later",
        "videos": [
            {"id": "vid1", "titleLong": "First Video"},
            {"id": "vid2", "title": "Second Video"},
        ],
    }

    class MockResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    with patch("src.youtube.urlopen", return_value=MockResponse()):
        result = await fetch_playlist_info("https://upaste.de/g3h")

    assert result["youtube_playlist_id"] == "upaste:WL"
    assert result["title"] == "Watch Later"
    assert result["url"] == "https://upaste.de/g3h"
    assert result["videos"][0]["youtube_video_id"] == "vid1"
    assert result["videos"][1]["title"] == "Second Video"


async def test_fetch_playlist_info_rejects_non_upaste_url():
    with pytest.raises(ValueError, match="Only upaste.de playlist export URLs are supported."):
        await fetch_playlist_info("https://www.youtube.com/playlist?list=PL12345")
