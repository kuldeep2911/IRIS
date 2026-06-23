"""Screen intelligence — opt-in, privacy-first screen awareness (Phase 7.2).

Flow: capture the screen -> Gemini vision (Flash) -> a short description ->
stored as a SHORT-TERM, in-memory note (NEVER persisted to disk/DB). Inspired by
OpenHuman, but locked down:

- OFF by default (``SCREEN_INTEL_ENABLED``).
- An app ALLOW-LIST gates what may be captured; a block-list (banking/passwords)
  is never captured, even if allow-listed.
- The description lives only in memory for the current session and is dropped on
  restart — it is not written anywhere.

The vision model id comes from the router (GOLDEN RULE #2). Heavy libs are
lazy-imported so importing this module stays cheap.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import structlog

from iris.config.settings import get_settings
from iris.router.model_router import RequestClass, model_for

log = structlog.get_logger(__name__)


@dataclass
class ScreenNote:
    """A short-term, in-memory screen description (not persisted)."""

    text: str
    window: str
    ts: float


class ScreenIntel:
    """Captures + describes the screen, respecting the app allow-list.

    State is a per-tenant in-memory cache only (short-term; never saved).
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.enabled = settings.SCREEN_INTEL_ENABLED
        # app allow-list / block-list (lower-cased for matching)
        self.allow_list = [a.lower() for a in settings.SCREEN_ALLOWLIST]
        self.block_list = [b.lower() for b in settings.SCREEN_BLOCKLIST]
        self._recent: dict[str, ScreenNote] = {}  # tenant_id -> note (in-memory only)

    # ── allow-list gate ───────────────────────────────────────────────────────
    def may_capture(self, window_title: str) -> bool:
        """True only if the active window is allow-listed and not block-listed."""
        title = (window_title or "").lower()
        if any(b in title for b in self.block_list):
            return False
        return any(a in title for a in self.allow_list)

    # ── capture + describe ────────────────────────────────────────────────────
    async def describe(self, tenant_id: str, refresh: bool = True) -> str | None:
        """Return a short description of the current screen (or cached one).

        Returns ``None`` when disabled, blocked by the allow-list, or on error.
        Never raises into the caller — screen intel is best-effort.
        """
        if not self.enabled:
            return None
        if not refresh and tenant_id in self._recent:
            return self._recent[tenant_id].text
        try:
            import asyncio

            return await asyncio.to_thread(self._capture_and_describe_blocking, tenant_id)
        except Exception as exc:  # noqa: BLE001 — best-effort
            log.warning("screen.describe_failed", error=str(exc))
            return None

    def recent(self, tenant_id: str) -> str | None:
        note = self._recent.get(tenant_id)
        return note.text if note else None

    # ── internals (run in a worker thread) ────────────────────────────────────
    def _capture_and_describe_blocking(self, tenant_id: str) -> str | None:
        window = self._active_window_title()
        if not self.may_capture(window):
            log.info("screen.capture_skipped", reason="not allow-listed", window=window[:40])
            return None

        png = self._screenshot_png()
        if not png:
            return None

        text = self._vision_describe(png)
        if text:
            # SHORT-TERM in-memory only — never written to disk or DB.
            self._recent[tenant_id] = ScreenNote(text=text, window=window, ts=time.time())
        return text

    @staticmethod
    def _active_window_title() -> str:
        try:
            import pygetwindow as gw

            win = gw.getActiveWindow()
            return win.title if win else ""
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _screenshot_png() -> bytes | None:
        try:
            import mss
            import mss.tools

            with mss.mss() as sct:
                shot = sct.grab(sct.monitors[0])
                return mss.tools.to_png(shot.rgb, shot.size)
        except Exception as exc:  # noqa: BLE001
            log.warning("screen.screenshot_failed", error=str(exc))
            return None

    @staticmethod
    def _vision_describe(png: bytes) -> str | None:
        settings = get_settings()
        if not settings.GEMINI_API_KEY:
            return None
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        model = model_for(RequestClass.STANDARD).model  # Flash multimodal (router-chosen)
        resp = client.models.generate_content(
            model=model,
            contents=[
                types.Part.from_bytes(data=png, mime_type="image/png"),
                "In one or two sentences, describe what the user is working on in "
                "this screenshot. Do not transcribe sensitive data.",
            ],
            config=types.GenerateContentConfig(max_output_tokens=120),
        )
        return (resp.text or "").strip()
