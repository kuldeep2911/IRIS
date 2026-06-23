"""Secrets — all site credentials via the OS keychain (GOLDEN RULE #8).

Site passwords / OAuth tokens are stored in the OS keychain, never in code,
prompts, or logs. The MCP servers (and later OAuth flows) retrieve them through
this interface; IRIS's prompts only ever see a *reference*, not the secret.

``SecretStore`` is the swap seam: the keyring backend is the default, and a
Vault / cloud-KMS backend can replace it in ONE place for SaaS — callers use the
module-level ``get_secret`` / ``set_secret`` / ``delete_secret`` helpers.

NOTE: ``GEMINI_API_KEY`` is the one exception — it comes from settings/.env (the
single config source). The log redaction filter ensures it never leaks anyway.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import structlog

log = structlog.get_logger(__name__)

SERVICE_NAME = "iris"


class SecretStore(ABC):
    """Backend-agnostic secret storage (keychain today, Vault/KMS later)."""

    @abstractmethod
    def get(self, name: str) -> str | None: ...

    @abstractmethod
    def set(self, name: str, value: str) -> None: ...

    @abstractmethod
    def delete(self, name: str) -> None: ...


class KeyringSecretStore(SecretStore):
    """OS keychain backend (Windows Credential Manager / macOS Keychain / etc)."""

    def __init__(self, service: str = SERVICE_NAME) -> None:
        self._service = service

    def get(self, name: str) -> str | None:
        try:
            import keyring

            return keyring.get_password(self._service, name)
        except Exception as exc:  # noqa: BLE001 — missing backend must not crash
            log.warning("secrets.get_failed", name=name, error=str(exc))
            return None

    def set(self, name: str, value: str) -> None:
        import keyring

        keyring.set_password(self._service, name, value)

    def delete(self, name: str) -> None:
        try:
            import keyring

            keyring.delete_password(self._service, name)
        except Exception as exc:  # noqa: BLE001
            log.warning("secrets.delete_failed", name=name, error=str(exc))


class VaultSecretStore(SecretStore):
    """Vault / cloud-KMS backend (SaaS) — the swap target for multi-tenant.

    Stubbed: wire to HashiCorp Vault / AWS Secrets Manager here and flip
    ``get_secret_store`` to return this. The rest of IRIS is unchanged because
    everything goes through the :class:`SecretStore` interface (GOLDEN RULE #10).
    """

    def __init__(self, *, namespace: str = "iris") -> None:
        self._namespace = namespace

    def get(self, name: str) -> str | None:  # pragma: no cover - SaaS stub
        raise NotImplementedError("Configure a Vault/KMS backend for SaaS deployments.")

    def set(self, name: str, value: str) -> None:  # pragma: no cover - SaaS stub
        raise NotImplementedError("Configure a Vault/KMS backend for SaaS deployments.")

    def delete(self, name: str) -> None:  # pragma: no cover - SaaS stub
        raise NotImplementedError("Configure a Vault/KMS backend for SaaS deployments.")


# ── module-level access (the ONE place to swap the backend) ──────────────────
_store: SecretStore | None = None


def get_secret_store() -> SecretStore:
    global _store
    if _store is None:
        # Single source of truth for the backend. Swap to VaultSecretStore()
        # for SaaS — no other code changes.
        _store = KeyringSecretStore()
    return _store


def get_secret(name: str) -> str | None:
    return get_secret_store().get(name)


def set_secret(name: str, value: str) -> None:
    get_secret_store().set(name, value)


def delete_secret(name: str) -> None:
    get_secret_store().delete(name)
