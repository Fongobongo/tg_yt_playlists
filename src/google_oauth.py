"""Google OAuth and YouTube playlist helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from aiohttp import ClientSession


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_PLAYLISTS_URL = "https://www.googleapis.com/youtube/v3/playlists"
GOOGLE_OAUTH_SCOPES = "openid https://www.googleapis.com/auth/youtube.readonly"


@dataclass
class YoutubePlaylistSummary:
    """Small subset of playlist data shown back to the user."""

    title: str
    video_count: int


def google_oauth_enabled(config: Any) -> bool:
    """Return whether Google OAuth is configured."""
    return bool(getattr(config, "google_client_id", None) and getattr(config, "google_client_secret", None))


def build_google_oauth_url(config: Any, telegram_id: int) -> str:
    """Build the Google OAuth URL for a Telegram user."""
    state = sign_google_state(config.webhook_secret, telegram_id)
    query = urlencode(
        {
            "client_id": config.google_client_id,
            "redirect_uri": f"{config.webhook_base_url}/auth/google/callback",
            "response_type": "code",
            "scope": GOOGLE_OAUTH_SCOPES,
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{GOOGLE_AUTH_URL}?{query}"


def sign_google_state(secret: str, telegram_id: int) -> str:
    """Create a signed OAuth state payload."""
    payload = {
        "telegram_id": telegram_id,
        "issued_at": int(time.time()),
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw + b"." + signature).decode("ascii")


def verify_google_state(secret: str, state: str, max_age_seconds: int = 600) -> int:
    """Verify a signed OAuth state and return the Telegram user ID."""
    decoded = base64.urlsafe_b64decode(state.encode("ascii"))
    if len(decoded) <= 33 or decoded[-33] != 46:
        raise ValueError("Invalid OAuth state payload.")
    raw = decoded[:-33]
    signature = decoded[-32:]
    expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid OAuth state signature.")

    payload = json.loads(raw.decode("utf-8"))
    issued_at = int(payload["issued_at"])
    if int(time.time()) - issued_at > max_age_seconds:
        raise ValueError("OAuth state expired.")
    return int(payload["telegram_id"])


async def exchange_google_code_for_token(config: Any, code: str) -> dict:
    """Exchange an OAuth code for a Google access token."""
    async with ClientSession() as session:
        async with session.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": config.google_client_id,
                "client_secret": config.google_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": f"{config.webhook_base_url}/auth/google/callback",
            },
            timeout=30,
        ) as response:
            payload = await response.json()
            if response.status >= 400:
                raise ValueError(payload.get("error_description") or payload.get("error") or "Token exchange failed.")
            return payload


async def fetch_youtube_playlists(access_token: str) -> tuple[int, list[YoutubePlaylistSummary]]:
    """Fetch a small list of the user's playlists from YouTube Data API."""
    params = {
        "part": "snippet,contentDetails",
        "mine": "true",
        "maxResults": "10",
    }
    async with ClientSession() as session:
        async with session.get(
            YOUTUBE_PLAYLISTS_URL,
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=30,
        ) as response:
            payload = await response.json()
            if response.status >= 400:
                error = payload.get("error", {})
                raise ValueError(error.get("message") or "Failed to fetch YouTube playlists.")

    page_info = payload.get("pageInfo", {})
    total = int(page_info.get("totalResults", 0))
    items = payload.get("items", [])
    playlists = [
        YoutubePlaylistSummary(
            title=item.get("snippet", {}).get("title", "Untitled playlist"),
            video_count=int(item.get("contentDetails", {}).get("itemCount", 0)),
        )
        for item in items
    ]
    return total, playlists
