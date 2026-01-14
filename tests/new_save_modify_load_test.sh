if [ -z "$1" ]; then
    echo "Usage: $0 test_name"
    exit 1
fi

test_dir=$(dirname "$(realpath $0)")/save_modify_load/$1
[[ $test_dir == *.test ]] || test_dir+=.test
echo $test_dir

if [ -d $test_dir ]; then
    echo This test case directory already exists
    exit 1
fi
mkdir -p $test_dir

proj_uuid=$(python -c "import uuid; print(uuid.uuid4().hex)")

cat > $test_dir/agproject.yml <<- EOM
project:
  name: Test Project $proj_uuid
  timezone: America/Chicago
  course:
    name: Test Course
    semester: Summer
    year: 2014
  settings:
EOM

cp $test_dir/agproject.yml $test_dir/agproject.expected.yml

echo "relative" > $test_dir/deadline_cutoff_preference
cat > $test_dir/modify_step.py <<- EOM
import argparse
import json
import subprocess
from typing import Any
from urllib.parse import quote, urljoin
from urllib.request import urlopen

BASE_URL = "http://localhost:9002/"


def main():
    args = parse_args()

    course = _get(
        f"/api/course/{args.course_name}/{args.course_semester}/{args.course_year}/"
    )
    projects = _get(f"/api/courses/{course['pk']}/projects/")
    project = next(p for p in projects if p["name"] == args.project_name)
    assert (
        project is not None
    ), f"Project {args.course_name} {args.course_semester} {args.course_year} {args.project_name} not found"

    print("FIXME: Finish implementing this step")


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
EOM
