"""AES-256 encryption at rest (GOLDEN RULE #8 / SaaS-ready).

Encrypts sensitive data (memory rows, credential refs, sensitive table columns)
with AES-256-GCM. The key is DERIVED in memory via PBKDF2-HMAC-SHA256 (500k
iterations) from a passphrase + salt and is never written to disk — only the
ciphertext is stored.

Token format (base64): ``nonce(12) || ciphertext+tag``. A fresh random nonce per
encryption means identical plaintexts produce different tokens.
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from iris.config.settings import get_settings

PBKDF2_ITERATIONS = 500_000
_NONCE_BYTES = 12
_KEY_BYTES = 32  # AES-256


def derive_key(passphrase: str, salt: bytes) -> bytes:
    """PBKDF2-HMAC-SHA256 -> 32-byte AES-256 key (in memory only)."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=_KEY_BYTES,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(passphrase.encode("utf-8"))


class CryptoBox:
    """AES-256-GCM encrypt/decrypt. Key derived once, held only in memory."""

    def __init__(self, passphrase: str, salt: str | bytes) -> None:
        if not passphrase:
            raise ValueError("CryptoBox requires a non-empty passphrase.")
        salt_bytes = salt.encode("utf-8") if isinstance(salt, str) else salt
        self._key = derive_key(passphrase, salt_bytes)

    def encrypt(self, plaintext: str | bytes) -> str:
        data = plaintext.encode("utf-8") if isinstance(plaintext, str) else plaintext
        nonce = os.urandom(_NONCE_BYTES)
        ct = AESGCM(self._key).encrypt(nonce, data, None)
        return base64.b64encode(nonce + ct).decode("ascii")

    def decrypt(self, token: str) -> bytes:
        raw = base64.b64decode(token)
        nonce, ct = raw[:_NONCE_BYTES], raw[_NONCE_BYTES:]
        return AESGCM(self._key).decrypt(nonce, ct, None)

    def decrypt_str(self, token: str) -> str:
        return self.decrypt(token).decode("utf-8")


_box: CryptoBox | None = None


def get_crypto() -> CryptoBox | None:
    """Return the app CryptoBox, or None if no passphrase is configured.

    The passphrase comes from settings (which in prod should be sourced from the
    keychain/Vault, not .env).
    """
    global _box
    if _box is None:
        settings = get_settings()
        if not settings.IRIS_PASSPHRASE:
            return None
        _box = CryptoBox(settings.IRIS_PASSPHRASE, settings.IRIS_CRYPTO_SALT)
    return _box
