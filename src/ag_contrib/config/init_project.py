import datetime
from pathlib import Path

from tzlocal import get_localzone

from ag_contrib.config.generated.schema import Semester
from ag_contrib.config.models import (
    AGConfig,
    CourseSelection,
    DeadlineWithRelativeCutoff,
    ExactMatchExpectedStudentFile,
    FnmatchExpectedStudentFile,
    InstructorFileConfig,
    MultiCmdTestCaseConfig,
    MultiCommandConfig,
    ProjectConfig,
    ProjectSettings,
    SingleCmdTestCaseConfig,
    TestSuiteConfig,
)

from .utils import write_yaml


def init_project(
    course_name: str,
    course_term: Semester,
    course_year: int,
    project_name: str,
    config_file: str,
    **kwargs: object,
):
    project = ProjectConfig(
        name=project_name,
        timezone=get_localzone(),
        settings=ProjectSettings(
            _timezone=get_localzone(),
            deadline=DeadlineWithRelativeCutoff(
                cutoff_type="relative",
                deadline=datetime.datetime.now(get_localzone()).replace(
                    minute=0, second=0, microsecond=0
                )
                + datetime.timedelta(days=7),
            ),
        ),
        course=CourseSelection(name=course_name, semester=course_term, year=course_year),
        student_files=[
            ExactMatchExpectedStudentFile(filename="hello.py"),
            FnmatchExpectedStudentFile(pattern="test_*.py", min_num_matches=1, max_num_matches=3),
        ],
        instructor_files=[InstructorFileConfig(local_path=Path("instructor_file.txt"))],
        test_suites=[
            TestSuiteConfig(
                name="Suite 1",
                test_cases=[
                    SingleCmdTestCaseConfig(name="Test 1", cmd='echo "Hello 1!"'),
                    MultiCmdTestCaseConfig(
                        name="Test 2",
                        commands=[MultiCommandConfig(name="Test 2", cmd='echo "Hello 2!"')],
                    ),
                ],
            )
        ],
    )

    write_yaml(AGConfig(project=project), config_file, exclude_defaults=False)

    blank_instructor_file = Path(config_file).parent / Path("instructor_file.txt")
    print(blank_instructor_file)
    if not blank_instructor_file.exists():
        with open(blank_instructor_file, "w") as f:
            f.write(
                "This is a file written and uploaded by the instructor. "
                "It might contain test cases or other contents needed by tests.\n"
            )
