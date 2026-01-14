import argparse
import datetime
import json
import subprocess
from typing import Any
from urllib.parse import quote, urljoin
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from dateutil.parser import parse as parse_datetime

BASE_URL = "http://localhost:9002/"


def main():
    args = parse_args()

    course = _get(f"/api/course/{args.course_name}/{args.course_semester}/{args.course_year}/")
    projects = _get(f"/api/courses/{course['pk']}/projects/")
    project = next(p for p in projects if p["name"] == args.project_name)
    assert (
        project is not None
    ), f"Project {args.course_name} {args.course_semester} {args.course_year} {args.project_name} not found"

    expected = datetime.datetime(
        year=2024, month=1, day=8, hour=19, minute=59, tzinfo=ZoneInfo("America/Chicago")
    )
    actual = parse_datetime(project["soft_closing_time"])
    print(actual)
    assert expected.astimezone(ZoneInfo("UTC")) == actual.astimezone(
        ZoneInfo("UTC")
    ), f"{expected.astimezone(ZoneInfo('UTC'))=} {actual=}"

    expected = datetime.datetime(
        year=2024, month=1, day=8, hour=21, minute=59, tzinfo=ZoneInfo("America/Chicago")
    )
    actual = parse_datetime(project["closing_time"])
    assert expected.astimezone(ZoneInfo("UTC")) == actual.astimezone(
        ZoneInfo("UTC")
    ), f"{expected.astimezone(ZoneInfo('UTC'))=} {actual=}"

    _patch(
        f"/api/projects/{project['pk']}/",
        {
            "soft_closing_time": str(
                datetime.datetime(
                    year=2024,
                    month=1,
                    day=8,
                    hour=11,
                    minute=0,
                    tzinfo=ZoneInfo("America/Chicago"),
                ).astimezone(ZoneInfo("UTC"))
            ),
            "closing_time": str(
                datetime.datetime(
                    year=2024,
                    month=1,
                    day=8,
                    hour=11,
                    minute=14,
                    tzinfo=ZoneInfo("America/Chicago"),
                ).astimezone(ZoneInfo("UTC"))
            ),
        },
    )


def _get(url: str):
    url = quote(urljoin(BASE_URL, url), safe=":/")
    with urlopen(url) as response:
        return json.load(response)


def _patch(url: str, data: Any):
    subprocess.run(
        [
            "ag",
            "-t",
            "tests.agtoken",
            "--base_url",
            BASE_URL,
            "http",
            "patch",
            url,
            "-j",
            f"{json.dumps(data)}",
        ],
        check=True,
        timeout=5,
    )


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("course_name")
    parser.add_argument("course_semester")
    parser.add_argument("course_year")
    parser.add_argument("project_name")

    return parser.parse_args()


if __name__ == "__main__":
    main()
