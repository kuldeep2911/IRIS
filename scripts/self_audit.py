"""Self-audit — PASS/FIX per golden rule, with the file that enforces it.

Static checks that each security/privacy rule has an enforcing implementation.
Run: ``python scripts/self_audit.py``
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _exists(rel: str) -> bool:
    return (ROOT / rel).exists()


def _contains(rel: str, needle: str) -> bool:
    p = ROOT / rel
    return p.exists() and needle.lower() in p.read_text(encoding="utf-8", errors="ignore").lower()


CHECKS = [
    ("MCP-first (capabilities = servers)", "iris/mcp/registry.yaml",
     lambda: _contains("iris/mcp/registry.yaml", "servers:")),
    ("No model-id hardcoding outside router", "iris/router/model_router.py",
     lambda: _exists("iris/router/model_router.py")),
    ("Stateless core (state in stores)", "iris/data/db.py",
     lambda: _exists("iris/data/db.py")),
    ("Tenant-scoped data model", "iris/data/repo.py",
     lambda: _contains("iris/data/repo.py", "_require_tenant")),
    ("Privacy: raw bodies summarised", "iris/core/privacy.py",
     lambda: _contains("iris/core/privacy.py", "summarise_tool_output")),
    ("Privacy: outbound sanitiser", "iris/core/context.py",
     lambda: _contains("iris/core/context.py", "sanitise_outbound")),
    ("Confirmation gate (send/delete/publish)", "iris/core/confirm.py",
     lambda: _contains("iris/core/confirm.py", "needs_confirmation")),
    ("Payments hard-blocked", "iris/core/confirm.py",
     lambda: _contains("iris/core/confirm.py", "hard-blocked")),
    ("Secrets via keychain (Vault-ready)", "iris/security/secrets.py",
     lambda: _contains("iris/security/secrets.py", "SecretStore")),
    ("AES-256 at rest (PBKDF2 500k)", "iris/security/crypto.py",
     lambda: _contains("iris/security/crypto.py", "500_000")),
    ("Sandbox: filesystem/shell -> workspace", "iris/security/sandbox.py",
     lambda: _contains("iris/security/sandbox.py", "workspace")),
    ("Log redaction filter", "iris/security/redaction.py",
     lambda: _contains("iris/security/redaction.py", "redact_processor")),
    ("Immutable audit on every tool/agent step", "iris/security/audit.py",
     lambda: _contains("iris/security/audit.py", "actions_audit")),
]


def main() -> None:
    failures = 0
    print(f"{'RESULT':6}  {'RULE':45}  ENFORCED BY")
    print("-" * 90)
    for rule, file, check in CHECKS:
        ok = False
        try:
            ok = bool(check())
        except Exception:  # noqa: BLE001
            ok = False
        status = "PASS" if ok else "FIX "
        if not ok:
            failures += 1
        print(f"{status:6}  {rule:45}  {file}")
    print("-" * 90)
    print(f"{len(CHECKS) - failures}/{len(CHECKS)} rules enforced.")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
