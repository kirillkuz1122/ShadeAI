from datetime import UTC, datetime
from xml.sax.saxutils import escape

import pytest

from app.services.calendar.codec import MAX_BYTES, CalendarError, parse_ical, parse_report

START = datetime(2026, 10, 1, tzinfo=UTC)
END = datetime(2026, 12, 1, tzinfo=UTC)


def ical(*events):
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Synthetic//EN\r\n"
        + "".join("BEGIN:VEVENT\r\n" + value + "\r\nEND:VEVENT\r\n" for value in events)
        + "END:VCALENDAR\r\n"
    )


def report(*objects, status="HTTP/1.1 200 OK"):
    return (
        '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        + "".join(
            "<d:response><d:href>/calendar/synthetic/"
            + str(i)
            + ".ics</d:href><d:propstat><d:prop><c:calendar-data>"
            + escape(obj)
            + "</c:calendar-data></d:prop><d:status>"
            + status
            + "</d:status></d:propstat></d:response>"
            for i, obj in enumerate(objects)
        )
        + "</d:multistatus>"
    ).encode()


BASE = "UID:synthetic-one\r\nDTSTART:20261019T050000Z\r\nDTEND:20261019T060000Z\r\nSUMMARY:Встреча"


def test_utc_escape_fold_and_drop_private_fields():
    data = ical(
        BASE.replace("Встреча", "Длинная\\, встреча\\nсо стро\r\n кой")
        + "\r\nLOCATION:Комната\\; 1\r\nDESCRIPTION:private-description\r\nATTENDEE:mailto:private@example.invalid\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\nATTACH:https://example.invalid/private\r\nEND:VALARM"
    )
    rows = parse_report(report(data), "Asia/Yekaterinburg", START, END)
    assert len(rows) == 1 and rows[0].summary == "Длинная, встреча\nсо строкой"
    assert rows[0].location == "Комната; 1" and rows[0].start == datetime(
        2026, 10, 19, 5, tzinfo=UTC
    )
    assert rows[0].busy and rows[0].status == "confirmed"
    assert "private" not in repr(rows[0]) and "synthetic-one" not in repr(rows[0])
    assert len(rows[0].uid_hash) == 64


def test_expanded_recurrences_have_distinct_stable_identity_and_moved_override():
    first = BASE
    second = (
        BASE.replace("20261019T050000Z", "20261020T070000Z").replace(
            "20261019T060000Z", "20261020T080000Z"
        )
        + "\r\nRECURRENCE-ID:20261020T050000Z"
    )
    events = parse_report(report(ical(first, second)), "UTC", START, END)
    assert len(events) == 2 and events[0].uid_hash == events[1].uid_hash
    assert events[0].recurrence == "master" and events[1].recurrence == "2026-10-20T05:00:00+00:00"
    changed = second.replace("20261020T070000Z", "20261020T090000Z").replace(
        "20261020T080000Z", "20261020T100000Z"
    )
    other = parse_report(report(ical(changed)), "UTC", START, END)[0]
    assert other.recurrence == events[1].recurrence and other.start != events[1].start


def test_all_day_exclusive_end_dst_and_default_one_day():
    event = "UID:all-day\r\nDTSTART;VALUE=DATE:20261025\r\nDTEND;VALUE=DATE:20261026"
    item = parse_report(report(ical(event)), "Europe/Berlin", START, END)[0]
    assert item.start_date == "2026-10-25" and item.end_date == "2026-10-26"
    assert (item.end - item.start).total_seconds() == 25 * 3600
    default = parse_report(report(ical(event.split("\r\nDTEND")[0])), "Europe/Berlin", START, END)[
        0
    ]
    assert default.end == item.end


def test_floating_and_iana_timezone_normalize_without_host_timezone():
    data = "UID:floating\r\nDTSTART:20261019T100000\r\nDURATION:PT1H"
    item = parse_report(report(ical(data)), "Asia/Yekaterinburg", START, END)[0]
    assert item.start.hour == 5 and item.end.hour == 6
    zoned = data.replace("DTSTART:", "DTSTART;TZID=Asia/Yekaterinburg:")
    assert parse_report(report(ical(zoned)), "UTC", START, END)[0].start == item.start


@pytest.mark.parametrize("value", ["20261025T023000", "20260329T023000"])
def test_ambiguous_or_nonexistent_floating_time_is_not_guessed(value):
    data = "UID:dst\r\nDTSTART:" + value
    with pytest.raises(CalendarError):
        parse_ical(ical(data), "Europe/Berlin")


def test_cancel_marker_without_start_and_transparency():
    marker = parse_ical(ical("UID:synthetic-one\r\nSTATUS:CANCELLED"), "UTC")[0]
    assert marker.start is None and marker.status == "cancelled" and not marker.busy
    normal = parse_ical(ical(BASE + "\r\nTRANSP:TRANSPARENT"), "UTC")[0]
    tentative = parse_ical(ical(BASE + "\r\nSTATUS:TENTATIVE"), "UTC")[0]
    assert not normal.busy and not tentative.busy


@pytest.mark.parametrize(
    "extra", ["RRULE:FREQ=DAILY", "RDATE:20261020T050000Z", "EXDATE:20261019T050000Z"]
)
def test_unexpanded_recurrence_never_becomes_partial_success(extra):
    with pytest.raises(CalendarError, match="CALENDAR_EXPANSION_REQUIRED"):
        parse_report(report(ical(BASE + "\r\n" + extra)), "UTC", START, END)


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s + "\r\nUID:second",
        lambda s: s.replace("T060000Z", "T040000Z"),
        lambda s: s.replace("20261019T050000Z", "bad-private-value"),
        lambda s: s.replace("DTSTART:", "DTSTART;TZID=Invalid/Private:"),
        lambda s: s + "\r\nDURATION:PT1H",
        lambda s: s + "\r\nSUMMARY:duplicate",
        lambda s: s + "\r\nLOCATION:" + "x" * 256,
    ],
)
def test_invalid_input_returns_fixed_error_without_raw(change):
    with pytest.raises(CalendarError) as caught:
        parse_report(report(ical(change(BASE))), "UTC", START, END)
    assert "private" not in str(caught.value)


def test_xml_partial_duplicate_entities_and_limits():
    with pytest.raises(CalendarError):
        parse_report(report(ical(BASE), status="HTTP/1.1 404 Missing"), "UTC", START, END)
    with pytest.raises(CalendarError):
        parse_report(report(ical(BASE), ical(BASE)), "UTC", START, END)
    for body in [
        b'<!DOCTYPE x [<!ENTITY a "private">]><x>&a;</x>',
        b"not xml",
        b"x" * (MAX_BYTES + 1),
        "<!DOCTYPE x><x/>".encode("utf-16"),
    ]:
        with pytest.raises(CalendarError):
            parse_report(body, "UTC", START, END)
    with pytest.raises(CalendarError):
        parse_report(
            report(ical(*[BASE.replace("synthetic-one", f"id-{i}") for i in range(501)])),
            "UTC",
            START,
            END,
        )


def test_no_version_unknown_version_mismatched_end_and_zero_range():
    for value in [
        ical(BASE).replace("VERSION:2.0\r\n", ""),
        ical(BASE).replace("VERSION:2.0", "VERSION:9.0"),
        ical(BASE).replace("END:VEVENT", "END:VALARM"),
    ]:
        with pytest.raises(CalendarError):
            parse_ical(value, "UTC")
    assert parse_report(report(ical(BASE)), "UTC", datetime(2026, 10, 19, 6, tzinfo=UTC), END) == []
    assert parse_report(report(), "UTC", START, END) == []


def test_nominal_duration_days_respect_dst_while_hours_are_elapsed():
    source = "UID:duration-dst\r\nDTSTART;TZID=Europe/Berlin:20260328T120000\r\nDURATION:P1D"
    day = parse_ical(ical(source), "UTC")[0]
    hours = parse_ical(ical(source.replace("P1D", "PT24H")), "UTC")[0]
    assert (day.end - day.start).total_seconds() == 23 * 3600
    assert (hours.end - hours.start).total_seconds() == 24 * 3600
