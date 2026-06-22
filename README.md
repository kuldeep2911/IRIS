# I.R.I.S. v5 — Intelligent Responsive Intelligence System

I.R.I.S. is a personal AI assistant built as a **stateless orchestration core**
that connects a **routed Gemini brain** (cheapest-capable model per request,
Flash-Lite → Flash → Pro) to a **mesh of MCP servers** (browser, memory, search,
desktop, gmail, calendar — capabilities live as external servers, never
reimplemented in core) plus a **self-correcting memory** subsystem (Mem0 over
agentmemory). It exposes a FastAPI backend (REST + WebSocket) and a React +
Tailwind dashboard, with an optional voice loop (Sarvam STT + Kokoro TTS + "Hey
IRIS" wake word). The data model is **tenant-scoped from day one** and the core
is stateless, so the same architecture can scale from single-user to SaaS
without a rewrite.

## Quick start (local)

```bash
# 1. Install Python deps (Python 3.12)
make install            # or: pip install -e ".[dev]"

# 2. Configure
cp .env.example .env    # then add your GEMINI_API_KEY

# 3. Run the API (built out in STEP 0.4)
make dev                # uvicorn iris.gateway.api:app --reload --port 8000
```

Health check (once STEP 0.4 lands): `curl localhost:8000/health`

## Full stack (Docker)

```bash
docker compose up -d    # iris-core + postgres:16 + redis:7
curl localhost:8000/health
```

MCP servers (browser, memory, desktop, gmail, calendar) mostly run on the host
and are reached over stdio / localhost SSE — declared in
[`iris/mcp/registry.yaml`](iris/mcp/registry.yaml) and enabled per phase.

## Make targets

| Target          | Does                                                    |
|-----------------|---------------------------------------------------------|
| `make install`  | `pip install -e ".[dev]"`                                |
| `make dev`      | Run the FastAPI app with reload on :8000                 |
| `make test`     | `pytest -q`                                              |
| `make up`/`down`| `docker compose up -d` / `down`                          |

## Architecture (the golden rules)

1. **MCP-first** — if a maintained server/library does it, IRIS calls it.
2. **No model-id hardcoding** outside [`iris/router/model_router.py`](iris/router/model_router.py).
3. **Stateless core** — state lives in Postgres / Redis / memory stores.
4. **Tenant-scoped** — every table has `tenant_id`; every query filters by it.
5. **Privacy** — raw bodies summarised locally; only sanitised context to Gemini.
6. **Confirmation gate** on send/delete/publish/post. 7. **Payments hard-blocked.**
8. **Secrets** only via `security/secrets.py` (keychain). 9. **Verify** every step.
10. **Provider-agnostic adapters** — swap any piece in one file.

See `IRIS_PRD_v5` and `IRIS_Technical_Architecture_v5` for the full design, and
`IRIS_v5_ClaudeCode_Prompts.md` for the step-by-step build plan.
