"""Intersection logic for common videos across users in a session."""

from typing import List

import asyncpg

from .database import get_video_sets_for_session, get_videos_by_youtube_ids
from .models import Video


async def compute_common_videos(conn: asyncpg.Connection, session_id: str) -> List[Video]:
    """Return videos that appear in at least one playlist of every user in the session."""
    video_sets = await get_video_sets_for_session(conn, session_id)
    if not video_sets:
        return []
    common_ids = set.intersection(*video_sets)
    if not common_ids:
        return []
    return await get_videos_by_youtube_ids(conn, list(common_ids))
