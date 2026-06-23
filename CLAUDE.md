# CLAUDE.md — I.R.I.S. v5 working notes

Guidance for any AI/dev working in this repo. Read this first.

## What IRIS is

A personal AI assistant: a **stateless orchestration core** that routes a
**cheapest-capable Gemini brain** over a **mesh of MCP servers** (capabilities)
plus a **self-correcting memory**, exposed via FastAPI (REST + WebSocket) and a
React dashboard. Multi-tenant-ready from day one so it can become SaaS without a
rewrite.

## The 10 golden rules (never violate)

1. **MCP-first** — if a maintained server/library does it, call it; never
   reimplement browsers/memory/search/desktop.
2. **No model-id hardcoding** outside `iris/router/model_router.py`. A CI-style
   grep enforces this: `grep -rn "gemini-" iris --include=*.py | grep -v model_router.py | grep -v test_` must be empty.
3. **Stateless core** — no module-level *request/session* state; per-request
   state is the `RequestContext` value passed through the call chain. (Infra
   singletons — DB engine, circuit breaker, event bus — are fine.)
4. **Tenant-scoped** — every table has `tenant_id`; every repo query filters by
   it (`scripts/audit_tenant_scope.py` enforces). Single-user uses
   `DEFAULT_TENANT_ID="local"`.
5. **Privacy** — raw email/chat/file bodies are summarised locally; only
   sanitised context reaches Gemini (`core/privacy.py` + `core/context.py`).
6. **Confirmation gate** on send/submit/delete/publish/post (`core/confirm.py`).
7. **Payments hard-blocked** — never executed, even with confirmation.
8. **Secrets** only via `security/secrets.py` (OS keychain), never in code/logs;
   logs run through `security/redaction.py`.
9. **Verify every step** — each change ends with a runnable check.
10. **Provider-agnostic adapters** — swap LLM/STT/TTS/data in one file.

## Model routing (the only place model ids live)

`iris/router/model_router.py`:
- TRIVIAL / SIMPLE → `gemini-2.5-flash-lite`
- STANDARD / BACKGROUND → `gemini-2.5-flash`
- HARD / LONG_CONTEXT → `gemini-2.5-pro`  *(the PRD's "gemini-3.1-pro" is a 404 — that model doesn't exist)*
- TTS fallback → `gemini-2.5-flash-preview-tts`

`classify()` is a cheap deterministic heuristic; `model_for()` returns the
`ModelChoice`. `cost_usd()`/`PRICE_MAP` keep pricing here too. The commander
(planner) is the only routine Pro user, and it falls back HARD→STANDARD if Pro is
slow/unavailable.

## Request lifecycle

```
HTTP/WS (gateway, tenant middleware)
  -> classify (router)
  -> Orchestrator.handle (stateless agent loop)
       assemble context (memory recall + opt-in screen, sanitised)
       loop: Gemini(tools) -> MCP tool calls (sandbox + confirm + payment gates
             + privacy filter) -> feed results back -> final answer
       if HARD + multi-part: commander -> plan -> specialists -> review -> synthesize
       fire-and-forget Mem0 AUDN learn at the end
  -> usage row per LLM call; messages persisted; events streamed to Agent Monitor
```

## Module map

```
iris/
  gateway/      api.py (REST: /chat /usage /health), ws.py (/ws Agent Monitor),
                middleware.py (tenant_id + request_id)
  router/       model_router.py  (ONLY model ids + pricing)
  core/         orchestrator.py (agent loop + commander), planner.py, context.py,
                confirm.py, privacy.py, events.py, proactive.py, telemetry.py
  llm/          base.py (LLMClient iface), gemini.py (adapter), __init__.get_llm()
  mcp/          host.py (MCP client host), registry.yaml (declared servers),
                browser_router.py, servers/ (first-party: agentmemory, desktop)
  agents/       base.py (SubAgentRunner), specialists.yaml (12 specialists)
  memory/       store.py (MemoryStore over agentmemory MCP), mem0_client.py (AUDN),
                consolidate.py
  voice/        stt.py (whisper default), tts.py (kokoro default), wake.py (openWakeWord)
  data/         db.py, models.py (8 tenant-scoped tables), repo.py (tenant-scoped repos)
  security/     crypto.py (AES-256), secrets.py (keychain/Vault), sandbox.py,
                redaction.py, audit.py
  tools/        screen.py (opt-in screen intel)
  config/       settings.py (single source of config + secrets)
dashboard/      React 18 + TS + Tailwind (Chat, Agent Monitor, Memory, Connections, Cost, Settings)
scripts/        smoke_*.py + audit_*.py + self_audit.py + quality_gates.py
```

## MCP servers (capabilities = servers, not code)

Declared in `iris/mcp/registry.yaml`. Adding a capability = a registry entry, no
core change. Servers stay **down (isolated)** until their preconditions are met
(`requires_env`/`requires_file`) or they're started — startup never hangs.

- **filesystem** `@modelcontextprotocol/server-filesystem` (sandboxed to ./workspace)
- **websearch** `mcp_server_fetch` (Python; `npx mcp-server-fetch` does NOT exist)
- **playwright** `@playwright/mcp` · **browser_use** SSE :7801 · **browser_mcp** SSE :7802
- **agentmemory** first-party server over **chromadb** (PyPI `agentmemory` is broken vs current chroma)
- **gmail** `@gongrzhe/server-gmail-autoauth-mcp` · **calendar** `@cocal/google-calendar-mcp` (need OAuth)
- **desktop** first-party server over pyautogui/pygetwindow/pyperclip/mss (no pip "Windows-MCP" exists)

## Conventions / gotchas

- **Windows + npx**: the MCP SDK (1.27+) resolves `npx`→`npx.cmd` itself; pass the
  bare command in registry.yaml.
- **Gemini schema**: raw MCP `inputSchema` has keys Gemini rejects (`$schema`,
  `additionalProperties`, free-form objects). `gemini.py:_clean_schema` sanitises
  every tool schema; keep it if you touch tool wiring.
- **Free-tier 429**: the key is now paid, but if you see `429 RESOURCE_EXHAUSTED`,
  it's quota — wait ~60s, not a bug.
- **Voice defaults are free/local**: faster-whisper + Kokoro + openWakeWord. Sarvam
  / Gemini-TTS are optional paid swaps.
- **Don't commit**: `.env`, `iris.db`, `data/`, `memory/`, `workspace/*`,
  `node_modules/`, `dist/`, `.claude/` (all gitignored). Verify staging before commit.
- **Commits**: author is the user; **do not add a Claude co-author**.

## Run it

```bash
pip install -e ".[dev]"           # core; extras: voice / desktop / screen / proactive
cp .env.example .env              # add GEMINI_API_KEY
make dev                          # uvicorn iris.gateway.api:app --reload --port 8000
cd dashboard && npm install && npm run build
docker compose up -d              # iris-core + postgres:16 + redis:7
```

## Verify (run after changes)

```bash
python -m pytest -q                       # unit tests (router + security)
python scripts/self_audit.py              # 13 golden-rule checks
python scripts/audit_privacy.py           # no raw PII reaches Gemini; payments blocked
python scripts/audit_tenant_scope.py      # every repo query tenant-scoped
python scripts/quality_gates.py           # full checklist PASS/MANUAL/FIX
grep -rn "gemini-" iris --include=*.py | grep -v model_router.py | grep -v test_   # must be empty
```

See `README.md` for per-feature setup (OAuth, voice, browser, desktop) and
`IRIS_v5_ClaudeCode_Prompts.md` for the phase-by-phase build plan.
