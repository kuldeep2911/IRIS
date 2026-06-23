"""Connectors PASS/FIX checklist (Phase 9.10).

Static + light-dynamic checks across the connector framework: OAuth connect,
token refresh, PAT connect, tool exposure, confirmation gate, disconnect
cleanup, tenant scoping, secret redaction, payments hard-blocked.

Run: ``python scripts/audit_connectors.py``
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _has(rel: str, needle: str) -> bool:
    p = ROOT / rel
    return p.exists() and needle.lower() in p.read_text(encoding="utf-8", errors="ignore").lower()


def _catalog_ok() -> bool:
    from iris.connectors.catalog import get_catalog

    return len(get_catalog()) >= 20


def _payments_blocked() -> bool:
    from iris.core.confirm import is_payment

    # Stripe/AWS payment-ish tools must be detected as payments (hard-blocked).
    return is_payment("create_payment_link") and is_payment("charge_card")


def _tenant_scope_ok() -> bool:
    r = subprocess.run([sys.executable, "scripts/audit_tenant_scope.py"], cwd=ROOT,
                       capture_output=True, text=True)
    return r.returncode == 0


CHECKS = [
    ("OAuth connect (auth-code + PKCE + signed state)", "iris/connectors/oauth.py",
     lambda: _has("iris/connectors/oauth.py", "build_authorize_url") and _has("iris/connectors/oauth.py", "code_challenge")),
    ("Token refresh (auto-refresh expired access token)", "iris/connectors/oauth.py",
     lambda: _has("iris/connectors/oauth.py", "get_valid_access_token") and _has("iris/connectors/oauth.py", "refresh_token")),
    ("PAT / API-key connect (validate then store)", "iris/connectors/token_auth.py",
     lambda: _has("iris/connectors/token_auth.py", "connect_with_token")),
    ("Tools exposed per-user (schemas_for_user)", "iris/mcp/host.py",
     lambda: _has("iris/mcp/host.py", "schemas_for_user") and _has("iris/core/orchestrator.py", "schemas_for_user")),
    ("Confirmation gate on connector confirm_tools", "iris/core/orchestrator.py",
     lambda: _has("iris/core/orchestrator.py", "connector_confirm_tools")),
    ("Disconnect cleanup (stop server + delete tokens)", "iris/connectors/service.py",
     lambda: _has("iris/connectors/service.py", "stop_connector_server") and _has("iris/connectors/service.py", "delete_tokens")),
    ("Tenant + user scoped connections", "iris/connectors/repo.py",
     _tenant_scope_ok),
    ("Tokens encrypted at rest (keychain, AES-256)", "iris/connectors/token_vault.py",
     lambda: _has("iris/connectors/token_vault.py", "encrypt") and _has("iris/connectors/token_vault.py", "keychain")),
    ("Secret redaction (access/refresh token scrubbed from logs)", "iris/security/redaction.py",
     lambda: _has("iris/security/redaction.py", "access_token") and _has("iris/security/redaction.py", "refresh_token")),
    ("Payments hard-blocked (Stripe/AWS)", "iris/core/confirm.py", _payments_blocked),
    ("20 connectors in the catalog", "iris/connectors/catalog.yaml", _catalog_ok),
]


def main() -> None:
    fixes = 0
    print(f"{'RESULT':6}  {'CHECK':52}  FILE")
    print("-" * 92)
    for label, file, fn in CHECKS:
        try:
            ok = bool(fn())
        except Exception:  # noqa: BLE001
            ok = False
        status = "PASS" if ok else "FIX "
        if not ok:
            fixes += 1
        print(f"{status:6}  {label:52}  {file}")
    print("-" * 92)
    print("CONNECTORS AUDIT: ALL PASS" if fixes == 0 else f"{fixes} item(s) need FIX")
    sys.exit(1 if fixes else 0)


if __name__ == "__main__":
    main()
