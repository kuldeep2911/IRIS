"""Connector catalog loader + validation.

Loads ``catalog.yaml`` and validates every entry against Pydantic models. A
malformed entry fails LOUDLY at load time (never silently skipped) so a bad
connector spec can't ship.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

_CATALOG_PATH = Path(__file__).resolve().parent / "catalog.yaml"

AuthType = Literal["oauth2", "pat", "api_key", "none"]
Transport = Literal["stdio", "sse"]
TokenInjection = Literal["env", "header", "arg"]


class AuthSpec(BaseModel):
    type: AuthType

    # ── oauth2 ────────────────────────────────────────────────────────────
    authorize_url: str | None = None
    token_url: str | None = None
    scopes: list[str] = Field(default_factory=list)
    pkce: bool = False
    extra_authorize_params: dict[str, str] = Field(default_factory=dict)
    client_id_env: str | None = None
    client_secret_env: str | None = None
    userinfo_url: str | None = None
    scope_separator: str = " "
    account_field: str | None = None

    # ── pat / api_key ─────────────────────────────────────────────────────
    help_url: str | None = None
    token_label: str | None = None
    validate_url: str | None = None

    @model_validator(mode="after")
    def _check_required(self) -> "AuthSpec":
        if self.type == "oauth2":
            missing = [
                k for k in ("authorize_url", "token_url", "client_id_env", "client_secret_env")
                if not getattr(self, k)
            ]
            if missing:
                raise ValueError(f"oauth2 connector missing {missing}")
        return self


class McpSpec(BaseModel):
    transport: Transport
    command: str | None = None
    url: str | None = None
    token_injection: TokenInjection = "env"
    token_env_var: str | None = None

    @model_validator(mode="after")
    def _check_transport(self) -> "McpSpec":
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio MCP server requires a command")
        if self.transport == "sse" and not self.url:
            raise ValueError("sse MCP server requires a url")
        return self


class ConnectorSpec(BaseModel):
    id: str
    name: str
    category: str
    icon: str | None = None
    auth: AuthSpec
    mcp: McpSpec
    confirm_tools: list[str] = Field(default_factory=list)


@lru_cache
def _load() -> dict[str, ConnectorSpec]:
    data = yaml.safe_load(_CATALOG_PATH.read_text(encoding="utf-8")) or {}
    out: dict[str, ConnectorSpec] = {}
    for connector_id, entry in data.items():
        # Fail loudly: a malformed entry raises ValidationError here.
        out[connector_id] = ConnectorSpec(id=connector_id, **(entry or {}))
    return out


def get_catalog() -> list[ConnectorSpec]:
    """All validated connector specs, in catalog order."""
    return list(_load().values())


def get_connector(connector_id: str) -> ConnectorSpec:
    """One connector spec by id; raises KeyError if unknown."""
    specs = _load()
    if connector_id not in specs:
        raise KeyError(f"unknown connector '{connector_id}'")
    return specs[connector_id]
