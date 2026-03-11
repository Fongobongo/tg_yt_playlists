"""Playlist fetching from YouTube or exported upaste JSON."""

import asyncio
import json
import logging
from typing import Dict, List
from urllib.parse import urlsplit
from urllib.request import urlopen

import yt_dlp

logger = logging.getLogger(__name__)


def normalize_upaste_url(url: str) -> str | None:
    """Return the raw upaste URL if the input points to upaste.de."""
    parsed = urlsplit(url.strip())
    if parsed.netloc not in {"upaste.de", "www.upaste.de"}:
        return None

    path = parsed.path.strip("/")
    if not path:
        return None
    if path.startswith("raw/"):
        paste_id = path.split("/", 1)[1]
    else:
        paste_id = path.split("/", 1)[0]
    if not paste_id:
        return None
    return f"https://upaste.de/raw/{paste_id}"


def _fetch_upaste_playlist_info_sync(source_url: str) -> Dict:
    """Download and parse playlist export JSON from upaste."""
    raw_url = normalize_upaste_url(source_url)
    if raw_url is None:
        raise ValueError("The provided upaste URL is invalid.")

    with urlopen(raw_url, timeout=30) as response:
        payload = response.read().decode("utf-8")
    info = json.loads(payload)
    videos_data = info.get("videos")
    if not isinstance(videos_data, list) or not videos_data:
        raise ValueError("The provided upaste export does not contain any videos.")

    videos: List[dict] = []
    for index, entry in enumerate(videos_data, start=1):
        if not isinstance(entry, dict):
            continue
        video_id = entry.get("id")
        if not video_id:
            continue
        video_title = entry.get("titleLong") or entry.get("title") or "No Title"
        videos.append(
            {
                "youtube_video_id": video_id,
                "title": video_title,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "position": index,
            }
        )

    if not videos:
        raise ValueError("The provided upaste export does not contain any valid videos.")

    playlist_id = info.get("id") or raw_url.rsplit("/", 1)[-1]
    playlist_title = info.get("title") or "Untitled Playlist"
    return {
        "youtube_playlist_id": f"upaste:{playlist_id}",
        "title": playlist_title,
        "url": raw_url,
        "videos": videos,
    }


async def fetch_playlist_info(playlist_url: str) -> Dict:
    """
    Fetch playlist metadata using upaste JSON or yt-dlp.

    Runs yt-dlp in a thread to avoid blocking the event loop.

    Args:
        playlist_url: Full YouTube playlist URL.

    Returns:
        A dictionary with keys:
        - youtube_playlist_id: The YouTube playlist ID.
        - title: Playlist title.
        - url: Original playlist URL.
        - videos: List of video dictionaries with keys: youtube_video_id, title, url, position.

    Raises:
        ValueError: If the URL does not contain a playlist export.
        yt_dlp.utils.DownloadError: On network or extraction failure.
    """
    if normalize_upaste_url(playlist_url) is not None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _fetch_upaste_playlist_info_sync, playlist_url)

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,  # need full info to get titles
        "skip_download": True,
        "force_generic_extractor": False,
        "extract_playlist": True,
    }
    loop = asyncio.get_running_loop()
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = await loop.run_in_executor(None, ydl.extract_info, playlist_url, False)

    if "entries" not in info or not info["entries"]:
        raise ValueError("The provided URL does not seem to be a playlist.")

    playlist_title = info.get("title", "Untitled Playlist")
    youtube_playlist_id = info.get("id", "")

    videos = []
    for entry in info["entries"]:
        if entry is None:
            continue
        video_id = entry.get("id")
        video_title = entry.get("title", "No Title")
        if not video_id:
            continue
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        videos.append(
            {
                "youtube_video_id": video_id,
                "title": video_title,
                "url": video_url,
                "position": entry.get("playlist_index", 0) or 0,
            }
        )

    return {
        "youtube_playlist_id": youtube_playlist_id,
        "title": playlist_title,
        "url": playlist_url,
        "videos": videos,
    }
