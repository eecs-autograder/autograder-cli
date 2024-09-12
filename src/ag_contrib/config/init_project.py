from pathlib import Path
import yaml

from ag_contrib.config.generated.schema import Semester
from ag_contrib.config.models import (
    AGConfig,
    CourseSelection,
    InstructorFileConfig,
    MultiCmdTestCaseConfig,
    MultiCommandConfig,
    ProjectConfig,
    SingleCmdTestCaseConfig,
    TestSuiteConfig,
)
from ag_contrib.config.generated import schema as ag_schema


def init_project(
    project_name: str,
    course_name: str,
    course_term: Semester,
    course_year: int,
    config_file: str,
    **kwargs: object,
):
    project = ProjectConfig(
        name=project_name,
        course=CourseSelection(name=course_name, semester=course_term, year=course_year),
        student_files=[
            ag_schema.CreateExpectedStudentFile(
                pattern="hello.py", min_num_matches=1, max_num_matches=1
            )
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

    with open(config_file, "w") as f:
        yaml.dump(AGConfig(project=project).model_dump(mode="json"), f, sort_keys=False)

    blank_instructor_file = Path(config_file).parent / Path("instructor_file.txt")
    print(blank_instructor_file)
    if not blank_instructor_file.exists():
        with open(blank_instructor_file, "w") as f:
            f.write(
                "This is a file written and uploaded by the instructor. "
                "It might contain test cases or other contents needed by tests.\n"
            )