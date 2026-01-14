"""
Infrastructure for running tests with the following structure:
- Save a project from a YAML config file
- Check and/or modify the project state directly from the API
- Load the project to a YAML config file and check values
"""

import subprocess
from pathlib import Path

import pytest
import yaml

_SAVE_MODIFY_LOAD_TESTS_DIR = Path(__file__).parent.resolve()


@pytest.mark.parametrize(
    "save_modify_load_test_dir",
    _SAVE_MODIFY_LOAD_TESTS_DIR.glob("**/*.test"),
    ids=lambda path: str(path.relative_to(_SAVE_MODIFY_LOAD_TESTS_DIR)),
)
def test_save_modify_load(save_modify_load_test_dir: Path):
    print(save_modify_load_test_dir)

    cmd_base = "ag -t tests.agtoken -u http://localhost:9002"
    if (
        cutoff_preference_file := save_modify_load_test_dir / "deadline_cutoff_preference"
    ).exists():
        with open(cutoff_preference_file) as f:
            deadline_cutoff_preference = ["-d", f.read().strip()]
    else:
        deadline_cutoff_preference = []

    create_filename = save_modify_load_test_dir / "agproject.yml"
    subprocess.run(
        cmd_base.split() + f"project save -f {create_filename}".split(),
        check=True,
        timeout=30,
    )

    with open(create_filename) as f:
        raw = yaml.safe_load(f)
        project_name = raw["project"]["name"]
        course_name = raw["project"]["course"]["name"]
        course_semester = raw["project"]["course"]["semester"]
        course_year = str(raw["project"]["course"]["year"])

    subprocess.run(
        [
            "python3",
            save_modify_load_test_dir / "modify_step.py",
            course_name,
            course_semester,
            course_year,
            project_name,
        ],
        check=True,
        timeout=30,
    )

    subprocess.run(
        cmd_base.split()
        + [
            "project",
            "load",
            course_name,
            course_semester,
            course_year,
            project_name,
            save_modify_load_test_dir / "agproject.actual.yml",
        ]
        + deadline_cutoff_preference,
        check=True,
        timeout=30,
    )

    subprocess.run(
        [
            "dyff",
            "between",
            "--set-exit-code",
            save_modify_load_test_dir / "agproject.expected.yml",
            save_modify_load_test_dir / "agproject.actual.yml",
        ],
        check=True,
    )
