"""
Sets up the local stack database for roundtrip tests.
This script is invoked by <project root>/dev_scripts/test.sh
"""

import subprocess
from typing import TYPE_CHECKING

# We want to be able to run this script from other environments
# that might not have typing_extensions installed (such as
# testing the wheel package builds on CI).
if TYPE_CHECKING:
    from typing_extensions import LiteralString


def setup_db():
    print("Applying migrations")
    _run_in_django_container("python3 manage.py migrate".split(), timeout=60)

    print("Clearing db")
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

# IMPORTANT: Do not change the course name/semester/year.
# Many tests and some CI workflows depend on them having these values.
c = Course.objects.validate_and_create(name='Test Course', semester='Summer', year=2014)
c.admins.add(user)
"""
    _run_in_django_container(["python", "manage.py", "shell", "-c", clear_db])


def _run_in_django_container(cmd: list['LiteralString'], timeout: int = 10):
    to_run = "docker exec -i ag-cli-test-stack-django-1".split() + cmd
    print("Running command:", to_run)
    return subprocess.run(to_run, timeout=timeout, check=True)


if __name__ == "__main__":
    setup_db()
