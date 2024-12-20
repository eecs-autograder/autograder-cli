import subprocess
from pathlib import Path

import yaml

_INSTRUCTOR_FILE_TESTS_DIR = Path(__file__).parent.resolve()


def test_instructor_files():
    cmd_base = "python -m ag_contrib -u http://localhost:9002"

    for stage in ["create", "update"]:
        dirname = _INSTRUCTOR_FILE_TESTS_DIR / stage
        create_filename = dirname / "initial" / "project.yml"
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
                dirname / "actual" / "project.yml",
            ],
            check=True,
            timeout=30,
        )

        subprocess.run(
            [
                "diff",
                "-r",
                dirname / "expected" / "project.yml",
                dirname / "actual" / "project.yml",
            ],
            check=True,
        )
