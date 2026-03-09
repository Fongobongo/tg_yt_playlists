"""Domain data models."""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Session:
    """Represents a chat session."""

    id: str  # UUID
    chat_id: int
    created_at: datetime
    short_code: str | None = None


@dataclass
class User:
    """Represents a user within a session."""

    id: str  # UUID
    session_id: str
    telegram_id: int
    username: Optional[str]
    created_at: datetime


@dataclass
class Playlist:
    """Represents a YouTube playlist added by a user."""

    id: str  # UUID
    session_id: str
    user_id: str
    youtube_playlist_id: str
    title: str
    url: str
    created_at: datetime


@dataclass
class Video:
    """Represents a video within a playlist."""

    id: str  # UUID
    playlist_id: str
    youtube_video_id: str
    title: str
    url: str
    position: int
    created_at: datetime