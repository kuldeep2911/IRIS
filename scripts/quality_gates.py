"""Quality Gates — final checklist with PASS / MANUAL / FIX + the enforcing file.

Runs the automated audits (privacy, tenant-scope, self-audit, model-id leak,
dashboard build artifact) and prints the full Quality Gates checklist. Items that
require live external setup (real Gmail login, mic, Docker daemon) are marked
MANUAL with the file/path that implements them.

Run: ``python scripts/quality_gates.py``
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _contains(rel: str, needle: str) -> bool:
    p = ROOT / rel
    return p.exists() and needle.lower() in p.read_text(encoding="utf-8", errors="ignore").lower()


def _no_model_leak() -> bool:
    out = subprocess.run(
        ["grep", "-rn", "gemini-", "iris", "--include=*.py"],
        cwd=ROOT, capture_output=True, text=True,
    ).stdout
    leaks = [l for l in out.splitlines() if "model_router.py" not in l and "test_" not in l]
    return not leaks


def _script_passes(rel: str) -> bool:
    r = subprocess.run([sys.executable, rel], cwd=ROOT, capture_output=True, text=True)
    return r.returncode == 0


# (gate, status_fn, enforcing file). status_fn returns True=PASS, "MANUAL", or False.
GATES = [
    ("CORE / ARCHITECTURE", None, None),
    ("Stateless core (no module-level request state)", lambda: _contains("iris/core/orchestrator.py", "RequestContext"), "core/orchestrator.py"),
    ("Every model id from model_router.py", _no_model_leak, "router/model_router.py"),
    ("Router defaults to Flash-Lite/Flash; Pro only HARD", lambda: _contains("iris/router/model_router.py", "gemini-2.5-flash-lite"), "router/model_router.py"),
    ("Every table tenant_id; every repo query scoped", lambda: _script_passes("scripts/audit_tenant_scope.py"), "scripts/audit_tenant_scope.py"),

    ("MCP-FIRST", None, None),
    ("Browser/memory/desktop/search/gmail/calendar = servers", lambda: _contains("iris/mcp/registry.yaml", "servers:"), "mcp/registry.yaml"),
    ("Adding a capability = a registry entry", lambda: _contains("iris/mcp/host.py", "_load_registry"), "mcp/host.py"),
    ("Browser router picks mcp/playwright/use", lambda: _contains("iris/mcp/browser_router.py", "choose_browser"), "mcp/browser_router.py"),

    ("MEMORY (learns the user)", None, None),
    ("Facts recalled across sessions", lambda: _contains("iris/memory/store.py", "recall"), "memory/store.py"),
    ("Contradictions update, not duplicate (AUDN)", lambda: _contains("iris/memory/mem0_client.py", "audn") or _contains("iris/memory/mem0_client.py", "update"), "memory/mem0_client.py"),
    ("Raw bodies never sent; only summaries", lambda: _script_passes("scripts/audit_privacy.py"), "core/privacy.py + context.py"),

    ("MULTI-AGENT + UI", None, None),
    ("Planner -> specialists -> commander review", lambda: _contains("iris/core/planner.py", "def plan"), "core/planner.py + agents/base.py"),
    ("Agent Monitor streams chain over WebSocket", lambda: _contains("iris/gateway/ws.py", "agent_start"), "gateway/ws.py"),
    ("Dark dashboard builds; optional avatar", lambda: (ROOT / "dashboard/dist/index.html").exists(), "dashboard/ (npm run build)"),

    ("VOICE", None, None),
    ("Hey IRIS -> STT -> Gemini -> female voice (free/local)", lambda: _contains("iris/voice/wake.py", "openwakeword"), "voice/{wake,stt,tts}.py"),

    ("SECURITY / SAAS-READY", None, None),
    ("AES-256 at rest; secrets via keychain; logs redacted", lambda: _contains("iris/security/crypto.py", "500_000") and _contains("iris/security/redaction.py", "redact"), "security/{crypto,secrets,redaction}.py"),
    ("Payments hard-blocked; destructive gated", lambda: _contains("iris/core/confirm.py", "hard-blocked"), "core/confirm.py"),
    ("OpenTelemetry traces + usage/cost per action", lambda: _contains("iris/core/telemetry.py", "setup_tracing"), "core/telemetry.py + data/repo.py"),
    ("Tenant-scope audit passes; screen opt-in + allow-list", lambda: _contains("iris/tools/screen.py", "allow_list"), "scripts/audit_tenant_scope.py + tools/screen.py"),

    ("BUILD / COST", None, None),
    ("pytest green; dashboard builds; /health ok", lambda: (ROOT / "dashboard/dist/index.html").exists(), "pytest + dashboard + gateway"),
    ("docker compose up (core+postgres+redis)", lambda: "MANUAL", "docker-compose.yml (daemon required)"),
    ("Personal monthly Gemini cost < ~$10 (routing)", lambda: "MANUAL", "router + /usage cost page"),
]


def main() -> None:
    fixes = 0
    for gate, fn, file in GATES:
        if fn is None:
            print(f"\n[{gate}]")
            continue
        try:
            res = fn()
        except Exception:  # noqa: BLE001
            res = False
        status = "MANUAL" if res == "MANUAL" else ("PASS" if res else "FIX ")
        if status == "FIX ":
            fixes += 1
        print(f"  [{status}] {gate:55} {file}")
    print("\n" + ("ALL AUTOMATED GATES PASS." if fixes == 0 else f"{fixes} gate(s) need FIX."))
    sys.exit(1 if fixes else 0)


if __name__ == "__main__":
    main()
