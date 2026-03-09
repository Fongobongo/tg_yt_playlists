"""YouTube playlist fetching using yt-dlp."""

import asyncio
import logging
from typing import Dict, List

import yt_dlp

logger = logging.getLogger(__name__)


async def fetch_playlist_info(playlist_url: str) -> Dict:
    """
    Fetch playlist metadata using yt-dlp.

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
        ValueError: If the URL does not contain a playlist.
        yt_dlp.utils.DownloadError: On network or extraction failure.
    """
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

    if "entries" not in info:
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