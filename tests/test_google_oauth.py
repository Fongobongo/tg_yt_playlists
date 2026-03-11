"""Tests for Google OAuth helpers."""

from types import SimpleNamespace

import pytest

from src.google_oauth import build_google_oauth_url, google_oauth_enabled, sign_google_state, verify_google_state


def test_google_oauth_enabled():
    assert google_oauth_enabled(SimpleNamespace(google_client_id="cid", google_client_secret="secret")) is True
    assert google_oauth_enabled(SimpleNamespace(google_client_id=None, google_client_secret="secret")) is False


def test_google_oauth_state_round_trip():
    state = sign_google_state("test-secret", 123456)
    assert verify_google_state("test-secret", state) == 123456


def test_build_google_oauth_url_contains_redirect_and_scope():
    config = SimpleNamespace(
        google_client_id="cid",
        google_client_secret="secret",
        webhook_base_url="https://example.com",
        webhook_secret="test-secret",
    )

    auth_url = build_google_oauth_url(config, 123456)

    assert auth_url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=cid" in auth_url
    assert "redirect_uri=https%3A%2F%2Fexample.com%2Fauth%2Fgoogle%2Fcallback" in auth_url
    assert "youtube.readonly" in auth_url
