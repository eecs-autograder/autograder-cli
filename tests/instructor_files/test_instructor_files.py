import subprocess
from pathlib import Path

import yaml

_INSTRUCTOR_FILE_TESTS_DIR = Path(__file__).parent.resolve()


def test_instructor_files():
    cmd_base = "ag -t tests.agtoken -u http://localhost:9002"

    for stage in ["create", "update"]:
        dirname = _INSTRUCTOR_FILE_TESTS_DIR / stage
        config_filename = dirname / "initial" / "agproject.yml"
        subprocess.run(
            cmd_base.split() + f"project save -f {config_filename}".split(),
            check=True,
            timeout=30,
        )

        with open(config_filename) as f:
            raw = yaml.safe_load(f)
            project_name = raw["project"]["name"]
            course_name = raw["project"]["course"]["name"]
            course_semester = raw["project"]["course"]["semester"]
            course_year = str(raw["project"]["course"]["year"])

        (dirname / "actual").mkdir(exist_ok=True)

        subprocess.run(
            cmd_base.split()
            + [
                "project",
                "load",
                course_name,
                course_semester,
                course_year,
                project_name,
                dirname / "actual" / "agproject.yml",
            ],
            check=True,
            timeout=30,
        )

        subprocess.run(
            [
                "diff",
                "-r",
                dirname / "expected" / "agproject.yml",
                dirname / "actual" / "agproject.yml",
            ],
            check=True,
        )

    # Check for a warning message when files are removed from the yaml
    # file (including globs) but still exist on the autograder
    config_filename = _INSTRUCTOR_FILE_TESTS_DIR / "remove_from_yml_only" / "agproject.yml"
    result = subprocess.run(
        cmd_base.split() + f"project save -f {config_filename}".split(),
        check=True,
        timeout=30,
        capture_output=True,
        text=True,
    )
    print(result.stdout, flush=True)
    assert "!! WARNING !! The instructor file file1.txt" in result.stdout
    assert "!! WARNING !! The instructor file test42.py" in result.stdout
