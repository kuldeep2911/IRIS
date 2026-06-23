"""Generic OAuth2 engine — authorization-code + PKCE + refresh (THE FIX).

Provider-agnostic: driven entirely by a connector's catalog ``AuthSpec``. Written
once; every OAuth connector reuses it. Fixes the common failures:
- ONE exact redirect URI everywhere (``settings.CONNECTOR_REDIRECT_URI``).
- signed ``state`` (HMAC) for CSRF; tampered/expired state is rejected.
- PKCE S256 where the provider supports it.
- Google's ``access_type=offline`` + ``prompt=consent`` (from the catalog) so a
  refresh_token is issued; refresh tokens are persisted and auto-refreshed.
- client_id/secret read from the env vars named in the spec (clear error if missing).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import structlog

from iris.config.settings import get_settings
from iris.connectors.catalog import AuthSpec, ConnectorSpec, get_connector
from iris.connectors.token_vault import TokenBundle, TokenVault
from iris.data.db import session_scope

log = structlog.get_logger(__name__)

_STATE_TTL_SECONDS = 300  # 5 min


class OAuthError(RuntimeError):
    """OAuth flow failure (bad state, missing creds, token exchange failed)."""


class ReconnectRequired(RuntimeError):
    """A token could not be refreshed (revoked/expired) — user must reconnect."""


@dataclass
class _PendingAuth:
    verifier: str | None
    created_at: float


# nonce -> pending PKCE verifier (short-TTL, in-memory; infra state, not request state).
_pending: dict[str, _PendingAuth] = {}


def _state_secret() -> bytes:
    s = get_settings()
    return (s.CONNECTOR_STATE_SECRET or s.IRIS_PASSPHRASE or s.IRIS_CRYPTO_SALT).encode("utf-8")


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign_state(payload: dict) -> str:
    body = _b64u(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_state_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def _verify_state(state: str) -> dict:
    try:
        body, sig = state.split(".", 1)
    except ValueError as exc:
        raise OAuthError("malformed state") from exc
    expected = hmac.new(_state_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise OAuthError("state signature mismatch (possible CSRF)")
    return json.loads(_b64u_decode(body))


def _make_pkce() -> tuple[str, str]:
    verifier = _b64u(secrets.token_bytes(32))
    challenge = _b64u(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _client_creds(spec: ConnectorSpec) -> tuple[str, str]:
    auth = spec.auth
    cid = os.environ.get(auth.client_id_env or "", "")
    csec = os.environ.get(auth.client_secret_env or "", "")
    if not cid or not csec:
        raise OAuthError(
            f"connector '{spec.id}': set env {auth.client_id_env} and {auth.client_secret_env} "
            "to the provider's OAuth client id/secret."
        )
    return cid, csec


class OAuthEngine:
    """Stateless engine; collaborators (vault) are injectable for tests."""

    def __init__(self, vault: TokenVault | None = None) -> None:
        self._vault = vault or TokenVault()

    # ── 1. build the authorize URL ────────────────────────────────────────────
    def build_authorize_url(
        self, spec: ConnectorSpec, tenant_id: str, user_id: str | None
    ) -> tuple[str, str | None]:
        auth = spec.auth
        cid, _ = _client_creds(spec)
        nonce = secrets.token_urlsafe(16)
        state = _sign_state(
            {"c": spec.id, "t": tenant_id, "u": user_id or "", "n": nonce}
        )
        verifier = challenge = None
        if auth.pkce:
            verifier, challenge = _make_pkce()
        _gc_pending()
        _pending[nonce] = _PendingAuth(verifier=verifier, created_at=time.time())

        params = {
            "client_id": cid,
            "redirect_uri": get_settings().CONNECTOR_REDIRECT_URI,
            "response_type": "code",
            "scope": auth.scope_separator.join(auth.scopes),
            "state": state,
            **auth.extra_authorize_params,
        }
        if challenge:
            params["code_challenge"] = challenge
            params["code_challenge_method"] = "S256"
        return f"{auth.authorize_url}?{urlencode(params)}", verifier

    # ── 2. handle the provider callback ───────────────────────────────────────
    async def handle_callback(self, code: str, state: str):
        payload = _verify_state(state)
        connector_id, tenant_id, user_id, nonce = (
            payload["c"], payload["t"], payload["u"] or None, payload["n"]
        )
        pending = _pending.pop(nonce, None)
        if pending is None or time.time() - pending.created_at > _STATE_TTL_SECONDS:
            raise OAuthError("state expired or unknown — restart the connect flow")

        spec = get_connector(connector_id)
        cid, csec = _client_creds(spec)
        redirect = get_settings().CONNECTOR_REDIRECT_URI

        import httpx

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect,
            "client_id": cid,
            "client_secret": csec,
        }
        if pending.verifier:
            data["code_verifier"] = pending.verifier

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                spec.auth.token_url, data=data,
                headers={"Accept": "application/json"},
            )
            if resp.status_code >= 400:
                raise OAuthError(f"token exchange failed ({resp.status_code}): {resp.text[:200]}")
            tok = resp.json()
            bundle = _bundle_from_token_response(tok, spec.auth)
            account_label = await self._fetch_account_label(client, spec.auth, bundle.access_token)

        ref = self._vault.store_tokens(tenant_id, user_id, connector_id, bundle)
        async with session_scope() as s:
            from iris.connectors.repo import ConnectionRepo

            conn = await ConnectionRepo(s).upsert_connection(
                tenant_id, user_id, connector_id,
                status="connected",
                scopes_granted=bundle.scope or " ".join(spec.auth.scopes),
                account_label=account_label,
                credentials_ref=ref,
            )
            s.expunge(conn)
            return conn

    # ── 3. a always-valid access token (auto-refresh) ─────────────────────────
    async def get_valid_access_token(self, connection) -> str:
        if not connection.credentials_ref:
            raise ReconnectRequired(f"{connection.connector_id}: no stored token")
        bundle = self._vault.get_tokens(connection.credentials_ref)
        if not bundle.is_expired() or not bundle.refresh_token:
            return bundle.access_token

        spec = get_connector(connection.connector_id)
        cid, csec = _client_creds(spec)
        import httpx

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    spec.auth.token_url,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": bundle.refresh_token,
                        "client_id": cid,
                        "client_secret": csec,
                    },
                    headers={"Accept": "application/json"},
                )
            if resp.status_code >= 400:
                raise OAuthError(f"refresh failed ({resp.status_code})")
            tok = resp.json()
            new_access = tok["access_token"]
            new_expires = time.time() + float(tok.get("expires_in", 3600))
            self._vault.update_access_token(connection.credentials_ref, new_access, new_expires)
            return new_access
        except Exception as exc:  # noqa: BLE001 — revoked/invalid -> reconnect
            async with session_scope() as s:
                from iris.connectors.repo import ConnectionRepo

                await ConnectionRepo(s).set_error(
                    connection.tenant_id, connection.user_id, connection.connector_id,
                    f"token refresh failed: {exc}",
                )
            raise ReconnectRequired(f"{connection.connector_id}: reconnect required") from exc

    @staticmethod
    async def _fetch_account_label(client, auth: AuthSpec, access_token: str) -> str | None:
        if not auth.userinfo_url:
            return None
        try:
            r = await client.get(
                auth.userinfo_url, headers={"Authorization": f"Bearer {access_token}"}
            )
            if r.status_code < 400:
                return r.json().get(auth.account_field or "email")
        except Exception:  # noqa: BLE001
            return None
        return None


def _bundle_from_token_response(tok: dict, auth: AuthSpec) -> TokenBundle:
    expires_at = None
    if tok.get("expires_in"):
        expires_at = time.time() + float(tok["expires_in"])
    return TokenBundle(
        access_token=tok["access_token"],
        refresh_token=tok.get("refresh_token"),
        expires_at=expires_at,
        token_type=tok.get("token_type", "Bearer"),
        scope=tok.get("scope"),
    )


def _gc_pending() -> None:
    now = time.time()
    for nonce in [n for n, p in _pending.items() if now - p.created_at > _STATE_TTL_SECONDS]:
        _pending.pop(nonce, None)
