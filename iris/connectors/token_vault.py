"""TokenVault — encrypted connector tokens in the OS keychain (security boundary).

Tokens NEVER touch the database in plaintext or appear in logs. A token bundle is
JSON-serialised, AES-256 encrypted (reusing ``security/crypto.py``) and stored in
the OS keychain (``security/secrets.py``) under a deterministic ref
``iris:{tenant}:{user}:{connector}``. The DB only ever stores that ref.

Decryption failure RAISES :class:`TokenVaultError` (never returns None) so a
corrupt/missing token surfaces as a clear "reconnect needed" rather than a
confusing downstream failure.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from iris.security.crypto import CryptoBox, get_crypto
from iris.security.secrets import SecretStore, get_secret_store


class TokenVaultError(RuntimeError):
    """Token missing/corrupt — the user must reconnect this app."""


@dataclass
class TokenBundle:
    access_token: str
    refresh_token: str | None = None
    expires_at: float | None = None     # epoch seconds
    token_type: str = "Bearer"
    scope: str | None = None

    def is_expired(self, skew_seconds: int = 60) -> bool:
        return self.expires_at is not None and time.time() >= (self.expires_at - skew_seconds)


class TokenVault:
    """Encrypted token storage. Backend (keychain) + crypto are injectable for tests."""

    def __init__(self, store: SecretStore | None = None, crypto: CryptoBox | None = None) -> None:
        self._store = store or get_secret_store()
        # If no passphrase is configured, the OS keychain still encrypts at rest;
        # the AES layer is added when IRIS_PASSPHRASE is set (prod).
        self._crypto = crypto if crypto is not None else get_crypto()

    @staticmethod
    def ref_for(tenant_id: str, user_id: str | None, connector_id: str) -> str:
        return f"iris:{tenant_id}:{user_id or '-'}:{connector_id}"

    def store_tokens(
        self, tenant_id: str, user_id: str | None, connector_id: str,
        bundle: TokenBundle | dict,
    ) -> str:
        ref = self.ref_for(tenant_id, user_id, connector_id)
        self._put(ref, _as_bundle(bundle))
        return ref

    def get_tokens(self, credentials_ref: str) -> TokenBundle:
        blob = self._store.get(credentials_ref)
        if blob is None:
            raise TokenVaultError(f"no tokens for {credentials_ref!r}; reconnect needed")
        try:
            payload = self._crypto.decrypt_str(blob) if self._crypto else blob
            data = json.loads(payload)
        except Exception as exc:  # noqa: BLE001 — corrupt token must surface clearly
            raise TokenVaultError(
                f"could not decrypt tokens for {credentials_ref!r}; reconnect needed"
            ) from exc
        return TokenBundle(**data)

    def delete_tokens(self, credentials_ref: str) -> None:
        self._store.delete(credentials_ref)

    def update_access_token(
        self, credentials_ref: str, new_access_token: str, new_expires_at: float | None
    ) -> None:
        bundle = self.get_tokens(credentials_ref)
        bundle.access_token = new_access_token
        bundle.expires_at = new_expires_at
        self._put(credentials_ref, bundle)

    # ── internals ─────────────────────────────────────────────────────────────
    def _put(self, ref: str, bundle: TokenBundle) -> None:
        payload = json.dumps(asdict(bundle))
        blob = self._crypto.encrypt(payload) if self._crypto else payload
        self._store.set(ref, blob)


def _as_bundle(bundle: TokenBundle | dict) -> TokenBundle:
    return bundle if isinstance(bundle, TokenBundle) else TokenBundle(**bundle)
