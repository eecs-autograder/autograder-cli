import datetime
from decimal import Decimal
from pathlib import Path

from tzlocal import get_localzone

from .autograder_io_schema.schema import Semester
from .models import (
    AGConfig,
    CourseSelection,
    DeadlineWithRelativeCutoff,
    FnmatchExpectedStudentFile,
    HandgradingAnnotationConfig,
    HandgradingConfig,
    HandgradingCriterionConfig,
    InstructorFileConfig,
    MultiCmdTestCaseConfig,
    MultiCommandConfig,
    MutationSuiteConfig,
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
            "hello.py",
            FnmatchExpectedStudentFile(pattern="test_*.py", min_num_matches=1, max_num_matches=3),
        ],
        instructor_files=[InstructorFileConfig(local_path=Path("instructor_file.txt"))],
        test_suites=[
            TestSuiteConfig(
                name="Suite 1",
                setup_suite_cmd=(
                    'echo "Configure your setup command here. Set to empty string to not use a setup command"'
                ),
                setup_suite_cmd_name="Setup",
                test_cases=[
                    SingleCmdTestCaseConfig(name="Test 1", cmd='echo "Hello 1!"'),
                    MultiCmdTestCaseConfig(
                        name="Test 2",
                        commands=[MultiCommandConfig(name="Test 2", cmd='echo "Hello 2!"')],
                    ),
                ],
            )
        ],
        mutation_suites=[
            MutationSuiteConfig(
                name="Mutation Suite 1",
                student_files_needed=["test_*.py"],
                bug_names={"bug1": ["Hint 1", "Hint 2"], "bug2": ["Hint 1"]},
                points_per_bug=Decimal(3),
            )
        ],
        handgrading=HandgradingConfig(
            points_style="start_at_zero_and_add",
            criteria=[
                HandgradingCriterionConfig(
                    short_description="Main function not too long",
                    long_description="The program's main() function should "
                    "be split up into smaller functions to improve maintainability",
                    points=3,
                )
            ],
            annotations=[
                HandgradingAnnotationConfig(
                    short_description="Poor choice of variable or function name",
                    long_description="Names should be descriptive and convey "
                    "their meaning and purpose. "
                    "Avoid single-letter names unless their purpose "
                    "is very clear from context or convention.",
                )
            ],
        ),
    )

    write_yaml(AGConfig(project=project), config_file, exclude_defaults=False)

    blank_instructor_file = Path(config_file).parent / Path("instructor_file.txt")
    if not blank_instructor_file.exists():
        with open(blank_instructor_file, "w") as f:
            f.write(
                "This is a file written and uploaded by the instructor. "
                "It might contain test cases or other contents needed by tests.\n"
            )
