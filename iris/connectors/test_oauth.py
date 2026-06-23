"""Tests for the OAuth2 engine — state sign/verify, PKCE, authorize URL (no network)."""

from __future__ import annotations

import base64
import hashlib
import os

import pytest

from iris.connectors.catalog import get_connector
from iris.connectors.oauth import (
    OAuthEngine,
    OAuthError,
    _make_pkce,
    _sign_state,
    _verify_state,
)


def test_state_sign_verify_round_trip():
    state = _sign_state({"c": "gmail", "t": "local", "u": "u1", "n": "abc"})
    payload = _verify_state(state)
    assert payload["c"] == "gmail" and payload["t"] == "local"


def test_tampered_state_rejected():
    state = _sign_state({"c": "gmail", "t": "local", "u": "u1", "n": "abc"})
    body, sig = state.split(".", 1)
    tampered = body + "." + ("0" * len(sig))
    with pytest.raises(OAuthError):
        _verify_state(tampered)


def test_pkce_s256_challenge():
    verifier, challenge = _make_pkce()
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    assert challenge == expected


def test_build_authorize_url_has_google_offline_consent_and_pkce(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-secret")
    engine = OAuthEngine()
    url, verifier = engine.build_authorize_url(get_connector("gmail"), "local", "u1")
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "code_challenge=" in url and "code_challenge_method=S256" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fconnectors%2Fcallback" in url
    assert "state=" in url
    assert verifier is not None


def test_missing_client_creds_errors():
    os.environ.pop("GOOGLE_CLIENT_ID", None)
    os.environ.pop("GOOGLE_CLIENT_SECRET", None)
    engine = OAuthEngine()
    with pytest.raises(OAuthError):
        engine.build_authorize_url(get_connector("gmail"), "local", "u1")
