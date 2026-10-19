from datetime import timedelta

from sqlalchemy import select

from app.core import clock
from app.core.config import settings
from app.db.models import CalendarEvent
from app.services.calendar.service import digest
from app.services.telemetry.store import iso, naive

GRACE_SECONDS = 300
MAX_REMINDERS = 50


async def schedule(calendar, session):
    metadata = await calendar.snapshot(session)
    enabled = settings.calendar_reminders_enabled
    lead = settings.calendar_reminder_lead_minutes
    scope = digest([1, calendar.config_key, enabled, lead, GRACE_SECONDS, MAX_REMINDERS])
    timestamp = clock.utcnow()
    response = dict(
        version=1,
        policy_scope=scope,
        source_id=calendar.config_key,
        enabled=enabled,
        configured=metadata["configured"],
        stale=metadata["stale"],
        server_time=clock.iso_utc(timestamp),
        timezone=calendar.timezone,
        grace_seconds=GRACE_SECONDS,
        lead_minutes=lead,
        overflow=False,
        reminders=[],
    )
    if not enabled or metadata["stale"]:
        return response
    now = naive(timestamp)
    rows = list(
        (
            await session.scalars(
                select(CalendarEvent)
                .where(
                    CalendarEvent.config_key == calendar.config_key,
                    CalendarEvent.status == "confirmed",
                    CalendarEvent.busy == 1,
                    CalendarEvent.start_date.is_(None),
                    CalendarEvent.starts_at > now + timedelta(minutes=lead, seconds=-GRACE_SECONDS),
                    CalendarEvent.starts_at <= now + timedelta(days=1, minutes=lead),
                )
                .order_by(CalendarEvent.starts_at, CalendarEvent.id)
                .limit(501)
            )
        ).all()
    )
    for row in rows:
        due = row.starts_at - timedelta(minutes=lead)
        response["reminders"].append(
            dict(
                id="rmd_" + digest([scope, row.id, row.revision])[:32],
                event_id=row.id,
                event_revision=row.revision,
                due_at=iso(due),
                expires_at=iso(due + timedelta(seconds=GRACE_SECONDS)),
                due=due <= now,
            )
        )
    response["overflow"] = len(response["reminders"]) > MAX_REMINDERS
    return response


def valid_reminder(page, identity):
    for item in page["reminders"]:
        if item["id"] == identity:
            return item
    return None
