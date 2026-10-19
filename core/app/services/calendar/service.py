import asyncio
import hashlib
import json
from contextlib import suppress
from datetime import timedelta

import httpx
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from app.core import clock
from app.core.config import settings
from app.db import base
from app.db.models import CalendarEvent, CalendarSyncState
from app.services.calendar.codec import MAX_BYTES, CalendarError, parse_report
from app.services.telemetry.store import naive


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True).encode()).hexdigest()


def report_xml(start, end):
    first, last = (v.strftime("%Y%m%dT%H%M%SZ") for v in (start, end))
    return f'''<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
<d:prop><d:getetag/><c:calendar-data>
<c:expand start="{first}" end="{last}"/>
</c:calendar-data></d:prop>
<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">
<c:time-range start="{first}" end="{last}"/>
</c:comp-filter></c:comp-filter></c:filter></c:calendar-query>'''.encode()


class CalendarService:
    def __init__(self):
        self.url = settings.calendar_url
        self.timezone = settings.calendar_timezone
        self.interval = settings.calendar_interval_seconds
        self.timeout = settings.calendar_timeout_seconds
        self.username, self.password = settings.calendar_username, settings.calendar_password
        self.config_key = digest([1, self.url, self.username, self.timezone])
        self.status = "disabled" if self.url is None else "starting"
        self.task: asyncio.Task | None = None
        self.client: httpx.AsyncClient | None = None
        self.lock = asyncio.Lock()

    async def snapshot(self, session):
        from app.services.telemetry.store import iso

        state = await session.get(CalendarSyncState, 1)
        valid = state is not None and state.config_key == self.config_key
        success = state.last_success if valid else None
        now = naive(clock.utcnow())
        stale = (
            success is None
            or self.status != "ready"
            or not now - timedelta(seconds=self.interval * 2)
            <= success
            <= now + timedelta(seconds=5)
        )
        return dict(
            status=self.status,
            configured=self.url is not None,
            stale=stale,
            timezone=self.timezone,
            last_success=iso(success),
            window_start=iso(state.window_start) if valid else None,
            window_end=iso(state.window_end) if valid else None,
            error_code=state.error_code if valid else None,
        )

    async def start(self):
        if self.task is not None:
            return
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            await session.execute(
                delete(CalendarEvent).where(CalendarEvent.config_key != self.config_key)
            )
            await session.execute(
                delete(CalendarSyncState).where(CalendarSyncState.config_key != self.config_key)
            )
        if self.url is not None:
            self.task = asyncio.create_task(self.loop())

    async def close(self):
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    async def loop(self):
        while True:
            try:
                await self.sync()
            except asyncio.CancelledError:
                raise
            except CalendarError:
                pass
            await asyncio.sleep(self.interval)

    async def download(self, start, end):
        if self.client is None:
            auth = httpx.BasicAuth(self.username, self.password) if self.username else None
            self.client = httpx.AsyncClient(
                auth=auth,
                trust_env=False,
                proxy=None,
                follow_redirects=False,
                timeout=self.timeout,
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
            )
        try:
            async with asyncio.timeout(self.timeout):
                async with self.client.stream(
                    "REPORT",
                    self.url,
                    content=report_xml(start, end),
                    headers={
                        "Depth": "1",
                        "Content-Type": "application/xml; charset=utf-8",
                        "Accept": "application/xml",
                    },
                ) as response:
                    code = response.status_code
                    if code in {401, 403}:
                        raise CalendarError("CALENDAR_AUTH_FAILED")
                    if 300 <= code < 400:
                        raise CalendarError("CALENDAR_REDIRECT_BLOCKED")
                    if code in {400, 404, 405, 501}:
                        raise CalendarError("CALENDAR_UNSUPPORTED")
                    if code != 207:
                        raise CalendarError("CALENDAR_UNAVAILABLE")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > MAX_BYTES:
                            raise CalendarError("CALENDAR_LIMIT")
                        body.extend(chunk)
                    return bytes(body)
        except CalendarError:
            raise
        except (httpx.HTTPError, TimeoutError):
            raise CalendarError("CALENDAR_UNAVAILABLE") from None

    async def failure(self, code, now):
        self.status = code
        try:
            async with base.async_session() as session, session.begin():
                await session.connection(execution_options={"sqlite_immediate": True})
                state = await session.get(CalendarSyncState, 1)
                if state is None or state.config_key != self.config_key:
                    state = CalendarSyncState(id=1, config_key=self.config_key, last_attempt=now)
                    state = await session.merge(state)
                else:
                    state.last_attempt = now
                state.error_code = code
        except SQLAlchemyError:
            self.status = "CALENDAR_STORAGE_ERROR"

    async def sync(self):
        if self.url is None:
            return
        async with self.lock:
            now = clock.utcnow()
            start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)
            end = start + timedelta(days=67)
            self.status = "syncing"
            try:
                # Запас48ч покрывает различия timezone коллекции для floating/DATE.
                body = await self.download(start - timedelta(days=2), end + timedelta(days=2))
                events = await asyncio.to_thread(parse_report, body, self.timezone, start, end)
                await self.apply(events, naive(now), naive(start), naive(end))
            except asyncio.CancelledError:
                raise
            except CalendarError as error:
                await self.failure(error.code, naive(now))
                raise
            except SQLAlchemyError:
                await self.failure("CALENDAR_STORAGE_ERROR", naive(now))
                raise CalendarError("CALENDAR_STORAGE_ERROR") from None
            self.status = "ready"

    async def apply(self, events, now, start, end):
        cancel_series = {e.uid_hash for e in events if e.start is None and e.recurrence == "master"}
        if any(
            e.start is not None and e.status != "cancelled" and e.uid_hash in cancel_series
            for e in events
        ):
            raise CalendarError()
        async with base.async_session() as session, session.begin():
            await session.connection(execution_options={"sqlite_immediate": True})
            rows = list(
                (
                    await session.scalars(
                        select(CalendarEvent)
                        .where(CalendarEvent.config_key == self.config_key)
                        .limit(1001)
                    )
                ).all()
            )
            if len(rows) > 1000:
                raise CalendarError("CALENDAR_LIMIT")
            previous = {r.id: r for r in rows}
            seen = set()
            for event in events:
                identity = "cal_" + digest([self.config_key, event.uid_hash, event.recurrence])[:32]
                row = previous.get(identity)
                if event.start is None:
                    for old in rows:
                        if old.uid_hash == event.uid_hash and (
                            event.recurrence == "master" or old.recurrence == event.recurrence
                        ):
                            if old.status != "cancelled":
                                old.status, old.busy, old.revision, old.updated_at = (
                                    "cancelled",
                                    0,
                                    old.revision + 1,
                                    now,
                                )
                            seen.add(old.id)
                    continue
                fields = dict(
                    summary=event.summary,
                    location=event.location,
                    starts_at=naive(event.start),
                    ends_at=naive(event.end),
                    start_date=event.start_date,
                    end_date=event.end_date,
                    status=event.status,
                    busy=int(event.busy),
                )
                if row is None:
                    row = CalendarEvent(
                        id=identity,
                        config_key=self.config_key,
                        uid_hash=event.uid_hash,
                        recurrence=event.recurrence,
                        revision=1,
                        created_at=now,
                        updated_at=now,
                        **fields,
                    )
                    session.add(row)
                    rows.append(row)
                    previous[identity] = row
                elif any(getattr(row, k) != v for k, v in fields.items()):
                    for key, value in fields.items():
                        setattr(row, key, value)
                    row.revision += 1
                    row.updated_at = now
                seen.add(identity)
            for row in rows:
                if row.id not in seen and row.status in {"confirmed", "tentative"}:
                    row.status, row.busy, row.revision, row.updated_at = (
                        "removed",
                        0,
                        row.revision + 1,
                        now,
                    )
            retained = []
            for row in rows:
                if row.ends_at < start or row.starts_at >= end:
                    await session.delete(row)
                else:
                    retained.append(row)
            excess = max(0, len(retained) - 1000)
            terminal = sorted(
                (r for r in retained if r.status in {"removed", "cancelled"}),
                key=lambda r: (r.updated_at, r.id),
            )
            for row in terminal[:excess]:
                await session.delete(row)
            if excess > len(terminal):
                raise CalendarError("CALENDAR_LIMIT")
            await session.merge(
                CalendarSyncState(
                    id=1,
                    config_key=self.config_key,
                    last_attempt=now,
                    last_success=now,
                    window_start=start,
                    window_end=end,
                    error_code=None,
                )
            )
