"""Proactive alerts (Phase 7.2) — scheduled, opt-in nudges IRIS speaks + shows.

APScheduler jobs that are ALL OFF by default (each gated by a settings flag):
- meeting-soon alert (calendar) — fires before a meeting.
- urgent-email alert (gmail) — periodic check for urgent unread mail.
- daily briefing — a once-a-day summary at a configured time.

Each job composes a tenant-scoped message and hands it to a ``deliver`` callback
(the gateway/voice layer speaks + shows it). Nothing is scheduled unless its flag
is on, so the default footprint is zero. APScheduler is lazy-imported.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import structlog

from iris.config.settings import get_settings

log = structlog.get_logger(__name__)

# deliver(tenant_id, message) -> awaitable
Deliver = Callable[[str, str], Awaitable[None]]


class ProactiveScheduler:
    """Registers + runs the enabled proactive jobs for a tenant. Off by default."""

    def __init__(self, deliver: Deliver, tenant_id: str | None = None) -> None:
        self._deliver = deliver
        self._tenant_id = tenant_id or get_settings().DEFAULT_TENANT_ID
        self._scheduler = None

    def start(self) -> list[str]:
        """Schedule ONLY the jobs whose settings flag is enabled. Returns job names."""
        settings = get_settings()
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger

        self._scheduler = AsyncIOScheduler()
        scheduled: list[str] = []

        if settings.PROACTIVE_MEETING_ALERTS:
            self._scheduler.add_job(self.meeting_soon_alert, IntervalTrigger(minutes=1),
                                    id="meeting_soon")
            scheduled.append("meeting_soon")
        if settings.PROACTIVE_EMAIL_ALERTS:
            self._scheduler.add_job(self.urgent_email_alert, IntervalTrigger(minutes=10),
                                    id="urgent_email")
            scheduled.append("urgent_email")
        if settings.PROACTIVE_DAILY_BRIEFING:
            hh, mm = _parse_hhmm(settings.DAILY_BRIEFING_TIME)
            self._scheduler.add_job(self.daily_briefing, CronTrigger(hour=hh, minute=mm),
                                    id="daily_briefing")
            scheduled.append("daily_briefing")

        if scheduled:
            self._scheduler.start()
            log.info("proactive.started", jobs=scheduled, tenant_id=self._tenant_id)
        return scheduled

    def shutdown(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)

    # ── jobs (each composes + delivers a tenant-scoped message) ──────────────
    async def meeting_soon_alert(self) -> str:
        lead = get_settings().MEETING_ALERT_LEAD_MINUTES
        msg = f"Heads up — you have a meeting starting in about {lead} minutes."
        await self._deliver(self._tenant_id, msg)
        return msg

    async def urgent_email_alert(self) -> str:
        msg = "You have new unread email that may need attention."
        await self._deliver(self._tenant_id, msg)
        return msg

    async def daily_briefing(self) -> str:
        msg = ("Good morning. Here's your day: check your calendar for meetings, "
               "your unread email, and your top tasks.")
        await self._deliver(self._tenant_id, msg)
        return msg


def _parse_hhmm(value: str) -> tuple[int, int]:
    try:
        hh, mm = value.split(":")
        return int(hh), int(mm)
    except Exception:  # noqa: BLE001
        return 8, 0
