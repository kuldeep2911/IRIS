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

## Browser mesh (Phase 2)

IRIS never hand-rolls browser automation — it uses three maintained MCP servers
and picks the right one per task ([`iris/mcp/browser_router.py`](iris/mcp/browser_router.py)):

| Server         | Transport            | Use for                                            |
|----------------|----------------------|----------------------------------------------------|
| `playwright`   | stdio (auto via npx) | deterministic, structured form/flows               |
| `browser_use`  | SSE `:7801`          | AI-driven reasoning over unknown pages             |
| `browser_mcp`  | SSE `:7802`          | the **real, logged-in Chrome** session             |

`playwright` starts automatically (`npx -y @playwright/mcp@latest`); the first
run downloads the server (and `npx playwright install chromium` for the browser
binary). The other two you start yourself:

```bash
# browser-use MCP (AI-driven) on :7801 — see https://github.com/browser-use/browser-use
uvx 'browser-use[cli]' --mcp --port 7801          # or the project's documented launch cmd

# BrowserMCP (real Chrome): install the "Browser MCP" Chrome extension, then run
# its bridge so the SSE endpoint is served on :7802 (see https://browsermcp.io).
```

**Reuse your logins:** set `BROWSER_USER_DATA_DIR` in `.env` to your real Chrome
profile path so authenticated sessions (Gmail/WhatsApp/etc.) are reused by the
browser servers — IRIS never stores site passwords itself.

```env
# Windows example
BROWSER_USER_DATA_DIR=C:\Users\<you>\AppData\Local\Google\Chrome\User Data
```

If a browser server isn't running it's simply marked **down** (the host isolates
failures); `playwright` alone is enough for search + structured form tasks.

## Gmail + Calendar (Phase 4)

Email and calendar are maintained Google MCP servers (official APIs) — IRIS adds
no bespoke API code. They stay **down until you complete OAuth**; the host skips
a server whose credentials are missing (so startup never hangs), then connects
once configured. Tokens live in each server's credential store / the OS keychain
— never in IRIS code, prompts, or logs.

**1. Google Cloud OAuth client** (one-time): in Google Cloud Console create an
OAuth 2.0 *Desktop* client, enable the **Gmail API** and **Google Calendar API**,
and download the client secret JSON.

**2. Gmail** (`@gongrzhe/server-gmail-autoauth-mcp`):
```bash
mkdir -p ~/.gmail-mcp
cp /path/to/client_secret.json ~/.gmail-mcp/gcp-oauth.keys.json
npx -y @gongrzhe/server-gmail-autoauth-mcp auth      # opens a browser, then writes
                                                     # ~/.gmail-mcp/credentials.json
```
Once `~/.gmail-mcp/credentials.json` exists, IRIS auto-connects the `gmail` server.

**3. Calendar** (`@cocal/google-calendar-mcp`): point it at the client secret and
authorise:
```bash
export GOOGLE_OAUTH_CREDENTIALS=/path/to/client_secret.json   # add to .env
npx -y @cocal/google-calendar-mcp auth
```
With `GOOGLE_OAUTH_CREDENTIALS` set, IRIS auto-connects the `calendar` server.

**Privacy:** `email_read`/search results are reduced to **summaries**
(subject + sender + snippet) before anything reaches Gemini — full bodies never
leave your machine ([`iris/core/privacy.py`](iris/core/privacy.py)).
**Confirmation:** `email_send` and `calendar_delete` always require explicit
confirmation ([`iris/core/confirm.py`](iris/core/confirm.py)).

## WhatsApp (Phase 4.2)

WhatsApp uses **WhatsApp Web through the real Chrome session** (`browser_mcp`) —
no unofficial API, no hand-rolled Playwright (that was the v3 failure). The
browser router sends any messaging intent ("message mom on whatsapp") to
`browser_mcp` where the session already lives ([`iris/mcp/browser_router.py`](iris/mcp/browser_router.py)).

**First-run login (one-time):** in the real Chrome profile used by the BrowserMCP
extension, open <https://web.whatsapp.com> and scan the **QR code** with your
phone (WhatsApp → Linked devices). The session persists in that Chrome profile
(`BROWSER_USER_DATA_DIR`), so IRIS reuses it on later runs — no re-login.

**Rules:** `whatsapp_send` requires confirmation before sending; reads return
**summaries only** (last-N messages, sender + snippet — bodies stripped by the
privacy filter). Example tasks:
- *"Send a WhatsApp to Priya saying I'm running 10 minutes late."* (confirm first)
- *"Summarise the last 10 messages in my family group."* (summaries only)

## Voice (Phase 5)

Real-time loop: **mic → "Hey IRIS" wake word → STT → core → TTS → speaker**. Only
**text** ever crosses into the core. Defaults are **100% free / open-source and
local**; paid services are optional swaps (provider-agnostic adapters):

| Piece | Default (free, local) | Optional swap |
|-------|-----------------------|---------------|
| STT   | **faster-whisper** (MIT) | Sarvam (paid) |
| TTS   | **Kokoro-82M** `af_heart` (Apache-2.0) | Gemini TTS |
| Wake  | **openWakeWord** (Apache-2.0, no key/trial) | — |

```bash
pip install -e ".[voice]"          # numpy, sounddevice, openwakeword, kokoro-onnx, faster-whisper
python scripts/smoke_tts.py        # writes workspace/iris_online.wav (female voice)
python -m iris.voice.wake          # run the live loop (needs a mic; no API keys)
```

- **STT** is faster-whisper out of the box — no key. (To use Sarvam instead, set
  `STT_PROVIDER=sarvam` + `SARVAM_API_KEY`.)
- **Wake word** is openWakeWord — no access key, no trial. It ships pretrained
  models (default `WAKE_MODEL=hey_jarvis`); for the real "Hey IRIS" phrase, train
  a custom model with openWakeWord's notebook and set `WAKE_MODEL_PATH` to the
  resulting `.onnx`.
- **TTS** is local Kokoro `af_heart`: download `kokoro-v1.0.onnx` + `voices-v1.0.bin`
  and set `KOKORO_MODEL_PATH` / `KOKORO_VOICES_PATH`; otherwise IRIS falls back to
  the Gemini TTS female voice automatically.

LiveKit can replace the local mic/speaker transport for streaming/remote use
(the FRIDAY pattern) without changing the loop.

## Desktop control (Phase 7.1)

OS-level app control is an MCP server ([`iris/mcp/servers/desktop_server.py`](iris/mcp/servers/desktop_server.py))
exposing `open_app`, `list_windows`, `read_window`, `click_element`, `type_text`,
`take_screenshot`, `get_clipboard`, `set_clipboard`. The server always connects
and lists its tools; each tool needs the automation libs:

```bash
pip install -e ".[desktop]"   # pyautogui, pygetwindow, pyperclip, mss
```

System-modifying actions (`open_app`, `click_element`, `type_text`,
`set_clipboard`) are **confirmation-gated**; reads (`read_window`,
`take_screenshot`, `get_clipboard`) are not. No pip-installable "Windows-MCP"
exists, so this thin server wraps maintained libraries — the CursorTouch
[Windows-MCP](https://github.com/CursorTouch/Windows-MCP) is a drop-in swap
(point the `desktop` registry entry at it). On Linux/macOS the same tools work
via the cross-platform libs; an OS-native desktop MCP can be substituted.

## Screen intelligence + proactive alerts (Phase 7.2)

Both are **opt-in and OFF by default**.

**Screen intelligence** ([`iris/tools/screen.py`](iris/tools/screen.py)): when
`SCREEN_INTEL_ENABLED=true`, IRIS can describe what you're working on — capture →
Gemini vision (Flash) → a short description that lives **in memory only, never
persisted**. An **app allow-list** gates what may be captured and a block-list
(banking/passwords) is never captured. Ask *"what am I working on?"* and IRIS
describes the active window. Needs `pip install -e ".[screen]"`.

**Proactive alerts** ([`iris/core/proactive.py`](iris/core/proactive.py)):
APScheduler jobs — meeting-soon, urgent-email, daily briefing — each gated by its
own flag (`PROACTIVE_MEETING_ALERTS`, `PROACTIVE_EMAIL_ALERTS`,
`PROACTIVE_DAILY_BRIEFING`, all default off). Nothing is scheduled unless enabled.
Needs `pip install -e ".[proactive]"`.

## Connectors (Phase 9)

Connect 20+ third-party apps from the **Connections page** — each is a catalog
entry ([`iris/connectors/catalog.yaml`](iris/connectors/catalog.yaml)) pointing at
a maintained MCP server + an auth spec. Connecting runs OAuth2 (auth-code + PKCE +
refresh) or stores a PAT/API key **encrypted in the OS keychain** (never in db,
logs, `.env`, or code), then starts that connector's MCP server with the token
injected so its tools reach the brain at runtime — per user, tenant-scoped.

**OAuth setup (one-time per provider):**
1. Register the **exact** redirect URI in the provider's OAuth app:
   `http://localhost:8000/connectors/callback` (scheme/host/port/path must match).
2. Put the app's client id/secret in `.env` using the env-var names from the
   catalog, e.g. `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` (one Google app
   serves gmail + gcalendar + drive), `SLACK_CLIENT_ID/SECRET`,
   `ATLASSIAN_CLIENT_ID/SECRET`, `NOTION_CLIENT_ID/SECRET`.
3. Google issues a **refresh token only** with `access_type=offline` +
   `prompt=consent` — already set in the catalog.

**Smoke (run for gmail / github / slack / notion):** open Connections → **Connect**
→ complete consent in the popup → the card flips to connected with your account
label. In chat: *"Summarise my 3 most recent unread emails"* (read-only summaries);
*"Send a test email to myself"* triggers a **confirmation** before sending. PAT
connectors (GitHub/Vercel/…) open a token modal with a "where do I get this?" link
and validate the token on connect.

**Security:** tokens AES-256 + keychain (`token_vault.py`), redacted from logs,
auto-refreshed (revoked → friendly "reconnect" prompt), every connection
tenant+user scoped, confirm gate on each connector's `confirm_tools`, and
**payments hard-blocked** (Stripe/AWS) regardless of confirmation. Verify with
`python scripts/audit_connectors.py`.

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
