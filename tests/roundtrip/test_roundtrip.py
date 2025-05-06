import subprocess
from pathlib import Path

import pytest
import yaml

_ROUNDTRIP_TESTS_DIR = Path(__file__).parent.resolve()


@pytest.mark.parametrize(
    "roundtrip_test_dir",
    _ROUNDTRIP_TESTS_DIR.glob("**/*.test"),
    ids=lambda path: str(path.relative_to(_ROUNDTRIP_TESTS_DIR)),
)
def test_roundtrip(roundtrip_test_dir: Path):
    print(roundtrip_test_dir)

    cmd_base = "ag -t tests.agtoken -u http://localhost:9002"
    if (cutoff_preference_file := roundtrip_test_dir / "deadline_cutoff_preference").exists():
        with open(cutoff_preference_file) as f:
            deadline_cutoff_preference = ["-d", f.read().strip()]
    else:
        deadline_cutoff_preference = []

    create_filename = roundtrip_test_dir / "agproject.create.yml"
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
        cmd_base.split()
        + [
            "project",
            "load",
            course_name,
            course_semester,
            course_year,
            project_name,
            roundtrip_test_dir / "agproject.create.actual.yml",
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
            roundtrip_test_dir / "agproject.create.expected.yml",
            roundtrip_test_dir / "agproject.create.actual.yml",
        ],
        check=True,
    )

    subprocess.run(
        cmd_base.split()
        + f"project save -f {roundtrip_test_dir / 'agproject.update.yml'}".split(),
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
            roundtrip_test_dir / "agproject.update.actual.yml",
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
            roundtrip_test_dir / "agproject.update.expected.yml",
            roundtrip_test_dir / "agproject.update.actual.yml",
        ],
        check=True,
    )
