import subprocess
from pathlib import Path

import pytest
from typing_extensions import LiteralString

_ROUNDTRIP_TESTS_DIR = Path(__file__).parent.resolve()


@pytest.fixture(scope="module", autouse=True)
def apply_migrations():
    _run_in_django_container("python3 manage.py migrate".split(), timeout=60)


@pytest.fixture(autouse=True)
def setup_db():
    print("Resetting db")
    # Because of the overhead in flushing the database using manage.py flush,
    # we'll instead delete all objects in the "top-level" tables that all
    # the other data depends on.
    clear_db = """import shutil
from django.core.cache import cache;
from django.contrib.auth.models import User
from autograder.core.models import Course, SandboxDockerImage, BuildSandboxDockerImageTask
Course.objects.all().delete()
User.objects.all().delete()
SandboxDockerImage.objects.exclude(name='default').delete()
BuildSandboxDockerImageTask.objects.all().delete()

shutil.rmtree('/usr/src/app/media_root_dev/', ignore_errors=True)
cache.clear()

user = User.objects.get_or_create(username='jameslp@umich.edu')[0]

c = Course.objects.validate_and_create(name='Test Course', semester='Summer', year=2014)
c.admins.add(user)
"""
    _run_in_django_container(["python", "manage.py", "shell", "-c", clear_db])


@pytest.mark.parametrize(
    "roundtrip_test_dir", _ROUNDTRIP_TESTS_DIR.glob("*.test"), ids=lambda path: path.name
)
def test_roundtrip(roundtrip_test_dir: Path):
    print(roundtrip_test_dir)

    cmd_base = "python -m ag_contrib -u http://localhost:9002"
    if (cutoff_preference_file := roundtrip_test_dir / "deadline_cutoff_preference").exists():
        with open(cutoff_preference_file) as f:
            deadline_cutoff_preference = ['-d', f.read().strip()]
    else:
        deadline_cutoff_preference = []

    subprocess.run(
        cmd_base.split() + f"project save -f {roundtrip_test_dir / 'project.create.yml'}".split(),
        check=True,
        timeout=30,
    )

    subprocess.run(
        cmd_base.split()
        + [
            "project",
            "load",
            "Test Course",
            "Summer",
            "2014",
            "Test Project",
            roundtrip_test_dir / "project.create.actual.yml",
        ]
        + deadline_cutoff_preference,
        check=True,
        timeout=30,
    )

    subprocess.run(
        [
            "diff",
            roundtrip_test_dir / "project.create.expected.yml",
            roundtrip_test_dir / "project.create.actual.yml",
        ],
        check=True,
    )

    subprocess.run(
        cmd_base.split() + f"project save -f {roundtrip_test_dir / 'project.update.yml'}".split(),
        check=True,
        timeout=30,
    )

    subprocess.run(
        cmd_base.split()
        + [
            "project",
            "load",
            "Test Course",
            "Summer",
            "2014",
            "Test Project",
            roundtrip_test_dir / "project.update.actual.yml",
        ]
        + deadline_cutoff_preference,
        check=True,
        timeout=30,
    )

    subprocess.run(
        [
            "diff",
            roundtrip_test_dir / "project.update.expected.yml",
            roundtrip_test_dir / "project.update.actual.yml",
        ],
        check=True,
    )


def _run_in_django_container(cmd: list[LiteralString], timeout: int = 10):
    to_run = "docker exec -i ag-cli-test-stack-django-1".split() + cmd
    print("Running command:", to_run)
    return subprocess.run(to_run, timeout=timeout, check=True)
