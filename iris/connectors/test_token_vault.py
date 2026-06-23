"""Tests for the connector token vault (no network, no real keychain)."""

from __future__ import annotations

import pytest

from iris.connectors.token_vault import TokenBundle, TokenVault, TokenVaultError
from iris.security.crypto import CryptoBox
from iris.security.redaction import REDACTED, _redact_text


class _FakeStore:
    """In-memory SecretStore stand-in so tests never touch the real keychain."""

    def __init__(self) -> None:
        self._d: dict[str, str] = {}

    def get(self, name):
        return self._d.get(name)

    def set(self, name, value):
        self._d[name] = value

    def delete(self, name):
        self._d.pop(name, None)


def _vault() -> TokenVault:
    return TokenVault(store=_FakeStore(), crypto=CryptoBox("test-pass", "test-salt"))


def test_store_get_round_trip():
    v = _vault()
    ref = v.store_tokens("local", "u1", "gmail", TokenBundle(
        access_token="ya29.SECRET", refresh_token="1//REFRESH", expires_at=123.0, scope="gmail"))
    assert ref == "iris:local:u1:gmail"
    got = v.get_tokens(ref)
    assert got.access_token == "ya29.SECRET"
    assert got.refresh_token == "1//REFRESH"
    assert got.scope == "gmail"


def test_encrypted_at_rest():
    store = _FakeStore()
    v = TokenVault(store=store, crypto=CryptoBox("pw", "salt"))
    ref = v.store_tokens("local", "u1", "gmail", {"access_token": "PLAINTEXT_SECRET"})
    # the raw stored blob must NOT contain the plaintext token
    assert "PLAINTEXT_SECRET" not in store.get(ref)


def test_update_access_token():
    v = _vault()
    ref = v.store_tokens("local", "u1", "gmail", TokenBundle(access_token="old", expires_at=1.0))
    v.update_access_token(ref, "new-token", 999.0)
    got = v.get_tokens(ref)
    assert got.access_token == "new-token" and got.expires_at == 999.0


def test_missing_ref_raises():
    v = _vault()
    with pytest.raises(TokenVaultError):
        v.get_tokens("iris:local:u1:nope")


def test_deleted_ref_raises():
    v = _vault()
    ref = v.store_tokens("local", "u1", "gmail", {"access_token": "x"})
    v.delete_tokens(ref)
    with pytest.raises(TokenVaultError):
        v.get_tokens(ref)


def test_redaction_hides_tokens():
    assert REDACTED in _redact_text("access_token=ya29.aVeryLongSecretValue123")
    assert REDACTED in _redact_text("Authorization: Bearer abc.def.ghi")
    assert "ya29.aVeryLongSecretValue123" not in _redact_text("access_token=ya29.aVeryLongSecretValue123")
