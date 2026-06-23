"""Connectors API — /connectors routes incl. the OAuth callback.

Tenant + user scoped via the existing middleware. The callback validates the
signed ``state`` (its security) and is otherwise open so the provider redirect
isn't blocked. Every failure returns a structured ``{error, detail,
reconnect_url}`` so the UI can show something actionable.
"""

from __future__ import annotations

import html

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from iris.connectors.catalog import get_connector
from iris.connectors.oauth import OAuthError, ReconnectRequired
from iris.connectors.service import ConnectorService

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/connectors", tags=["connectors"])


class TokenIn(BaseModel):
    token: str


def _service(request: Request) -> ConnectorService:
    return ConnectorService(
        tenant_id=request.state.tenant_id,
        user_id=getattr(request.app.state, "default_user_id", None),
        mcp=getattr(request.app.state, "mcp", None),
    )


def _error(status: int, error: str, detail: str = "", reconnect_url: str | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": error, "detail": detail, "reconnect_url": reconnect_url},
    )


@router.get("")
async def list_connectors(request: Request) -> list[dict]:
    return await _service(request).list_available()


@router.post("/{connector_id}/connect")
async def connect(connector_id: str, request: Request):
    try:
        spec = get_connector(connector_id)
    except KeyError:
        return _error(404, "unknown_connector", connector_id)

    if spec.auth.type == "oauth2":
        try:
            url = await _service(request).begin_oauth(connector_id)
            return {"authorize_url": url}
        except OAuthError as exc:
            return _error(400, "oauth_config_error", str(exc))
    # pat / api_key path
    return {
        "needs_token": True,
        "help_url": spec.auth.help_url,
        "label": spec.auth.token_label or "API token",
    }


@router.post("/{connector_id}/token")
async def submit_token(connector_id: str, body: TokenIn, request: Request):
    try:
        conn = await _service(request).connect_token(connector_id, body.token)
        return {"status": conn.status, "account_label": conn.account_label}
    except KeyError:
        return _error(404, "unknown_connector", connector_id)
    except Exception as exc:  # noqa: BLE001 — surface a clear, actionable error
        return _error(400, "token_rejected", str(exc))


@router.get("/callback")
async def callback(request: Request):
    """Provider redirect target. Validates signed state, exchanges the code."""
    params = request.query_params
    if params.get("error"):
        return _callback_html(False, detail=params.get("error", "access_denied"))
    code, state = params.get("code"), params.get("state")
    if not code or not state:
        return _callback_html(False, detail="missing code/state")
    try:
        conn = await _service(request).complete_oauth(code, state)
        return _callback_html(True, connector=conn.connector_id, account=conn.account_label)
    except OAuthError as exc:
        # State tampering / expiry / config error -> 400, NO token exchange happened.
        return _callback_html(False, detail=str(exc), status=400)
    except Exception as exc:  # noqa: BLE001
        return _callback_html(False, detail=str(exc), status=400)


@router.post("/{connector_id}/disconnect")
async def disconnect(connector_id: str, request: Request):
    try:
        await _service(request).disconnect(connector_id)
        return {"status": "disconnected"}
    except Exception as exc:  # noqa: BLE001
        return _error(400, "disconnect_failed", str(exc))


@router.get("/{connector_id}/status")
async def status(connector_id: str, request: Request):
    try:
        return await _service(request).status(connector_id)
    except KeyError:
        return _error(404, "unknown_connector", connector_id)


def _callback_html(ok: bool, connector: str = "", account: str | None = None,
                   detail: str = "", status: int = 200) -> HTMLResponse:
    """Tiny page that messages the opener (dashboard) then closes itself."""
    safe_detail = html.escape(detail)
    safe_connector = html.escape(connector)
    safe_account = html.escape(account or "")
    if ok:
        body = f"""
        <h2>Connected!</h2>
        <p>{safe_connector} {('· ' + safe_account) if safe_account else ''} is connected.
        You can close this window.</p>
        <script>
          try {{ window.opener && window.opener.postMessage(
            {{type:'iris-connector', status:'connected', connector:'{safe_connector}'}}, '*'); }} catch(e){{}}
          setTimeout(function(){{ window.close(); }}, 800);
        </script>"""
    else:
        body = f"""
        <h2>Connection failed</h2>
        <p>{safe_detail or 'The connection could not be completed.'}</p>
        <p><a href="javascript:window.close()">Close</a> and try again from the Connections page.</p>
        <script>
          try {{ window.opener && window.opener.postMessage(
            {{type:'iris-connector', status:'error', detail:'{safe_detail}'}}, '*'); }} catch(e){{}}
        </script>"""
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>IRIS Connector</title>
      <style>body{{background:#0a0a0f;color:#e5e7eb;font-family:system-ui;display:grid;
      place-items:center;height:100vh;margin:0;text-align:center}}a{{color:#06B6D4}}</style></head>
      <body><div>{body}</div></body></html>"""
    return HTMLResponse(content=page, status_code=status)
