import datetime
import re
import zoneinfo
from typing import overload
from zoneinfo import ZoneInfo

from dateutil.parser import parse as parse_datetime
from pydantic import SerializationInfo


def validate_time(value: object) -> datetime.time:
    if isinstance(value, datetime.time):
        return value

    error_msg = 'Expected a time string in the format "[h]h:mm [am/pm]"'

    # In certain cases where we'd expect YAML to parse as a time,
    # it instead parses as sexagesimal (base 60) integers.
    # See section 2.4: https://yaml.org/spec/1.1/
    if isinstance(value, int):
        hour = value // 60
        minute = value % 60

        # We don't support times with seconds.
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError(error_msg)

        return datetime.time(hour=hour, minute=minute)

    if not isinstance(value, str):
        raise ValueError(error_msg)

    match = re.match(
        r"""\s*
        (?P<hour>\d\d?):
        (?P<minute>\d\d)
        (:\d\d)?  # Discard seconds
        \s*
        (?P<ampm>(am)|(AM)|(pm)|(PM))?
        \s*""",
        value,
        re.VERBOSE,
    )

    if match is None or not (matches := match.groupdict()):
        raise ValueError(error_msg)

    hour = int(matches["hour"])
    minute = int(matches["minute"])
    if (ampm := matches["ampm"]) is not None and ampm in ["pm", "PM"] and hour != 12:
        hour += 12

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError(error_msg)

    return datetime.time(
        hour=hour,
        minute=minute,
    )


def serialize_time(value: datetime.time, info: SerializationInfo):
    if (context := info.context) is not None and context.get("write_yaml", False):
        return value.strftime("%I:%M%p")

    return value.isoformat()


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

    return result if result else "0h0m"


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
