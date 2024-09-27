import datetime
import re
import zoneinfo
from typing import overload
from zoneinfo import ZoneInfo

from dateutil.parser import parse as parse_datetime


def validate_time(value: object) -> datetime.time | None:
    parsed = parse_datetime(value) if isinstance(value, str) else value
    if not isinstance(parsed, datetime.datetime):
        raise ValueError("Unrecognized time format.")

    return parsed.time()


def validate_duration(value: object) -> datetime.timedelta:
    if isinstance(value, datetime.timedelta):
        return value

    error_msg = 'Expected a time string in the format "XdXhXm"'
    if not isinstance(value, str):
        raise ValueError(error_msg)

    match = re.match(
        r"""\s*(((?P<days>\d+)\s*d)?)
        \s*(((?P<hours>\d+)\s*h)?)
        \s*(((?P<minutes>\d+)\s*m)?)""",
        value,
        re.VERBOSE,
    )
    if match is None or not (matches := match.groupdict(0)):
        raise ValueError(error_msg)

    return datetime.timedelta(
        days=int(matches["days"]),
        hours=int(matches["hours"]),
        minutes=int(matches["minutes"]),
    )


def serialize_duration(value: datetime.timedelta) -> str:
    days = value.days
    seconds = value.seconds

    hours = seconds // 3600
    seconds %= 3600

    minutes = seconds // 60

    result = ""
    if days:
        result += f"{days}d"

    if hours:
        result += f"{hours}h"

    if minutes:
        result += f"{minutes}m"

    return result


@overload
def validate_datetime(value: str) -> datetime.datetime: ...


@overload
def validate_datetime(value: None) -> None: ...


@overload
def validate_datetime(value: object) -> datetime.datetime | None: ...


def validate_datetime(value: object) -> datetime.datetime | None:
    if value is None:
        return None

    parsed = parse_datetime(value) if isinstance(value, str) else value
    if not isinstance(parsed, datetime.datetime):
        raise ValueError("Unrecognized datetime format.")

    return parsed


def serialize_datetime(value: datetime.datetime):
    return value.strftime("%b %d, %Y %I:%M%p")


def validate_timezone(timezone: object) -> ZoneInfo:
    if isinstance(timezone, ZoneInfo):
        return timezone

    if not isinstance(timezone, str):
        raise ValueError("Expected a string representing a timezone.")

    # TODO/Future: Once the API has an endpoint of supported timezones,
    # load from there instead.
    if timezone not in zoneinfo.available_timezones():
        raise ValueError("Unrecognized timezone.")

    return ZoneInfo(timezone)


def serialize_timezone(timezone: ZoneInfo) -> str:
    return timezone.key
