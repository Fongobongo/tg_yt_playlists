"""Tests for YouTube playlist fetching."""

from unittest.mock import MagicMock, patch

import pytest

from src.youtube import fetch_playlist_info

pytestmark = pytest.mark.asyncio


async def test_fetch_playlist_info_success():
    # Simulate yt-dlp info dict
    mock_info = {
        "id": "PL12345",
        "title": "My Playlist",
        "entries": [
            {
                "id": "vid1",
                "title": "First Video",
                "playlist_index": 1,
            },
            {
                "id": "vid2",
                "title": "Second Video",
                "playlist_index": 2,
            },
        ],
    }

    class MockYoutubeDL:
        def __init__(self, opts):
            pass

        def extract_info(self, url, download):
            return mock_info

    with patch("src.youtube.yt_dlp.YoutubeDL", MockYoutubeDL):
        result = await fetch_playlist_info("https://www.youtube.com/playlist?list=PL12345")

    assert result["youtube_playlist_id"] == "PL12345"
    assert result["title"] == "My Playlist"
    assert result["url"] == "https://www.youtube.com/playlist?list=PL12345"
    assert len(result["videos"]) == 2
    assert result["videos"][0] == {
        "youtube_video_id": "vid1",
        "title": "First Video",
        "url": "https://www.youtube.com/watch?v=vid1",
        "position": 1,
    }
    assert result["videos"][1]["youtube_video_id"] == "vid2"


async def test_fetch_playlist_info_no_entries():
    """Raise ValueError if URL does not contain a playlist."""
    mock_info = {"title": "Single Video", "entries": None}

    class MockYoutubeDL:
        def __init__(self, opts):
            pass

        def extract_info(self, url, download):
            return mock_info

    with patch("src.youtube.yt_dlp.YoutubeDL", MockYoutubeDL):
        with pytest.raises(ValueError, match="does not seem to be a playlist"):
            await fetch_playlist_info("https://www.youtube.com/watch?v=abc")


async def test_fetch_playlist_info_download_error():
    """Propagate yt-dlp errors."""
    class MockYoutubeDL:
        def __init__(self, opts):
            pass

        def extract_info(self, url, download):
            raise Exception("network failure")

    with patch("src.youtube.yt_dlp.YoutubeDL", MockYoutubeDL):
        with pytest.raises(Exception, match="network failure"):
            await fetch_playlist_info("https://www.youtube.com/playlist?list=PL123")