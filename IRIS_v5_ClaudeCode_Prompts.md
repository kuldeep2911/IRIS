# I.R.I.S. v5 — Claude Code Build Prompts
## Ground-up rebuild · Gemini-powered · MCP-first · stateless · multi-tenant-ready
### Paste into Claude Code one STEP at a time. Never skip a step. Run the verification after each.

> Companion documents: **IRIS_PRD_v5.docx** and **IRIS_Technical_Architecture_v5.docx**.
> Keep both open. This file is the executable build plan derived from them.

---

## HOW TO USE THIS DOCUMENT

1. Start every Claude Code session by pasting the **CONTEXT RELOAD PROMPT** (bottom of this file).
2. Then paste **one STEP** (the fenced prompt block). Let Claude Code finish.
3. Run the **VERIFICATION** block under that step in your terminal. It must pass before you continue.
4. If verification fails, paste: `The verification failed: <paste output>. Fix it, then re-run the same verification.`
5. Only move to the next step when the current one is green.

**Golden rules enforced at every step (never violated):**
- **MCP-first.** If a maintained MCP server or library does it, IRIS calls it. Never reimplement browsers, memory, search, or desktop control.
- **No model hardcoding.** Every model id comes from `router/model_router.py`. Never write `"gemini-..."` in a route or agent.
- **Stateless core.** No module-level mutable state. All state lives in Postgres/Redis/memory stores.
- **Tenant-scoped.** Every table has `tenant_id`; every query filters by it. Single-user uses a fixed default tenant.
- **Privacy.** Raw personal data (email/chat/file bodies) is summarised locally; only sanitised context reaches Gemini.
- **Cheapest capable model.** Router defaults to Flash-Lite/Flash; Pro only for genuinely hard tasks.
- **Verify before proceeding.** Every step ends with a runnable check.

---

## MODEL STRATEGY (locked in — centralized in `router/model_router.py`)

| Class | Gemini model | When |
|-------|--------------|------|
| Trivial / routing / classify | `gemini-2.5-flash-lite` | greetings, wake-ack, the routing decision itself |
| Main workhorse | `gemini-2.5-flash` | most tasks: planning, tool calls, drafting, responses |
| Hard reasoning / long context | `gemini-3.1-pro` | complex design, >200k context — used rarely |
| Embeddings | `gemini-embedding-001` or local MiniLM | indexing personal data |
| Background / non-urgent | `gemini-2.5-flash` via **Batch (50% off)** | memory consolidation, nightly jobs |

Never hardcode a model id in a route or agent. `model_router.py` is the only place model ids appear.

---

## TECH BASELINE

- **Backend:** Python 3.12, FastAPI (async), MCP client SDK, Pydantic v2 settings.
- **Frontend:** React 18 + TypeScript + Tailwind (dark theme), WebSocket.
- **Data:** PostgreSQL (Redis for cache/queue/sessions). SQLite acceptable for first local run.
- **MCP servers (processes, declared in `mcp/registry.yaml`):** agentmemory, browser-use, BrowserMCP, Playwright MCP, desktop (Windows-MCP), filesystem, gmail, calendar, web-search/fetch.
- **Voice:** LiveKit + Sarvam STT + Kokoro TTS (af_heart) + Porcupine wake word.
- **Memory:** Mem0 (extraction + AUDN) over agentmemory (semantic store).
- **Infra:** Docker + docker-compose; OpenTelemetry; structured logs.

---

# ═══════════════════════════════════════════════════════
# PHASE 0 — FOUNDATION (stateless core + routed Gemini)
# ═══════════════════════════════════════════════════════

---

## STEP 0.1 — Repo skeleton, settings, Docker

```
You are building I.R.I.S. v5 — a personal AI assistant, rebuilt from scratch, Gemini-powered,
MCP-first, with a stateless core and a multi-tenant-ready data model. Read the two companion docs
(IRIS PRD v5 and IRIS Technical Architecture v5) if provided. This is a clean repo. Build the skeleton.

Follow the GOLDEN RULES: MCP-first, no model hardcoding, stateless core, tenant-scoped data,
privacy (raw data never sent raw to Gemini), cheapest-capable model, verify before proceeding.

STEP 1: Create this exact structure (empty but importable files where noted):
iris/
  __init__.py
  gateway/__init__.py  api.py  ws.py  middleware.py
  router/__init__.py   model_router.py
  core/__init__.py     orchestrator.py  planner.py  context.py  events.py
  llm/__init__.py      gemini.py  base.py
  mcp/__init__.py      host.py  registry.yaml
  agents/__init__.py   base.py  specialists.yaml
  memory/__init__.py   mem0_client.py  store.py
  voice/__init__.py    stt.py  tts.py  wake.py
  data/__init__.py     models.py  repo.py  db.py
  security/__init__.py crypto.py  secrets.py  sandbox.py  audit.py
  config/__init__.py   settings.py
dashboard/             (React+TS+Tailwind app via Vite — scaffold only)
docker-compose.yml
pyproject.toml         (or requirements.txt)
.env.example
README.md

STEP 2: config/settings.py — Pydantic v2 BaseSettings. Fields: GEMINI_API_KEY, DATABASE_URL
(default sqlite:///./iris.db), REDIS_URL (optional), DEFAULT_TENANT_ID="local", ENV, LOG_LEVEL,
model threshold knobs (ROUTER_SIMPLE_MAX_TOKENS etc). Load from env + .env. NEVER read secrets
elsewhere — settings is the single source.

STEP 3: pyproject.toml deps: fastapi, uvicorn[standard], pydantic, pydantic-settings,
google-genai (the new Gemini SDK), httpx, sqlalchemy, aiosqlite, redis, pyyaml,
"mcp" (model context protocol SDK), opentelemetry-sdk, structlog, python-dotenv.

STEP 4: docker-compose.yml with services: iris-core (build .), postgres:16, redis:7. Mark MCP
servers as commented placeholders to be filled in Phase 1. .env.example lists every env var.

STEP 5: README.md — one-paragraph overview + "make dev" run instructions.

STEP 6: Verify imports resolve: python -c "import iris.config.settings".
Print settings.py and docker-compose.yml.
```

**VERIFICATION:**
```bash
python -c "from iris.config.settings import Settings; print(Settings().DEFAULT_TENANT_ID)"
test -f iris/router/model_router.py && test -f iris/mcp/registry.yaml && echo "skeleton ok"
test -f docker-compose.yml && grep -q postgres docker-compose.yml && echo "compose ok"
```

---

## STEP 0.2 — Model router (the only place model ids live)

```
Continue IRIS v5. Build the model router — the single source of model selection. No model id may
appear anywhere else in the codebase.

STEP 1: iris/router/model_router.py
- Enum RequestClass: TRIVIAL, SIMPLE, STANDARD, HARD, LONG_CONTEXT, BACKGROUND.
- MODEL_MAP: RequestClass -> { model, max_output_tokens, use_batch: bool }:
    TRIVIAL/SIMPLE  -> gemini-2.5-flash-lite
    STANDARD        -> gemini-2.5-flash
    HARD/LONG_CONTEXT -> gemini-3.1-pro
    BACKGROUND      -> gemini-2.5-flash (use_batch=True)
- def classify(request_text, context_token_estimate, force=None) -> RequestClass:
    cheap heuristic first (length, keywords, context size, explicit force). Returns a class.
    (A Flash-Lite LLM classifier may be added later behind the same function — keep the signature.)
- def model_for(rc: RequestClass) -> ModelChoice (dataclass: model, max_output_tokens, use_batch).
- Thresholds come from settings (tunable without code change).

STEP 2: Unit-testable: add iris/router/test_model_router.py with a few asserts (no network).

STEP 3: Verify. Print model_router.py.
```

**VERIFICATION:**
```bash
python -m pytest iris/router/test_model_router.py -q
grep -rn "gemini-" iris --include=*.py | grep -v model_router.py | grep -v test_ && echo "LEAK: model id outside router" || echo "no model-id leaks"
```

---

## STEP 0.3 — Gemini adapter (provider-agnostic interface)

```
Continue IRIS v5. Build the LLM adapter behind a provider-agnostic interface so the provider can be
swapped in ONE file later.

STEP 1: iris/llm/base.py — abstract LLMClient:
  async def complete(model, messages, tools=None, max_output_tokens=None) -> LLMResponse
  LLMResponse dataclass: text, tool_calls (list of {name, args}), usage (input_tok, output_tok),
  model, raw.

STEP 2: iris/llm/gemini.py — GeminiClient(LLMClient) using google-genai SDK.
- Reads GEMINI_API_KEY from settings only.
- Maps our messages + tool schemas to Gemini function-calling format.
- Returns normalized LLMResponse (parse tool calls + usage).
- Built-in: exponential backoff on 429/5xx, circuit breaker, request timeout.
- Records usage to the usage table (Phase via data layer; for now accept an optional usage_sink fn).

STEP 3: Provide a thin factory get_llm() in iris/llm/__init__.py returning GeminiClient (so callers
never import the concrete class).

STEP 4: Smoke test script scripts/smoke_gemini.py: send "Say 'IRIS online' and nothing else" using
model_for(SIMPLE). Print response.text and usage.

STEP 5: Verify (requires real GEMINI_API_KEY in .env). Print gemini.py.
```

**VERIFICATION:**
```bash
python scripts/smoke_gemini.py    # expect: IRIS online  + token usage printed
grep -n "GEMINI_API_KEY" iris/llm/gemini.py    # must come via settings, not os.environ directly
```

---

## STEP 0.4 — Event bus + minimal FastAPI gateway + first end-to-end reply

```
Continue IRIS v5. Wire the smallest possible end-to-end path: HTTP in -> router -> Gemini -> response.
Keep the core STATELESS.

STEP 1: iris/core/events.py — async EventBus: subscribe(event, async_cb), publish(event, payload).
No globals leaking state; it's a simple in-process pub/sub for now.

STEP 2: iris/gateway/middleware.py — tenant middleware: resolve tenant_id (DEFAULT_TENANT_ID for
now) + a request id; attach to request.state. This is where multi-tenant auth slots in later.

STEP 3: iris/gateway/api.py — FastAPI app. POST /chat { message, session_id? } ->
  rc = classify(message); choice = model_for(rc);
  resp = await get_llm().complete(choice.model, [system, user], max_output_tokens=choice.max_output_tokens)
  return { reply: resp.text, model: resp.model, usage: resp.usage, request_class: rc.name }.
  (No memory/MCP yet — that's Phase 1+.) GET /health -> {status:"ok"}.

STEP 4: iris/__main__.py or uvicorn entry; "make dev" runs it.

STEP 5: Verify. Print api.py.
```

**VERIFICATION:**
```bash
uvicorn iris.gateway.api:app --port 8000 &  sleep 2
curl -s localhost:8000/health
curl -s -X POST localhost:8000/chat -H 'content-type: application/json' -d '{"message":"hello, who are you?"}' | python -m json.tool
kill %1
```

---

# ═══════════════════════════════════════════════════════
# PHASE 1 — MCP BACKBONE (capabilities as servers, not code)
# ═══════════════════════════════════════════════════════

---

## STEP 1.1 — MCP host + registry (filesystem + web-search first)

```
Continue IRIS v5. Make IRIS an MCP client host. Capabilities are external MCP servers declared in a
registry — NEVER hardcoded tool logic. Start with two safe servers: filesystem and web-search/fetch.

STEP 1: iris/mcp/registry.yaml — declare servers with transport (stdio|sse), command/url, and an
enabled flag. Add:
  filesystem: stdio, command: "npx -y @modelcontextprotocol/server-filesystem ./workspace"
  websearch:  stdio, command: "npx -y mcp-server-fetch"
(Leave agentmemory, browser_use, browser_mcp, playwright, desktop, gmail, calendar as enabled:false
placeholders to fill in later phases.)

STEP 2: iris/mcp/host.py — MCPHost:
- async connect_all(): read registry.yaml, start/connect each enabled server via the MCP SDK.
- collect each server's tool schemas; build a merged tool list + a map tool_name -> server.
- async invoke(tool_name, args) -> result: route to the owning server; normalize errors.
- def schemas() -> merged tool schema list (for Gemini function-calling).
- health(): per-server up/down.

STEP 3: Create ./workspace/ as the only path filesystem MCP may touch (sandbox).

STEP 4: scripts/smoke_mcp.py: connect_all(); print discovered tools; call a filesystem "write file"
then "read file" round-trip in ./workspace.

STEP 5: Verify. Print host.py and registry.yaml.
```

**VERIFICATION:**
```bash
python scripts/smoke_mcp.py    # prints tool list; writes+reads a file in ./workspace
test -d workspace && echo "sandbox dir ok"
grep -c "enabled" iris/mcp/registry.yaml
```

---

## STEP 1.2 — Orchestrator agent loop (route → tools → answer), stateless

```
Continue IRIS v5. Build the core agent loop that lets Gemini call MCP tools. Keep it stateless:
all per-request state is passed through, never stored at module scope.

READ iris/mcp/host.py
READ iris/router/model_router.py
READ iris/llm/base.py

STEP 1: iris/core/context.py — assemble(request, ctx) -> prompt context. For now: session id +
request only (memory + screen added later). Returns a compact dict; NEVER includes raw secrets.

STEP 2: iris/core/orchestrator.py — Orchestrator constructed with injected get_llm() and MCPHost.
async def handle(request, ctx) -> Result:
  rc = classify(request, est_tokens(ctx)); choice = model_for(rc)
  messages = [system_prompt(ctx), assemble(...)]
  for step in range(MAX_STEPS=8):
     resp = await llm.complete(choice.model, messages, tools=mcp.schemas(), max_output_tokens=choice.max_output_tokens)
     if resp.tool_calls:
        for call in resp.tool_calls:
           if needs_confirmation(call): emit('confirm_request', call); await wait_or_autoskip(ctx)
           result = await mcp.invoke(call.name, call.args)
           emit('tool_result', {call, result})       # -> Agent Monitor later
           messages.append(tool_msg(call, result))
        continue
     emit('final', resp.text); return Result(text=resp.text, usage=resp.usage)
  return Result(text="(max steps reached)", ...)
- On tool error: ask the model for an alternative approach; retry up to 5 total; then escalate.
- needs_confirmation: true for send/delete/publish/post/purchase-like tools (read from a small policy).

STEP 3: Wire POST /chat to Orchestrator.handle (replace the direct call from 0.4).

STEP 4: Verify. Print orchestrator.py.
```

**VERIFICATION:**
```bash
uvicorn iris.gateway.api:app --port 8000 &  sleep 2
curl -s -X POST localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message":"search the web for the current time in Tokyo and save a one-line summary to tokyo.txt"}' | python -m json.tool
cat workspace/tokyo.txt
kill %1
```

---

## STEP 1.3 — Data layer (multi-tenant from day one) + usage logging

```
Continue IRIS v5. Add the persistence layer. Every table carries tenant_id. Every repo method is
tenant-scoped. This is the SaaS-ready foundation even though we run single-user now.

STEP 1: iris/data/db.py — async SQLAlchemy engine + session from DATABASE_URL.

STEP 2: iris/data/models.py — tables (all with tenant_id):
  tenants(id, name, plan, created_at)
  users(id, tenant_id, name, auth_ref, created_at)
  sessions(id, tenant_id, user_id, started_at)
  messages(id, tenant_id, session_id, role, content, model, input_tok, output_tok, created_at)
  memories(id, tenant_id, user_id, text, source, confidence, embedding_ref, created_at)
  connections(id, tenant_id, type, status, credentials_ref, created_at)
  actions_audit(id, tenant_id, user_id, action, params_hash, result, ts)
  usage(id, tenant_id, model, input_tok, output_tok, cost_usd, ts)

STEP 3: iris/data/repo.py — repositories; EVERY method takes tenant_id and filters by it. Add a
guard that raises if tenant_id is missing. Seed a default tenant 'local' + user on startup.

STEP 4: Wire usage logging: GeminiClient.usage_sink writes a usage row (compute cost_usd from a
small static price map per model). messages persisted per turn.

STEP 5: Alembic (or simple create_all for sqlite). Verify tables exist + tenant guard works.
Print models.py and repo.py.
```

**VERIFICATION:**
```bash
python -c "import asyncio,iris.data.db as d,iris.data.models as m; asyncio.run(d.init_models())" && echo "tables created"
python -c "from iris.data.repo import MessageRepo; \
import inspect; assert 'tenant_id' in inspect.signature(MessageRepo.add).parameters; print('tenant-scoped ok')"
```

---

# ═══════════════════════════════════════════════════════
# PHASE 2 — BROWSER THAT ACTUALLY WORKS (login, forms, search)
# ═══════════════════════════════════════════════════════

---

## STEP 2.1 — Enable browser MCP servers (browser-use + Playwright + BrowserMCP)

```
Continue IRIS v5. Fix browsing for good by using EXISTING servers — do not hand-roll Playwright.
Enable three browser servers and a router that picks the right one per task.

STEP 1: In iris/mcp/registry.yaml flip these to enabled and configure:
  browser_use: sse, url http://localhost:7801/sse   (browser-use MCP, AI-driven)
  playwright:  stdio, command "npx -y @playwright/mcp@latest"   (deterministic, accessibility tree)
  browser_mcp: sse, url http://localhost:7802/sse   (real Chrome session via extension)
Document in README how to start browser-use MCP and the BrowserMCP Chrome extension, and how to set
the real Chrome profile path (BROWSER_USER_DATA_DIR) so logins are reused.

STEP 2: iris/mcp/browser_router.py — choose_browser(task) -> server name:
  logged-in/authenticated target (gmail/whatsapp/bank/linkedin) -> browser_mcp
  known structured form/flow -> playwright
  unknown page needing reasoning -> browser_use
  expose this as a hint the orchestrator passes when a browser_* tool is selected.

STEP 3: Confirm MCPHost picks up the new servers in schemas() and routes correctly.

STEP 4: Verify connections (servers must be running). Print browser_router.py.
```

**VERIFICATION:**
```bash
python scripts/smoke_mcp.py | grep -i "browser" && echo "browser tools discovered"
python -c "from iris.mcp.browser_router import choose_browser; print(choose_browser('log into gmail and read latest email'))"  # -> browser_mcp
python -c "from iris.mcp.browser_router import choose_browser; print(choose_browser('find the cheapest flight on this page'))"   # -> browser_use
```

---

## STEP 2.2 — End-to-end browser tasks (real login, search, form fill)

```
Continue IRIS v5. Prove the browser works on real tasks through the orchestrator. No new tool code —
this is orchestration + the MCP servers only.

STEP 1: Add a confirmation policy entry so any "send/submit/post" browser action requires user
confirmation (surface via the /chat confirm flow).

STEP 2: Ensure secrets (site passwords) come from security/secrets.py (OS keychain), retrieved by the
MCP server, NEVER placed in prompts or logs. Add a redaction filter to logging.

STEP 3: Manual acceptance (run each through POST /chat and confirm in terminal/UI):
  a) "Search the web for the top 3 mechanical keyboards under 10000 INR and save a summary file."
  b) "Log into Gmail and summarise my 3 most recent unread emails."  (uses real Chrome session)
  c) "Fill the contact form at <test url> with my name and email and stop before submitting."

STEP 4: Verify with (a) which needs no login. Print the confirmation-policy file.
```

**VERIFICATION:**
```bash
uvicorn iris.gateway.api:app --port 8000 &  sleep 2
curl -s -X POST localhost:8000/chat -H 'content-type: application/json' \
  -d '{"message":"Search the web for the top 3 mechanical keyboards under 10000 INR and save a summary to kbd.txt"}' >/dev/null
cat workspace/kbd.txt && echo "browser+search+file round-trip ok"
kill %1
grep -rn "redact" iris/security | head
```

---

# ═══════════════════════════════════════════════════════
# PHASE 3 — MEMORY (learns the user, self-corrects)
# ═══════════════════════════════════════════════════════

---

## STEP 3.1 — agentmemory MCP + memory store wrapper

```
Continue IRIS v5. Add persistent memory using the agentmemory MCP server. Do not build a vector DB
yourself.

STEP 1: In registry.yaml enable agentmemory: stdio, command "npx -y agentmemory serve".
Confirm MCPHost discovers its tools (store/search/update/delete/consolidate/graph).

STEP 2: iris/memory/store.py — MemoryStore wrapper over the agentmemory MCP tools:
  async remember(tenant_id, user_id, text, source, confidence)
  async recall(tenant_id, query, k=8) -> list[Memory]
  async forget(tenant_id, memory_id)
  All calls tenant-scoped; never store raw secrets.

STEP 3: iris/core/context.py — extend assemble() to call MemoryStore.recall and include a compact,
de-duplicated, SANITISED memory block in the prompt context.

STEP 4: scripts/smoke_memory.py: remember 3 facts, recall by query, assert relevant ones return.

STEP 5: Verify. Print store.py.
```

**VERIFICATION:**
```bash
python scripts/smoke_mcp.py | grep -i "memory" && echo "agentmemory tools discovered"
python scripts/smoke_memory.py   # stores + recalls facts, prints matches
```

---

## STEP 3.2 — Mem0 AUDN learning loop (write path)

```
Continue IRIS v5. Make IRIS LEARN after every turn using Mem0's Add/Update/Delete/No-op loop, so
facts stay fresh and contradictions are removed. Inspired by the Hermes agent's continuous learning.

STEP 1: iris/memory/mem0_client.py — Mem0 self-hosted client:
  async learn(tenant_id, user_id, turn) :
    1. locally summarise the turn (NO raw bodies to Gemini) -> short text
    2. Mem0 extracts candidate facts
    3. AUDN: for each fact, semantic match vs MemoryStore.recall -> add/update/delete/no-op
    4. write survivors via MemoryStore.remember with provenance (source, ts, confidence)
- Configure Mem0 extraction to use get_llm() through the router (cheap model) WITH the sanitiser.

STEP 2: Call memory.learn(...) at the END of Orchestrator.handle (fire-and-forget via event bus so
it doesn't block the response).

STEP 3: iris/memory/consolidate.py — a Batch-API (50% off) nightly job that de-dupes/merges memories
and flags stale (old + low-confidence) ones.

STEP 4: Acceptance: tell IRIS a fact in one session; in a NEW session ask about it; it recalls.
Then contradict it; confirm the old fact is updated/removed, not duplicated.

STEP 5: Verify. Print mem0_client.py.
```

**VERIFICATION:**
```bash
python scripts/smoke_learn.py   # session1: "my sister is Priya, I prefer dark mode";
                                # session2: recall both; then "actually I prefer light mode" -> updated, not duplicated
grep -rn "learn(" iris/core/orchestrator.py && echo "learn wired into loop"
```

---

# ═══════════════════════════════════════════════════════
# PHASE 4 — COMMUNICATION + CALENDAR
# ═══════════════════════════════════════════════════════

---

## STEP 4.1 — Gmail + Calendar MCP servers

```
Continue IRIS v5. Add email + calendar via MCP servers (official APIs). No bespoke API plumbing in
core — the MCP servers own it.

STEP 1: In registry.yaml enable gmail + calendar MCP servers (use a maintained Google Workspace MCP
server; document OAuth setup in README). Tokens stored via security/secrets.py (keychain).

STEP 2: Confirm MCPHost exposes read/search/send (gmail) and read/create/update (calendar) tools.

STEP 3: Confirmation policy: email_send and calendar_delete require user confirmation; email_read
returns SUMMARIES only (subject+sender+snippet) — the privacy rule, enforced in context assembly.

STEP 4: Acceptance via /chat:
  "What are my 5 most recent unread emails?"  (summaries only)
  "Draft a reply to the latest email from <X> saying I'll send the report tomorrow." (draft, confirm to send)
  "Add a meeting 'Dentist' Friday 3pm."

STEP 5: Verify discovery. Print the confirmation-policy additions.
```

**VERIFICATION:**
```bash
python scripts/smoke_mcp.py | grep -Ei "gmail|calendar" && echo "comms tools discovered"
grep -rn "email_send\|calendar_delete" iris -r | grep -i confirm && echo "confirm gate present"
```

---

## STEP 4.2 — WhatsApp via browser-use (persistent session)

```
Continue IRIS v5. Add WhatsApp using browser-use on WhatsApp Web with a persistent session — NOT a
hand-rolled Playwright script (that was the v3 failure).

STEP 1: Document first-run QR login; session persists in the real Chrome profile (browser_mcp) or a
saved browser-use profile dir. No unofficial API.

STEP 2: Add intent routing so "message <name> on whatsapp" maps to a browser task via browser_router
(authenticated -> browser_mcp). whatsapp_send requires confirmation; reads return summaries only.

STEP 3: Acceptance: "Send a WhatsApp to <contact> saying I'm running 10 minutes late." (confirm first)
and "Summarise the last 10 messages in my family group."

STEP 4: Verify routing decision. Print the intent-routing addition.
```

**VERIFICATION:**
```bash
python -c "from iris.mcp.browser_router import choose_browser; print(choose_browser('send a whatsapp message to mom'))"  # -> browser_mcp
grep -rn "whatsapp" iris -ri | grep -i confirm && echo "whatsapp confirm gate ok"
```

---

# ═══════════════════════════════════════════════════════
# PHASE 5 — VOICE + FACE
# ═══════════════════════════════════════════════════════

---

## STEP 5.1 — Voice pipeline (Sarvam STT + Kokoro TTS + wake word)

```
Continue IRIS v5. Add the real-time voice loop, reusing the FRIDAY reference pattern (LiveKit +
Sarvam STT). Female voice via Kokoro (af_heart). Provider-agnostic adapters so any piece can swap.

STEP 1: iris/voice/stt.py — STT adapter; default Sarvam v3 (Indian English). Interface:
  async transcribe(audio) -> text. Keep a WhisperSTT fallback class behind the same interface.

STEP 2: iris/voice/tts.py — TTS adapter; default Kokoro-82M voice "af_heart". Interface:
  async speak(text) -> audio + word_timestamps. Gemini TTS fallback behind same interface.

STEP 3: iris/voice/wake.py — Porcupine "Hey IRIS" wake word; on wake, start an STT capture and feed
the transcript to POST /chat; speak the reply via TTS. Only TEXT crosses into the core.

STEP 4: LiveKit pipeline wiring (from FRIDAY): mic -> wake -> STT -> core -> TTS -> speaker. Swap the
LLM provider to Gemini (it already is, via core). Latency target < 1s to first spoken word.

STEP 5: Acceptance: say "Hey IRIS, what's on my calendar today?" -> spoken female-voice answer.

STEP 6: Verify adapters import + interfaces match. Print stt.py and tts.py.
```

**VERIFICATION:**
```bash
python -c "from iris.voice.stt import STT; from iris.voice.tts import TTS; print('voice adapters ok')"
python scripts/smoke_tts.py   # writes a wav of IRIS saying 'IRIS online' in the female voice
```

---

## STEP 5.2 — Dashboard shell + avatar (optional, toggleable)

```
Continue IRIS v5. Build the React dashboard shell (dark theme) with a chat page, WebSocket streaming,
and an OPTIONAL TalkingHead 3D avatar driven by TTS audio. Avatar is toggleable in settings.

READ dashboard/ scaffold.

STEP 1: Dark theme (bg #0a0a0f, accent #2563EB + cyan #06B6D4). Pages routed: Chat, Agent Monitor,
Memory, Connections, Settings (others stubbed). Zustand store; WebSocket client.

STEP 2: Chat page: streaming responses token-by-token; mic button; tool-call cards between messages.

STEP 3: components/Avatar.tsx — TalkingHead 3D in a Three.js canvas; fed TTS audio + visemes for
lip-sync; idle breathing/blink when not speaking; states: idle, thinking, speaking, success, concern.
Toggle in Settings (off => voice-only).

STEP 4: Verify dashboard builds. Print Avatar.tsx.
```

**VERIFICATION:**
```bash
cd dashboard && npm install && npm run build && echo "dashboard builds"
grep -rn "TalkingHead" dashboard/src | head
```

---

# ═══════════════════════════════════════════════════════
# PHASE 6 — MULTI-AGENT + AGENT MONITOR
# ═══════════════════════════════════════════════════════

---

## STEP 6.1 — Planner + specialist sub-agents

```
Continue IRIS v5. Add multi-agent orchestration: IRIS commander breaks complex tasks into sub-tasks
and delegates to specialist sub-agents (system prompts from the agency-agents reference). Sub-agents
reuse the SAME MCP servers — no duplicated capability code.

STEP 1: iris/agents/specialists.yaml — 12 core specialists (name, system_prompt, allowed_tool_tags):
  frontend, backend, devops, database, code_reviewer, security, content_writer, researcher,
  data_analyst, ux, email_copywriter, deployer. Prompts adapted from agency-agents.

STEP 2: iris/core/planner.py — given a complex request, produce an ordered list of sub-tasks
{specialist, instruction, needs}. Uses model_for(HARD) only when the task is genuinely complex;
otherwise the orchestrator handles it directly (cheap path).

STEP 3: iris/agents/base.py — SubAgentRunner.run(subtask, ctx): a Gemini call with the specialist
system prompt + scoped MCP tools; own mini agent-loop (max 6 steps); returns {success, output,
artifacts, notes}. Commander reviews; up to 2 revisions; max nesting depth 2; per-sub-agent token cap.

STEP 4: Orchestrator: when classify()==HARD and request is multi-part, route through planner +
SubAgentRunner; else stay on the direct path.

STEP 5: Acceptance: "Build a small React landing page and deploy it to a static host." Confirm the
chain runs (planner -> frontend -> deployer -> commander review).

STEP 6: Verify. Print planner.py and base.py.
```

**VERIFICATION:**
```bash
python -c "import yaml; d=yaml.safe_load(open('iris/agents/specialists.yaml')); print('specialists:', len(d))"   # >= 12
python -c "from iris.core.planner import plan; print('planner importable')"
```

---

## STEP 6.2 — Agent Monitor (real-time visibility of which agent is working)

```
Continue IRIS v5. Build the signature UX: a live Agent Monitor showing which agent/MCP is running,
the agent chain, and tool calls — all streamed over WebSocket. Nothing is a black box.

STEP 1: iris/gateway/ws.py — on every orchestrator/sub-agent event (agent_start, agent_update,
agent_complete, agent_failed, tool_result, confirm_request), push a WS message to the session's UI.

STEP 2: iris/core/events.py — ensure orchestrator + SubAgentRunner emit these events with
{agent_name, status, elapsed_ms, summary}. Persist to actions_audit.

STEP 3: dashboard Agent Monitor page + components/AgentLog.tsx:
- Active agent card (name, status spinner/check/cross, elapsed).
- Agent chain log (Commander -> specialist -> MCP call -> review -> result).
- Tool-call log (collapsible). Real-time via WS.

STEP 4: Acceptance: run the Phase 6.1 build task and watch the chain appear live.

STEP 5: Verify events emit + UI builds. Print ws.py and AgentLog.tsx.
```

**VERIFICATION:**
```bash
grep -rn "agent_start\|agent_complete\|tool_result" iris/core iris/gateway | head
cd dashboard && npm run build && echo "agent monitor builds"
```

---

# ═══════════════════════════════════════════════════════
# PHASE 7 — DESKTOP CONTROL + SCREEN INTELLIGENCE
# ═══════════════════════════════════════════════════════

---

## STEP 7.1 — Desktop app control (Windows-MCP)

```
Continue IRIS v5. Add OS-level app control via a desktop MCP server (Windows-MCP or the OS
equivalent). No bespoke automation code in core.

STEP 1: registry.yaml enable desktop: stdio, command for the Windows-MCP server. Confirm tools:
open_app, click_element, type_text, read_window, take_screenshot, get/set_clipboard.

STEP 2: Confirmation policy: any action that modifies files/system requires confirmation.

STEP 3: Acceptance: "Open VS Code and create a new file hello.py with a print statement."

STEP 4: Verify discovery. (Linux/macOS: document the equivalent desktop MCP.)
```

**VERIFICATION:**
```bash
python scripts/smoke_mcp.py | grep -Ei "open_app|read_window|desktop" && echo "desktop tools discovered"
```

---

## STEP 7.2 — Screen intelligence (opt-in) + proactive alerts

```
Continue IRIS v5. Add opt-in screen awareness (inspired by OpenHuman) and proactive alerts. Privacy
first: in-memory only, never saved, app allow-list, OFF by default.

STEP 1: iris/tools/screen.py — capture screenshot -> Gemini vision (Flash) -> short description ->
store as a short-term memory in context (NOT persisted). Respect an app allow-list; never capture
banking/password apps.

STEP 2: iris/core/proactive.py — APScheduler jobs: meeting-soon alert, urgent-email alert, daily
briefing. Each returns a message IRIS speaks + shows. Tenant-scoped.

STEP 3: Settings toggles for screen intelligence + each proactive job (all off by default).

STEP 4: Acceptance: enable screen intel, open a code file, ask "what am I working on?" -> IRIS
describes it. Enable daily briefing -> fires at the configured time.

STEP 5: Verify flags default off. Print screen.py and proactive.py.
```

**VERIFICATION:**
```bash
python -c "from iris.config.settings import Settings; s=Settings(); print('screen default off:', getattr(s,'SCREEN_INTEL_ENABLED', False)==False)"
grep -rn "allow_list\|allowlist" iris/tools/screen.py && echo "app allow-list present"
```

---

# ═══════════════════════════════════════════════════════
# PHASE 8 — HARDEN + SAAS-READY PASS
# ═══════════════════════════════════════════════════════

---

## STEP 8.1 — Security hardening (encryption, secrets, sandbox, audit, sanitiser)

```
Continue IRIS v5. Lock the system down. Verify every privacy/security rule is actually enforced.

STEP 1: security/crypto.py — AES-256 at rest for memory + sensitive tables; key derived (PBKDF2
500k) from a passphrase; key only in memory.

STEP 2: security/secrets.py — all credentials via OS keychain; provide a Vault/KMS-ready interface
(swap class later for SaaS). Nothing secret in .env in prod; redaction filter on all logs.

STEP 3: security/sandbox.py — filesystem + shell MCP restricted to ./workspace + an allow-listed
command set; block destructive patterns; confirmation gate enforced centrally.

STEP 4: data_sanitiser in context.py — assert (with a test) that raw email/chat/file bodies are
never present in any outbound Gemini payload; only summaries. PAYMENTS hard-blocked at action layer.

STEP 5: security/audit.py — immutable actions_audit on every tool call + agent step.

STEP 6: Run a self-audit; print PASS/FIX per rule with the file that enforces it.
```

**VERIFICATION:**
```bash
python -m pytest iris/security -q
python scripts/audit_privacy.py   # asserts no raw PII in a simulated outbound payload; payments blocked
grep -rn "PAYMENT\|payment" iris/security iris/core | grep -i block && echo "payments blocked"
```

---

## STEP 8.2 — Cost page + observability + tenant-scope audit

```
Continue IRIS v5. Make cost and behavior observable, and prove multi-tenant readiness.

STEP 1: OpenTelemetry traces across gateway -> router -> orchestrator -> mcp -> llm. Structured JSON
logs with request id + tenant id.

STEP 2: Cost page (dashboard) reads the usage table: tokens + cost by model + by day. This becomes
per-tenant billing later.

STEP 3: Tenant-scope audit script: scan repo.py — every query filters by tenant_id; fail if any
unscoped query exists. Confirm DEFAULT_TENANT_ID is the only thing single-user about the data model.

STEP 4: Verify. Print the cost page component + the audit output.
```

**VERIFICATION:**
```bash
python scripts/audit_tenant_scope.py   # passes only if every repo query is tenant-scoped
cd dashboard && npm run build && echo "cost page builds"
grep -rn "tenant_id" iris/data/repo.py | wc -l
```

---

## STEP 8.3 — Full regression + quality gates + run

```
Continue IRIS v5. Final pass. Run the full Quality Gates (below) and fix any failure.

STEP 1: pyproject/requirements install clean; python -m pytest -q (all green).
STEP 2: dashboard builds; lints clean.
STEP 3: docker-compose up brings core + postgres + redis + MCP servers; /health ok.
STEP 4: Run the end-to-end acceptance scenarios from the PRD (Section 14) one by one; record pass/fail.
STEP 5: Print the completed Quality Gates checklist with PASS/FIX and the enforcing file per item.
```

**VERIFICATION:**
```bash
python -m pytest -q
cd dashboard && npm run build
docker compose up -d && sleep 5 && curl -s localhost:8000/health
```

---

# ═══════════════════════════════════════════════════════
# CONTEXT RELOAD PROMPT — paste at the START of every Claude Code session
# ═══════════════════════════════════════════════════════

```
You are building I.R.I.S. v5 — a personal AI assistant rebuilt from scratch. Reload context.

WHAT IT IS: a stateless orchestration core that connects a ROUTED Gemini brain to a MESH of MCP
servers (capabilities) and a memory subsystem (learning), exposed via FastAPI (REST+WebSocket) with a
React dashboard. Companion docs: IRIS PRD v5 + IRIS Technical Architecture v5.

ARCHITECTURE:
- Gateway (FastAPI, tenant middleware) -> Model Router -> Orchestrator (stateless agent loop) ->
  MCP Host (routes tool calls to servers) + Memory (Mem0 + agentmemory) -> response (stream+TTS).
- Capabilities are MCP SERVERS declared in iris/mcp/registry.yaml: agentmemory, browser-use,
  browser_mcp (real Chrome), playwright, desktop, filesystem, gmail, calendar, websearch.
- Multi-agent: a commander delegates complex tasks to specialist sub-agents (agency-agents prompts),
  which reuse the SAME MCP servers. The Agent Monitor streams which agent is working, live.

MODELS (Gemini; ONLY in iris/router/model_router.py — never hardcode elsewhere):
- trivial/routing -> gemini-2.5-flash-lite; standard -> gemini-2.5-flash; hard/long -> gemini-3.1-pro;
  background -> gemini-2.5-flash via Batch (50% off). Router picks the cheapest capable model.

GOLDEN RULES (never violate):
1. MCP-first: if a maintained server/library does it, call it — never reimplement browser/memory/
   search/desktop. 2. No model-id hardcoding outside model_router.py. 3. Stateless core; state lives
   in Postgres/Redis/memory stores. 4. tenant_id on every table; every query tenant-scoped (single-
   user uses DEFAULT_TENANT_ID). 5. Privacy: raw email/chat/file bodies summarised locally; only
   sanitised context reaches Gemini. 6. Confirmation gate on send/delete/publish/post. 7. Payments
   hard-blocked. 8. Secrets only via security/secrets.py (keychain), never in code/logs. 9. Every
   step ends with a runnable verification. 10. Provider-agnostic adapters (LLM/STT/TTS/data) so any
   piece swaps in one file.

STACK: Python 3.12 + FastAPI; google-genai SDK; MCP SDK; SQLAlchemy (Postgres/SQLite); Redis;
React 18 + TS + Tailwind; LiveKit + Sarvam STT + Kokoro TTS; Docker.

After reloading, confirm understanding in 3 lines, then wait for the STEP prompt.
```

---

# QUALITY GATES — RUN AT END OF THE BUILD

```
CORE / ARCHITECTURE:
[ ] Core is stateless — no module-level mutable state; many instances could run in parallel
[ ] Every model id comes from model_router.py (grep finds none elsewhere)
[ ] Router sends most traffic to Flash-Lite/Flash; Pro only on HARD/LONG_CONTEXT
[ ] Every table has tenant_id; every repo query is tenant-scoped (audit script passes)

MCP-FIRST:
[ ] Browser, memory, desktop, search, gmail, calendar are all MCP servers — none reimplemented in core
[ ] Adding a capability = a registry.yaml entry, no core code change
[ ] Browser router picks browser_mcp (logged-in) / playwright (structured) / browser_use (reasoning)

BROWSER (the v3 failure — must now work):
[ ] Real login works (Gmail) via the real Chrome session
[ ] Web search + form fill work end-to-end through the orchestrator
[ ] Send/submit actions require confirmation

MEMORY (learns the user):
[ ] Facts from one session recalled in a new session
[ ] Contradiction updates/removes the old fact (no duplicates) — Mem0 AUDN working
[ ] Raw bodies never sent to Gemini; only summaries (privacy test passes)

MULTI-AGENT + UI:
[ ] Complex task runs through planner -> specialists -> commander review
[ ] Agent Monitor shows the live chain + tool calls over WebSocket
[ ] Dark dashboard builds; optional avatar lip-syncs to TTS

VOICE:
[ ] "Hey IRIS" wake word -> Sarvam STT -> Gemini -> Kokoro female voice reply
[ ] Latency < ~1s to first spoken word

SECURITY / SAAS-READY:
[ ] AES-256 at rest; secrets only via keychain; logs redacted
[ ] Payments hard-blocked; destructive actions gated by confirmation
[ ] OpenTelemetry traces + usage/cost table per action (per-tenant billing later)
[ ] Tenant-scope audit passes (SaaS-ready); screen capture opt-in + app allow-list

BUILD / COST:
[ ] pytest green; dashboard builds; docker compose up; /health ok
[ ] Estimated personal monthly Gemini cost under ~$10 (routing verified in cost page)
```

---

## SUMMARY — WHAT THIS BUILD GIVES YOU

- **A working browser at last** — login, forms, search via browser-use + BrowserMCP + Playwright, picked per task. No more broken hand-rolled automation.
- **Real memory** — Mem0's AUDN loop over agentmemory means IRIS learns you over time and corrects stale facts instead of piling up contradictions.
- **MCP-first, zero clutter** — every capability is an external server; the core is thin orchestration. Adding Notion, Slack, or anything else is a registry line, not a rewrite.
- **Cheap to run** — the model router keeps most traffic on Flash-Lite/Flash and reserves Pro for genuinely hard work, holding personal cost under ~$10/month.
- **A face and a voice** — female Kokoro voice, Indian-English Sarvam STT, optional TalkingHead avatar, and a live Agent Monitor so you can see which agent is working.
- **SaaS-ready by construction** — stateless core + tenant_id everywhere + observability + cost metering means scaling to many users is additive, not a rewrite.

*Document: I.R.I.S. v5 Claude Code Build Prompts. Build derived from IRIS_PRD_v5.docx + IRIS_Technical_Architecture_v5.docx.*
*Start by pasting the CONTEXT RELOAD PROMPT, then STEP 0.1.*
