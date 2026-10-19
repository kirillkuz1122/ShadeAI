"""Ограниченный reader развёрнутого CalDAV: без RRULE-движка и внешних ссылок."""

import hashlib
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

MAX_BYTES = 1_048_576
MAX_EVENTS = 500
DAV = "{DAV:}"
CAL = "{urn:ietf:params:xml:ns:caldav}"


class CalendarError(Exception):
    def __init__(self, code="CALENDAR_BAD_RESPONSE"):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class Event:
    uid_hash: str
    recurrence: str
    summary: str
    location: str | None
    start: datetime | None
    end: datetime | None
    start_date: str | None
    end_date: str | None
    status: str
    busy: bool


def aware(local: datetime, zone: ZoneInfo) -> datetime:
    choices = {
        local.replace(tzinfo=zone, fold=fold).astimezone(UTC)
        for fold in (0, 1)
        if local.replace(tzinfo=zone, fold=fold)
        .astimezone(UTC)
        .astimezone(zone)
        .replace(tzinfo=None)
        == local
    }
    if len(choices) != 1:
        raise CalendarError("CALENDAR_BAD_TIME")
    return choices.pop()


def unescape(value: str, maximum: int) -> str:
    if re.search(r"\\(?![nN,;\\])", value):
        raise CalendarError()
    value = re.sub(r"\\([nN,;\\])", lambda m: "\n" if m[1] in "nN" else m[1], value)
    if len(value) > maximum or any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise CalendarError("CALENDAR_LIMIT")
    return value


def property_line(line):
    quoted = False
    for index, char in enumerate(line):
        if char == '"':
            quoted = not quoted
        if char == ":" and not quoted:
            head, value = line[:index], line[index + 1 :]
            name = head.split(";", 1)[0].upper()
            if not re.fullmatch(r"[A-Z0-9-]+", name):
                raise CalendarError()
            return name, head, value
    raise CalendarError()


def parse_time(prop, timezone):
    _, head, value = prop
    params = {}
    for param in head.split(";")[1:]:
        key, sep, raw = param.partition("=")
        if not sep or key.upper() in params:
            raise CalendarError()
        params[key.upper()] = raw.strip('"')
    if set(params) - {"VALUE", "TZID"}:
        raise CalendarError("CALENDAR_UNSUPPORTED")
    if params.get("VALUE") == "DATE":
        if "TZID" in params or not re.fullmatch(r"\d{8}", value):
            raise CalendarError()
        local = date(int(value[:4]), int(value[4:6]), int(value[6:]))
        return aware(datetime.combine(local, time.min), ZoneInfo(timezone)), local.isoformat()
    if params.get("VALUE", "DATE-TIME") != "DATE-TIME" or not re.fullmatch(r"\d{8}T\d{6}Z?", value):
        raise CalendarError()
    local = datetime.strptime(value.rstrip("Z"), "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        if "TZID" in params:
            raise CalendarError()
        return local.replace(tzinfo=UTC), None
    return aware(local, ZoneInfo(params.get("TZID", timezone))), None


def event(values, timezone):
    def value(name, default=""):
        return values[name][2] if name in values else default

    uid = unescape(value("UID"), 255)
    if not uid:
        raise CalendarError()
    uid_hash = hashlib.sha256(uid.encode()).hexdigest()
    status = value("STATUS", "CONFIRMED").upper()
    if status not in {"CONFIRMED", "TENTATIVE", "CANCELLED"}:
        raise CalendarError()
    recurrence = "master"
    if "RECURRENCE-ID" in values:
        instant, day = parse_time(values["RECURRENCE-ID"], timezone)
        recurrence = "date:" + day if day else instant.isoformat()
    summary = unescape(value("SUMMARY", "Событие без названия"), 200)
    location = unescape(value("LOCATION"), 255) or None
    if "DTSTART" not in values:
        if status != "CANCELLED":
            raise CalendarError()
        return Event(
            uid_hash, recurrence, summary, location, None, None, None, None, "cancelled", False
        )
    start, start_date = parse_time(values["DTSTART"], timezone)
    if "DTEND" in values and "DURATION" in values:
        raise CalendarError()
    if "DTEND" in values:
        end, end_date = parse_time(values["DTEND"], timezone)
        if bool(start_date) != bool(end_date):
            raise CalendarError()
    else:
        duration = value("DURATION")
        if duration:
            match = re.fullmatch(
                r"P(?:(\d+)W|(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?)", duration
            )
            if not match or not any(match.groups()) or duration.endswith("T"):
                raise CalendarError()
            weeks, days, hours, minutes, seconds = (int(v or 0) for v in match.groups())
            delta = timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds)
            if start_date and (hours or minutes or seconds):
                raise CalendarError()
        else:
            delta = timedelta(days=1) if start_date else timedelta(0)
        if start_date:
            end_day = date.fromisoformat(start_date) + delta
            end_date = end_day.isoformat()
            end = aware(datetime.combine(end_day, time.min), ZoneInfo(timezone))
        else:
            end_date = None
            if duration and (weeks or days):
                prop = values["DTSTART"]
                zone = ZoneInfo("UTC" if prop[2].endswith("Z") else timezone)
                for part in prop[1].split(";")[1:]:
                    if part.upper().startswith("TZID="):
                        zone = ZoneInfo(part.split("=", 1)[1].strip('"'))
                shifted = start.astimezone(zone).replace(tzinfo=None) + timedelta(
                    weeks=weeks, days=days
                )
                end = aware(shifted, zone) + timedelta(
                    hours=hours, minutes=minutes, seconds=seconds
                )
            else:
                end = start + delta
    if end < start or end - start > timedelta(days=366) or start_date and end <= start:
        raise CalendarError("CALENDAR_BAD_TIME")
    transparency = value("TRANSP", "OPAQUE")
    if transparency not in {"OPAQUE", "TRANSPARENT"}:
        raise CalendarError()
    return Event(
        uid_hash,
        recurrence,
        summary,
        location,
        start,
        end,
        start_date,
        end_date,
        status.lower(),
        transparency == "OPAQUE" and status == "CONFIRMED",
    )


def _parse_ical(text, timezone):
    if len(text.encode()) > MAX_BYTES or "\r" in text.replace("\r\n", ""):
        raise CalendarError("CALENDAR_LIMIT")
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if len(line) > 8192:
            raise CalendarError("CALENDAR_LIMIT")
        if line.startswith((" ", "\t")):
            if not lines:
                raise CalendarError()
            lines[-1] += line[1:]
            if len(lines[-1]) > 8192:
                raise CalendarError("CALENDAR_LIMIT")
        elif line:
            lines.append(line)
    stack, events, values = [], [], None
    version = None
    for line in lines:
        name, head, value = property_line(line)
        if name == "BEGIN":
            if value in {"VTIMEZONE", "VTODO", "VFREEBUSY"}:
                raise CalendarError("CALENDAR_UNSUPPORTED")
            if not stack and value != "VCALENDAR" or len(stack) > 3:
                raise CalendarError()
            if value == "VEVENT":
                if stack != ["VCALENDAR"]:
                    raise CalendarError()
                values = {}
            stack.append(value)
        elif name == "END":
            if not stack or stack.pop() != value:
                raise CalendarError()
            if value == "VEVENT":
                events.append(event(values, timezone))
                values = None
                if len(events) > MAX_EVENTS:
                    raise CalendarError("CALENDAR_LIMIT")
        elif not stack:
            raise CalendarError()
        elif stack == ["VCALENDAR"] and name == "VERSION":
            if version is not None or value != "2.0":
                raise CalendarError("CALENDAR_UNSUPPORTED")
            version = value
        elif name in {"RRULE", "RDATE", "EXRULE", "EXDATE"}:
            raise CalendarError("CALENDAR_EXPANSION_REQUIRED")
        elif stack[-1] == "VEVENT" and name in {
            "UID",
            "SUMMARY",
            "LOCATION",
            "DTSTART",
            "DTEND",
            "DURATION",
            "RECURRENCE-ID",
            "STATUS",
            "TRANSP",
        }:
            if name in values:
                raise CalendarError()
            values[name] = (name, head, value)
    if (
        version != "2.0"
        or stack
        or not lines
        or lines[0] != "BEGIN:VCALENDAR"
        or lines[-1] != "END:VCALENDAR"
    ):
        raise CalendarError()
    return events


def parse_ical(text, timezone):
    try:
        return _parse_ical(text, timezone)
    except CalendarError:
        raise
    except (ValueError, KeyError, TypeError, OverflowError):
        raise CalendarError() from None


def parse_report(body: bytes, timezone: str, start: datetime, end: datetime):
    if len(body) > MAX_BYTES:
        raise CalendarError("CALENDAR_LIMIT")
    try:
        document = body.decode("utf-8")
        if "<!DOCTYPE" in document.upper() or "<!ENTITY" in document.upper():
            raise CalendarError()
        tree = ET.fromstring(document)
        if tree.tag != DAV + "multistatus" or sum(1 for _ in tree.iter()) > 5000:
            raise CalendarError()
        output = []
        for response in tree:
            if response.tag != DAV + "response" or not response.findtext(DAV + "href"):
                raise CalendarError()
            data = []
            for propstat in response.findall(DAV + "propstat"):
                status = propstat.findtext(DAV + "status", "").split()
                if len(status) < 2 or status[1] != "200":
                    raise CalendarError("CALENDAR_PARTIAL_RESPONSE")
                prop = propstat.find(DAV + "prop")
                if prop is None:
                    raise CalendarError()
                data.extend(prop.findall(CAL + "calendar-data"))
            if len(data) != 1 or data[0].text is None:
                raise CalendarError()
            for item in parse_ical(data[0].text, timezone):
                if (
                    item.start is None
                    or item.start < end
                    and (item.end > start or item.start >= start)
                ):
                    output.append(item)
                    if len(output) > MAX_EVENTS:
                        raise CalendarError("CALENDAR_LIMIT")
        identities = [(e.uid_hash, e.recurrence) for e in output]
        if len(set(identities)) != len(identities):
            raise CalendarError()
        return output
    except CalendarError:
        raise
    except (ValueError, KeyError, TypeError, ET.ParseError, OverflowError):
        raise CalendarError() from None
