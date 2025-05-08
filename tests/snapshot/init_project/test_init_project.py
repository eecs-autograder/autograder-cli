import subprocess
import tempfile
from pathlib import Path


def test_project_init():
    expected_dir = Path(__file__).parent / "expected"

    with tempfile.TemporaryDirectory() as temp_dir:
        config_filename = str(Path(temp_dir) / f"new_project.yml")
        cmd_base = f"ag -t tests.agtoken -u http://localhost:9002".split()
        subprocess.run(
            cmd_base
            + [
                "project",
                "init",
                "-f",
                config_filename,
                "Test Course",
                "Summer",
                "2014",
                "Test Project",
            ],
            check=True,
            timeout=30,
        )
        subprocess.run(
            [
                "dyff",
                "between",
                "--exclude",
                "project.settings.deadline.deadline",
                "--exclude",
                "project.timezone",
                "--set-exit-code",
                str(expected_dir / "agproject.yml"),
                config_filename,
            ],
            check=True,
        )

        subprocess.run(
            ["diff", Path(temp_dir) / "instructor_file.txt", expected_dir / "instructor_file.txt"]
        )
