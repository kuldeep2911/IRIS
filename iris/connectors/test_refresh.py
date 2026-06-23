"""Token-refresh test — an expired OAuth token is refreshed transparently (no net)."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from iris.connectors.oauth import OAuthEngine
from iris.connectors.token_vault import TokenBundle, TokenVault
from iris.security.crypto import CryptoBox


class _FakeStore:
    def __init__(self):
        self._d = {}

    def get(self, n):
        return self._d.get(n)

    def set(self, n, v):
        self._d[n] = v

    def delete(self, n):
        self._d.pop(n, None)


class _FakeResp:
    status_code = 200

    def json(self):
        return {"access_token": "fresh-access", "expires_in": 3600}


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        return _FakeResp()


@pytest.mark.asyncio
async def test_expired_oauth_token_is_refreshed(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "csec")
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)

    vault = TokenVault(store=_FakeStore(), crypto=CryptoBox("pw", "salt"))
    ref = vault.store_tokens("local", "u1", "gmail", TokenBundle(
        access_token="stale", refresh_token="r1", expires_at=time.time() - 100))  # expired

    conn = SimpleNamespace(
        tenant_id="local", user_id="u1", connector_id="gmail", credentials_ref=ref)

    token = await OAuthEngine(vault).get_valid_access_token(conn)
    assert token == "fresh-access"
    # the new token is persisted in the vault
    assert vault.get_tokens(ref).access_token == "fresh-access"
