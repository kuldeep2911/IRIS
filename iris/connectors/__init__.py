"""Connectors framework — connect third-party apps (OAuth2/PAT) to IRIS.

Each connector is a catalog ENTRY (data) pointing at a maintained MCP server +
an auth spec. The framework does auth + lifecycle only; it never reimplements a
provider's API (GOLDEN RULE #1).
"""
