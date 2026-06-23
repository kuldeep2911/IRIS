"""Tests for AES-256 at rest."""

from __future__ import annotations

import pytest

from iris.security.crypto import CryptoBox


def test_round_trip():
    box = CryptoBox("correct horse battery staple", "iris-salt")
    token = box.encrypt("my sister is Priya")
    assert token != "my sister is Priya"
    assert box.decrypt_str(token) == "my sister is Priya"


def test_nonce_makes_tokens_unique():
    box = CryptoBox("pw", "salt")
    assert box.encrypt("same") != box.encrypt("same")  # random nonce per call


def test_wrong_passphrase_fails():
    a = CryptoBox("pw-a", "salt")
    b = CryptoBox("pw-b", "salt")
    token = a.encrypt("secret")
    with pytest.raises(Exception):
        b.decrypt(token)


def test_empty_passphrase_rejected():
    with pytest.raises(ValueError):
        CryptoBox("", "salt")
