"""Intersection logic for common videos across playlists in a session."""

from typing import List

import asyncpg

from .database import get_video_sets_for_session, get_videos_by_youtube_ids
from .models import Video


async def compute_common_videos(conn: asyncpg.Connection, session_id: str) -> List[Video]:
    """
    Compute a list of videos that appear in every playlist of the given session.

    Args:
        conn: Active asyncpg connection.
        session_id: UUID of the session.

    Returns:
        List of Video objects (distinct by YouTube video ID) that are present in all playlists.
    """
    video_sets = await get_video_sets_for_session(conn, session_id)
    if not video_sets:
        return []
    # Compute intersection of all sets
    common_ids = set.intersection(*video_sets)
    if not common_ids:
        return []
    return await get_videos_by_youtube_ids(conn, list(common_ids))