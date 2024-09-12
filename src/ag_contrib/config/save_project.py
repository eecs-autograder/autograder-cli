import itertools
import json
from pathlib import Path
from typing import TypeVar
from pydantic import TypeAdapter
from requests import Response
import yaml

try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader

# from ag_contrib.config.models import (
#     AGConfig,
#     AGTestCommandFeedbackConfig,
#     CommandConfig,
#     TestCaseConfig,
#     TestSuiteConfig,
# )
from ag_contrib.config.generated.schema import (
    AGTestCommandFeedbackConfig,
    AGTestSuite,
    AGTestSuiteFeedbackConfig,
    Course,
    ExpectedStudentFile,
    InstructorFile,
    Project,
    SandboxDockerImage,
)
from ag_contrib.config.models import AGConfig, TestSuiteConfig
from ag_contrib.http_client import HTTPClient, check_response_status
from ag_contrib.utils import get_api_token

g_dry_run: bool = True


def save_project(config_file: str, *, base_url: str, token_file: str):
    _ProjectSaver(config_file, base_url=base_url, token_file=token_file).save_project()


class _ProjectSaver:
    student_files: dict[str, ExpectedStudentFile] = {}
    instructor_files: dict[str, InstructorFile] = {}
    sandbox_images: dict[str, SandboxDockerImage] = {}

    def __init__(self, config_file: str, *, base_url: str, token_file: str):
        with open(config_file) as f:
            self.config = AGConfig.model_validate(yaml.load(f, Loader=Loader))

        self.project_config_dir = Path(config_file).parent

        self.base_url = base_url
        self.token_file = token_file

        self.client = HTTPClient(get_api_token(token_file), base_url)

        course_data = self.config.project.course
        self.course = do_get(
            self.client,
            f"/api/course/{course_data.name}/{course_data.semester}/{course_data.year}/",
            Course,
        )

        projects = do_get_list(
            self.client,
            f'/api/courses/{self.course["pk"]}/projects/',
            Project,
        )
        # print(projects)

        self.project = next((p for p in projects if p["name"] == self.config.project.name), None)

    def save_project(self):
        if self.project is None:
            print(f"Creating project {self.config.project.name}...")
            self.project = do_post(
                self.client,
                f'/api/courses/{self.course["pk"]}/projects/',
                self._make_project_request_body(),
                Project,
            )
            print("Project created")
        else:
            print(f"Updating project {self.config.project.name} settings...")
            self.project = do_patch(
                self.client,
                f'/api/projects/{self.project["pk"]}/',
                self._make_project_request_body(),
                Project,
            )
            print("Project settings updated")

        self._save_expected_student_files()
        self._save_instructor_files()
        self._load_sandbox_images()
        pass

    def _make_project_request_body(self):
        return {"name": self.config.project.name} | json.loads(
            self.config.project.settings.model_dump_json(
                exclude_unset=True,
                by_alias=True,
            )
        )

    def _save_expected_student_files(self):
        assert self.project is not None

        print("Checking student files")
        file_list = do_get_list(
            self.client,
            f'/api/projects/{self.project["pk"]}/expected_student_files/',
            ExpectedStudentFile,
        )
        self.student_files = {item["pattern"]: item for item in file_list}

        for student_file_config in self.config.project.student_files:
            pattern = student_file_config["pattern"]
            print("* Checking", pattern, "...")
            if student_file_config["pattern"] in self.student_files:
                response = self.client.patch(
                    f'/api/expected_student_files/{self.student_files[pattern]["pk"]}/',
                    json=student_file_config,
                )
                check_response_status(response)
                print("  Updated", pattern)
            else:
                response = self.client.post(
                    f'/api/projects/{self.project["pk"]}/expected_student_files/',
                    json=student_file_config,
                )
                check_response_status(response)
                print("  Created", pattern)

    def _save_instructor_files(self):
        assert self.project is not None

        print("Checking instructor files...")
        file_list = do_get_list(
            self.client,
            f'/api/projects/{self.project["pk"]}/instructor_files/',
            InstructorFile,
        )
        self.instructor_files = {item["name"]: item for item in file_list}

        for file_config in self.config.project.instructor_files:
            print("* Checking", file_config.name, "...")
            if file_config.name in self.instructor_files:
                with open(self.project_config_dir / file_config.local_path, "rb") as f:
                    response = self.client.put(
                        f'/api/instructor_files/{self.instructor_files[file_config.name]["pk"]}/content/',
                        files={"file_obj": f},
                    )
                check_response_status(response)
                print("  Updated", file_config.name, "from", file_config.local_path)
            else:
                with open(self.project_config_dir / file_config.local_path, "rb") as f:
                    response = self.client.post(
                        f'/api/projects/{self.project["pk"]}/instructor_files/',
                        files={"file_obj": f},
                    )
                check_response_status(response)
                print("  Created", file_config.name, "from", file_config.local_path)

    def _load_sandbox_images(self):
        print("Loading sandbox images...")
        global_sandbox_images = do_get_list(
            self.client,
            f"/api/sandbox_docker_images/",
            SandboxDockerImage,
        )
        course_sandbox_images = do_get_list(
            self.client,
            f'/api/courses/{self.course["pk"]}/sandbox_docker_images/',
            SandboxDockerImage,
        )

        self.sandbox_images = {
            image["display_name"]: image
            for image in itertools.chain(global_sandbox_images, course_sandbox_images)
        }
        print("\n".join(self.sandbox_images))

    def _save_test_suites(self):
        assert self.project is not None

        print("Checking test suites")
        test_suites = do_get_list(
            self.client,
            f'/api/projects/{self.project["pk"]}/ag_test_suites/',
            AGTestSuite,
        )
        test_suites = {item["name"]: item for item in test_suites}

        for suite_data in self.config.project.test_suites:
            print("* Checking test suite", suite_data.name, "...")
            if suite_data.name in test_suites:
                response = self.client.patch(
                    f'/api/ag_test_suites/{test_suites[suite_data.name]["pk"]}/',
                    json=self._make_save_test_suite_request_body(suite_data),
                )
                check_response_status(response)
                print("  Updated", suite_data.name)
            else:
                response = self.client.post(
                    f'/api/projects/{self.project["pk"]}/ag_test_suites/',
                    json=self._make_save_test_suite_request_body(suite_data),
                )
                check_response_status(response)
                test_suites[suite_data.name] = response.json()
                print("  Created", suite_data.name)

    def _make_save_test_suite_request_body(self, suite_data: TestSuiteConfig):
        return suite_data.model_dump(
            exclude={"test_cases"},
            exclude_unset=True,
        ) | {
            "sandbox_docker_image": self.sandbox_images[suite_data.sandbox_docker_image],
            "student_files_needed": [
                self.student_files[pattern] for pattern in suite_data.student_files_needed
            ],
            "instructor_files_needed": [
                self.instructor_files[name] for name in suite_data.instructor_files_needed
            ],
            "normal_fdbk_config": self._get_suite_setup_fdbk_conf(suite_data.normal_fdbk_config),
            "ultimate_submission_fdbk_config": self._get_suite_setup_fdbk_conf(
                suite_data.ultimate_submission_fdbk_config
            ),
            "past_limit_submission_fdbk_config": self._get_suite_setup_fdbk_conf(
                suite_data.past_limit_submission_fdbk_config
            ),
            "staff_viewer_fdbk_config": self._get_suite_setup_fdbk_conf(
                suite_data.staff_viewer_fdbk_config
            ),
        }

    def _get_suite_setup_fdbk_conf(
        self, val: str | AGTestSuiteFeedbackConfig
    ) -> AGTestSuiteFeedbackConfig:
        if isinstance(val, str):
            if val not in self.config.feedback_presets_test_suite_setup:
                print(f'Suite setup feedback preset "{val}" not found')
            return self.config.feedback_presets_test_suite_setup[val]

        return val

    def _get_fdbk_conf(
        self,
        val: str | AGTestCommandFeedbackConfig | None,
    ) -> AGTestCommandFeedbackConfig | None:
        if val is None:
            return None

        if isinstance(val, str):
            if val not in self.config.feedback_presets:
                print(f'Feedback preset "{val}" not found.')
            return self.config.feedback_presets[val]

        return val


#         test_cases = {test["name"]: test for test in test_suites[suite_data.name]["ag_test_cases"]}
#         for test_data in suite_data.test_cases:
#             if test_data.repeat:
#                 repeat_test_case(
#                     test_data.repeat,
#                     client,
#                     suite_data,
#                     test_data,
#                     test_suites=test_suites,
#                     test_cases=test_cases,
#                     instructor_files=instructor_files,
#                 )
#             else:
#                 create_or_update_test(
#                     client,
#                     suite_data,
#                     test_data,
#                     test_suites=test_suites,
#                     test_cases=test_cases,
#                     instructor_files=instructor_files,
#                 )


# def get_instr_file(name: str | None, instr_files: dict[str, dict]):
#     if name is None:
#         return None

#     return instr_files[name]


# def create_or_update_test(
#     client: HTTPClient,
#     suite_data: TestSuiteConfig,
#     test_data: TestCaseConfig,
#     *,
#     test_suites: dict[str, dict],
#     test_cases: dict[str, dict],
#     instructor_files: dict[str, dict],
# ) -> None:
#     _create_or_update_test_shallow(
#         client,
#         suite_data,
#         test_data,
#         test_suites=test_suites,
#         test_cases=test_cases,
#     )

#     commands = {cmd["name"]: cmd for cmd in test_cases[test_data.name]["ag_test_commands"]}
#     for cmd_data in test_data.commands:
#         if cmd_data.repeat:
#             repeat_command(
#                 cmd_data.repeat,
#                 client,
#                 test_data,
#                 cmd_data,
#                 test_cases=test_cases,
#                 commands=commands,
#                 instructor_files=instructor_files,
#             )
#         else:
#             create_or_update_command(
#                 client,
#                 test_data,
#                 cmd_data,
#                 test_cases=test_cases,
#                 commands=commands,
#                 instructor_files=instructor_files,
#             )


# def _create_or_update_test_shallow(
#     client: HTTPClient,
#     suite_data: TestSuiteConfig,
#     test_data: TestCaseConfig,
#     *,
#     test_suites: dict[str, dict],
#     test_cases: dict[str, dict],
# ) -> None:
#     request_body = test_data.model_dump(exclude_unset=True, exclude={"commands", "repeat"})

#     print("  * Checking test case", test_data.name, "...")
#     if test_data.name in test_cases:
#         response = client.patch(
#             f'/api/ag_test_cases/{test_cases[test_data.name]["pk"]}/', json=request_body
#         )
#         check_response_status(response)
#         print("    Updated", test_data.name)
#     else:
#         response = client.post(
#             f'/api/ag_test_suites/{test_suites[suite_data.name]["pk"]}/ag_test_cases/',
#             json=request_body,
#         )
#         check_response_status(response)
#         test_cases[test_data.name] = response.json()
#         print("    Created", test_data.name)


# def create_or_update_command(
#     client: HTTPClient,
#     test_data: TestCaseConfig,
#     cmd_data: CommandConfig,
#     *,
#     test_cases: dict[str, dict],
#     commands: dict[str, dict],
#     instructor_files: dict[str, dict],
# ) -> None:
#     exclude_fields = [
#         "stdin_instructor_file",
#         "expected_stdout_instructor_file",
#         "expected_stderr_instructor_file",
#         "normal_fdbk_config",
#         "first_failed_test_normal_fdbk_config",
#         "ultimate_submission_fdbk_config",
#         "past_limit_submission_fdbk_config",
#         "staff_viewer_fdbk_config",
#         "repeat",
#     ]

#     stitched_data = {
#         "stdin_instructor_file": get_instr_file(cmd_data.stdin_instructor_file, instructor_files),
#         "expected_stdout_instructor_file": get_instr_file(
#             cmd_data.expected_stdout_instructor_file, instructor_files
#         ),
#         "expected_stderr_instructor_file": get_instr_file(
#             cmd_data.expected_stderr_instructor_file, instructor_files
#         ),
#         "normal_fdbk_config": get_fdbk_conf(cmd_data.normal_fdbk_config),
#         "first_failed_test_normal_fdbk_config": get_fdbk_conf(
#             cmd_data.first_failed_test_normal_fdbk_config
#         ),
#         "ultimate_submission_fdbk_config": get_fdbk_conf(cmd_data.ultimate_submission_fdbk_config),
#         "past_limit_submission_fdbk_config": get_fdbk_conf(
#             cmd_data.past_limit_submission_fdbk_config
#         ),
#         "staff_viewer_fdbk_config": get_fdbk_conf(cmd_data.staff_viewer_fdbk_config),
#     }

#     print("    * Checking command", cmd_data.name, "...")

#     request_body = (
#         cmd_data.model_dump(mode="json", exclude_unset=True, exclude=exclude_fields)
#         | stitched_data
#     )

#     if cmd_data.name in commands:
#         response = client.patch(
#             f'/api/ag_test_commands/{commands[cmd_data.name]["pk"]}/',
#             json=request_body,
#         )
#         check_response_status(response)
#         print("      Updated", cmd_data.name)
#     else:
#         response = client.post(
#             f'/api/ag_test_cases/{test_cases[test_data.name]["pk"]}/ag_test_commands/',
#             json=request_body,
#         )
#         check_response_status(response)
#         commands[cmd_data.name] = response.json()
#         print("      Created", cmd_data.name)


# def repeat_test_case(
#     substitutions: list[dict[str, object]],
#     client: HTTPClient,
#     suite_data: TestSuiteConfig,
#     test_data: TestCaseConfig,
#     *,
#     test_suites: dict[str, dict],
#     test_cases: dict[str, dict],
#     instructor_files: dict[str, dict],
# ):
#     print(f"  Repeating test case {test_data.name}")
#     for sub in substitutions:
#         new_test_data = test_data.model_copy(deep=True)
#         new_test_data.name = apply_substitutions(test_data.name, sub)

#         _create_or_update_test_shallow(
#             client,
#             suite_data,
#             new_test_data,
#             test_suites=test_suites,
#             test_cases=test_cases,
#         )

#         commands = {cmd["name"]: cmd for cmd in test_cases[new_test_data.name]["ag_test_commands"]}
#         for cmd_data in test_data.commands:
#             new_cmd_data = cmd_data.model_copy(deep=True)
#             new_cmd_data.name = apply_substitutions(new_cmd_data.name, sub)
#             new_cmd_data.cmd = apply_substitutions(new_cmd_data.cmd, sub)
#             if new_cmd_data.stdin_instructor_file is not None:
#                 new_cmd_data.stdin_instructor_file = apply_substitutions(
#                     new_cmd_data.stdin_instructor_file, sub
#                 )

#             if new_cmd_data.expected_stdout_instructor_file is not None:
#                 new_cmd_data.expected_stdout_instructor_file = apply_substitutions(
#                     new_cmd_data.expected_stdout_instructor_file, sub
#                 )

#             if new_cmd_data.expected_stderr_instructor_file is not None:
#                 new_cmd_data.expected_stderr_instructor_file = apply_substitutions(
#                     new_cmd_data.expected_stderr_instructor_file, sub
#                 )

#             if new_cmd_data.repeat:
#                 repeat_command(
#                     new_cmd_data.repeat,
#                     client,
#                     new_test_data,
#                     new_cmd_data,
#                     test_cases=test_cases,
#                     commands=commands,
#                     instructor_files=instructor_files,
#                 )
#             else:
#                 create_or_update_command(
#                     client,
#                     new_test_data,
#                     new_cmd_data,
#                     test_cases=test_cases,
#                     commands=commands,
#                     instructor_files=instructor_files,
#                 )


# def repeat_command(
#     substitutions: list[dict[str, object]],
#     client: HTTPClient,
#     test_data: TestCaseConfig,
#     cmd_data: CommandConfig,
#     *,
#     test_cases: dict[str, dict],
#     commands: dict[str, dict],
#     instructor_files: dict[str, dict],
# ) -> None:
#     print(f"    Repeating command {cmd_data.name}")
#     for sub in substitutions:
#         new_name = apply_substitutions(cmd_data.name, sub)
#         new_cmd = apply_substitutions(cmd_data.cmd, sub)

#         new_cmd_data = cmd_data.model_copy(deep=True)
#         new_cmd_data.name = new_name
#         new_cmd_data.cmd = new_cmd

#         if new_cmd_data.stdin_instructor_file is not None:
#             new_cmd_data.stdin_instructor_file = apply_substitutions(
#                 new_cmd_data.stdin_instructor_file, sub
#             )

#         if new_cmd_data.expected_stdout_instructor_file is not None:
#             new_cmd_data.expected_stdout_instructor_file = apply_substitutions(
#                 new_cmd_data.expected_stdout_instructor_file, sub
#             )

#         if new_cmd_data.expected_stderr_instructor_file is not None:
#             new_cmd_data.expected_stderr_instructor_file = apply_substitutions(
#                 new_cmd_data.expected_stderr_instructor_file, sub
#             )

#         create_or_update_command(
#             client,
#             test_data,
#             new_cmd_data,
#             test_cases=test_cases,
#             commands=commands,
#             instructor_files=instructor_files,
#         )


# def apply_substitutions(string: str, sub: dict[str, object]) -> str:
#     for placeholder, replacement in sub.items():
#         string = string.replace(placeholder, str(replacement))

#     return string


T = TypeVar("T")


def do_get(client: HTTPClient, url: str, response_type: type[T]) -> T:
    response = client.get(url)
    check_response_status(response)
    return response_to_schema_obj(response, response_type)


def do_post(client: HTTPClient, url: str, request_body: object, response_type: type[T]) -> T:
    response = client.post(url, json=request_body)
    check_response_status(response)
    return response_to_schema_obj(response, response_type)


def do_patch(client: HTTPClient, url: str, request_body: object, response_type: type[T]) -> T:
    response = client.patch(url, json=request_body)
    check_response_status(response)
    return response_to_schema_obj(response, response_type)


def response_to_schema_obj(response: Response, class_: type[T]) -> T:
    return TypeAdapter(class_).validate_python(response.json())


def do_get_list(client: HTTPClient, url: str, element_type: type[T]) -> list[T]:
    response = client.get(url)
    check_response_status(response)
    type_adapter = TypeAdapter(element_type)
    return [type_adapter.validate_python(obj) for obj in response.json()]
