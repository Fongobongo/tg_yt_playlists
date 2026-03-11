"""Playlist fetching from exported upaste JSON."""

import asyncio
import html
import json
import re
from typing import Dict, List
from urllib.parse import urlsplit
from urllib.request import urlopen


def normalize_upaste_url(url: str) -> str | None:
    """Return the canonical upaste page URL if the input points to upaste.de."""
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
    return f"https://upaste.de/{paste_id}"


def _extract_json_payload(payload: str) -> dict:
    """Parse JSON directly or extract it from an HTML textarea."""
    try:
        data = json.loads(payload)
        if not isinstance(data, dict):
            raise ValueError("The upaste export must be a JSON object.")
        return data
    except json.JSONDecodeError:
        pass

    match = re.search(r"<textarea[^>]*>(.*?)</textarea>", payload, re.DOTALL | re.IGNORECASE)
    if not match:
        raise ValueError("The upaste page does not contain a readable JSON export.")
    textarea_content = html.unescape(match.group(1)).strip()
    data = json.loads(textarea_content)
    if not isinstance(data, dict):
        raise ValueError("The upaste export must be a JSON object.")
    return data


def _fetch_upaste_playlist_info_sync(source_url: str) -> Dict:
    """Download and parse playlist export JSON from upaste."""
    page_url = normalize_upaste_url(source_url)
    if page_url is None:
        raise ValueError("The provided upaste URL is invalid.")

    last_error: Exception | None = None
    payload = None
    raw_url = page_url.replace("https://upaste.de/", "https://upaste.de/raw/", 1)
    candidate_urls = [raw_url, page_url]

    for candidate_url in candidate_urls:
        try:
            with urlopen(candidate_url, timeout=30) as response:
                payload = response.read().decode("utf-8")
            break
        except Exception as exc:
            last_error = exc

    if payload is None:
        raise ValueError(f"Failed to fetch upaste export: {last_error}")

    info = _extract_json_payload(payload)
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

    playlist_id = info.get("id") or page_url.rsplit("/", 1)[-1]
    playlist_title = info.get("title") or "Untitled Playlist"
    return {
        "youtube_playlist_id": f"upaste:{playlist_id}",
        "title": playlist_title,
        "url": raw_url,
        "videos": videos,
    }


async def fetch_playlist_info(playlist_url: str) -> Dict:
    """
    Fetch playlist metadata from upaste JSON.

    Args:
        playlist_url: upaste playlist export URL.

    Returns:
        A dictionary with keys:
        - youtube_playlist_id: Internal playlist identifier.
        - title: Playlist title.
        - url: Original playlist URL.
        - videos: List of video dictionaries with keys: youtube_video_id, title, url, position.

    Raises:
        ValueError: If the URL does not contain a playlist export.
    """
    if normalize_upaste_url(playlist_url) is None:
        raise ValueError("Only upaste.de playlist export URLs are supported.")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch_upaste_playlist_info_sync, playlist_url)
