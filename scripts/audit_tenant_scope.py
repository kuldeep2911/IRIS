"""Tenant-scope audit — fail if any repo query is not tenant-scoped.

Scans ``iris/data/repo.py``: any method that issues a ``select(...)`` MUST also
reference ``tenant_id`` (a WHERE filter). Also confirms every table in
``models.py`` carries a ``tenant_id`` column (except the ``tenants`` table
itself) — proving the data model is SaaS-ready and that DEFAULT_TENANT_ID is the
only single-user thing about it.

Run: ``python scripts/audit_tenant_scope.py``  (exit 0 only if fully scoped)
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPOS = [
    ROOT / "iris" / "data" / "repo.py",
    ROOT / "iris" / "connectors" / "repo.py",   # connector connections
]
MODELS = ROOT / "iris" / "data" / "models.py"


def audit_repo() -> list[str]:
    violations: list[str] = []
    for repo in REPOS:
        if not repo.exists():
            continue
        src = repo.read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body_src = ast.get_source_segment(src, node) or ""
            if "select(" not in body_src or "tenant_id" in body_src:
                continue
            # Exemption: selecting the tenants table itself is allowed unscoped.
            if "select(Tenant)" in body_src:
                continue
            violations.append(f"{repo.name}:{node.name}() issues select() without tenant_id")
    return violations


def audit_models() -> list[str]:
    src = MODELS.read_text(encoding="utf-8")
    tree = ast.parse(src)
    problems: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        cls_src = ast.get_source_segment(src, node) or ""
        if "__tablename__" not in cls_src:
            continue
        is_tenants = '"tenants"' in cls_src or "'tenants'" in cls_src
        if not is_tenants and "tenant_id" not in cls_src:
            problems.append(f"table {node.name} has no tenant_id column")
    return problems


def main() -> None:
    repo_violations = audit_repo()
    model_problems = audit_models()

    print("=== repo.py tenant-scope ===")
    if repo_violations:
        for v in repo_violations:
            print("  FAIL:", v)
    else:
        print("  PASS: every select() in repo.py is tenant-scoped")

    print("=== models.py tenant_id coverage ===")
    if model_problems:
        for p in model_problems:
            print("  FAIL:", p)
    else:
        print("  PASS: every table carries tenant_id (except the tenants table)")

    if repo_violations or model_problems:
        sys.exit(1)
    print("\nTENANT-SCOPE AUDIT: PASS (SaaS-ready; DEFAULT_TENANT_ID is the only single-user bit)")


if __name__ == "__main__":
    main()
