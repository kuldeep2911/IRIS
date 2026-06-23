"""PAT / API-key connectors — the non-OAuth path.

Many dev tools (GitHub PAT, Cloudflare token, etc.) authenticate with a static
token. We validate it with one cheap authenticated call (if the catalog gives a
``validate_url``), store it in the keychain via the TokenVault, and upsert the
connection — rejecting obviously-invalid tokens early.
"""

from __future__ import annotations

import structlog

from iris.connectors.catalog import ConnectorSpec
from iris.connectors.token_vault import TokenBundle, TokenVault
from iris.data.db import session_scope

log = structlog.get_logger(__name__)


class TokenAuthError(RuntimeError):
    """The provided PAT/API key was rejected."""


async def connect_with_token(
    spec: ConnectorSpec,
    tenant_id: str,
    user_id: str | None,
    raw_token: str,
    account_label: str | None = None,
    vault: TokenVault | None = None,
):
    """Validate + store a PAT/API key, then upsert the connection. Returns Connection."""
    if spec.auth.type not in ("pat", "api_key"):
        raise TokenAuthError(f"connector '{spec.id}' is not a token connector")
    if not (raw_token or "").strip():
        raise TokenAuthError("empty token")

    # Validate against the provider (cheap authed call) when we know how.
    if spec.auth.validate_url:
        account_label = account_label or await _validate(spec, raw_token)

    vault = vault or TokenVault()
    bundle = TokenBundle(access_token=raw_token.strip(), token_type="token")
    ref = vault.store_tokens(tenant_id, user_id, spec.id, bundle)

    async with session_scope() as s:
        from iris.connectors.repo import ConnectionRepo

        conn = await ConnectionRepo(s).upsert_connection(
            tenant_id, user_id, spec.id,
            status="connected",
            account_label=account_label,
            credentials_ref=ref,
        )
        s.expunge(conn)
        return conn


async def _validate(spec: ConnectorSpec, raw_token: str) -> str | None:
    """One authed GET to the validate URL; raise if rejected. Returns account label."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                spec.auth.validate_url,
                headers={"Authorization": f"Bearer {raw_token}",
                         "Accept": "application/json"},
            )
    except Exception as exc:  # noqa: BLE001
        raise TokenAuthError(f"could not reach {spec.id} to validate token: {exc}") from exc
    if r.status_code in (401, 403):
        raise TokenAuthError(f"{spec.id} rejected the token ({r.status_code})")
    if r.status_code >= 400:
        raise TokenAuthError(f"{spec.id} validation failed ({r.status_code})")
    try:
        return r.json().get(spec.auth.account_field or "login")
    except Exception:  # noqa: BLE001
        return None
