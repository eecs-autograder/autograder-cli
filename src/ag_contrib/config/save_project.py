import copy
import itertools
from collections.abc import Mapping
from pathlib import Path

import yaml

import ag_contrib.config.generated.schema as ag_schema
from ag_contrib.config.models import (
    AGConfig,
    AGConfigError,
    DeadlineWithFixedCutoff,
    DeadlineWithNoCutoff,
    DeadlineWithRelativeCutoff,
    ExactMatchExpectedStudentFile,
    ExpectedStudentFile,
    FnmatchExpectedStudentFile,
    MultiCmdTestCaseConfig,
    SingleCmdTestCaseConfig,
    TestSuiteConfig,
)
from ag_contrib.http_client import HTTPClient, check_response_status
from ag_contrib.utils import get_api_token

from .utils import do_get_list, do_patch, do_post, get_project_from_course


def save_project(config_file: str, *, base_url: str, token_file: str):
    _ProjectSaver(config_file, base_url=base_url, token_file=token_file).save_project()


class _ProjectSaver:
    student_files: dict[str, ag_schema.ExpectedStudentFile] = {}
    instructor_files: dict[str, ag_schema.InstructorFile] = {}
    sandbox_images: dict[str, ag_schema.SandboxDockerImage] = {}

    def __init__(self, config_file: str, *, base_url: str, token_file: str):
        with open(config_file) as f:
            self.config = AGConfig.model_validate(yaml.safe_load(f))

        self.project_config_dir = Path(config_file).parent

        self.base_url = base_url
        self.token_file = token_file

        self.client = HTTPClient(get_api_token(token_file), base_url)

        self.course, project = get_project_from_course(
            self.client,
            self.config.project.course.name,
            self.config.project.course.semester,
            self.config.project.course.year,
            self.config.project.name,
        )
        self.project_pk = project["pk"] if project is not None else None

    def save_project(self):
        if self.project_pk is None:
            print(f"Creating project {self.config.project.name}...")
            project = do_post(
                self.client,
                f'/api/courses/{self.course["pk"]}/projects/',
                {"name": self.config.project.name},
                ag_schema.Project,
            )
            self.project_pk = project["pk"]
            print("Project created")

        print(f"Updating project {self.config.project.name} settings...")
        request_body = (
            self.config.project.settings.model_dump(
                # We do NOT want to exclude unset. Unsetting a field
                # should set it to the CLI default.
                exclude={"send_email_receipts", "deadline", "honor_pledge"},
            )
            | self._make_legacy_project_api_dict()
        )
        do_patch(self.client, f"/api/projects/{self.project_pk}/", request_body, ag_schema.Project)
        print("Project settings updated")

        self._save_expected_student_files()
        self._save_instructor_files()
        self._load_sandbox_images()
        self._save_test_suites()
        pass

    def _make_legacy_project_api_dict(self) -> ag_schema.UpdateProject:
        result: ag_schema.UpdateProject = {
            "submission_limit_reset_timezone": self.config.project.timezone.key
        }
        match (self.config.project.settings.deadline):
            case DeadlineWithRelativeCutoff(deadline=deadline, cutoff=cutoff):
                result["soft_closing_time"] = deadline.isoformat()
                result["closing_time"] = (deadline + cutoff).isoformat()
            case DeadlineWithFixedCutoff(deadline=deadline, cutoff=cutoff):
                result["soft_closing_time"] = deadline.isoformat()
                result["closing_time"] = cutoff.isoformat()
            case DeadlineWithNoCutoff(deadline=deadline):
                result["soft_closing_time"] = deadline.isoformat()
                result["closing_time"] = None
            case None:
                pass

        return result

    def _save_expected_student_files(self):
        assert self.project_pk is not None

        print("Checking student files")
        file_list = do_get_list(
            self.client,
            f"/api/projects/{self.project_pk}/expected_student_files/",
            ag_schema.ExpectedStudentFile,
        )
        self.student_files = {item["pattern"]: item for item in file_list}
        patterns_in_yml: set[str] = set()

        for student_file_config in self.config.project.student_files:
            pattern = str(student_file_config)
            patterns_in_yml.add(pattern)
            print("* Checking", pattern, "...")
            if pattern not in self.student_files:
                do_post(
                    self.client,
                    f"/api/projects/{self.project_pk}/expected_student_files/",
                    self._get_expected_student_file_request_body(student_file_config),
                    ag_schema.ExpectedStudentFile,
                )
                print("  Created", pattern)
            else:
                do_patch(
                    self.client,
                    f'/api/expected_student_files/{self.student_files[pattern]["pk"]}/',
                    self._get_expected_student_file_request_body(student_file_config),
                    ag_schema.ExpectedStudentFile,
                )
                print("  Updated", pattern)

        patterns_not_in_yml = set(self.student_files) - patterns_in_yml
        for pattern in patterns_not_in_yml:
            print(
                f"!! WARNING !! The expected student file {pattern} "
                "is no longer present in the configuration file. "
                "If you meant to rename or delete this file, "
                "please do so through the web interface."
            )

    def _get_expected_student_file_request_body(
        self, obj: ExpectedStudentFile
    ) -> ag_schema.CreateExpectedStudentFile:
        match (obj):
            case ExactMatchExpectedStudentFile():
                return {"pattern": obj}
            case FnmatchExpectedStudentFile():
                return {
                    "pattern": obj.pattern,
                    "min_num_matches": obj.min_num_matches,
                    "max_num_matches": obj.max_num_matches,
                }

    def _save_instructor_files(self):
        assert self.project_pk is not None

        print("Checking instructor files...")
        file_list = do_get_list(
            self.client,
            f"/api/projects/{self.project_pk}/instructor_files/",
            ag_schema.InstructorFile,
        )
        self.instructor_files = {item["name"]: item for item in file_list}

        files_in_yml: set[str] = set()

        for file_config in self.config.project.instructor_files:
            print("* Checking", file_config.name, "...")

            for local_file in sorted(self.project_config_dir.glob(str(file_config.local_path))):
                if local_file.is_dir():
                    continue

                files_in_yml.add(local_file.name)

                if local_file.name in self.instructor_files:
                    with open(local_file, "rb") as f:
                        response = self.client.put(
                            f'/api/instructor_files/{self.instructor_files[local_file.name]["pk"]}/content/',
                            files={"file_obj": f},
                        )
                    check_response_status(response)
                    print("  Updated", local_file.name, "from", local_file)
                else:
                    with open(local_file, "rb") as f:
                        response = self.client.post(
                            f"/api/projects/{self.project_pk}/instructor_files/",
                            files={"file_obj": f},
                        )
                    check_response_status(response)
                    print("  Created", local_file.name, "from", local_file)

                self.instructor_files[local_file.name] = response.json()

        files_not_in_yml = set(self.instructor_files) - files_in_yml
        for file_ in files_not_in_yml:
            print(
                f"!! WARNING !! The instructor file {file_} "
                "is no longer present in the configuration file. "
                "If you meant to rename or delete this file, "
                "please do so through the web interface."
            )

    def _load_sandbox_images(self):
        print("Loading sandbox images...")
        global_sandbox_images = do_get_list(
            self.client,
            f"/api/sandbox_docker_images/",
            ag_schema.SandboxDockerImage,
        )
        course_sandbox_images = do_get_list(
            self.client,
            f'/api/courses/{self.course["pk"]}/sandbox_docker_images/',
            ag_schema.SandboxDockerImage,
        )

        self.sandbox_images = {
            image["display_name"]: image
            for image in itertools.chain(global_sandbox_images, course_sandbox_images)
        }
        print("\n".join(self.sandbox_images))

    def _save_test_suites(self):
        assert self.project_pk is not None

        print("Checking test suites")
        test_suites = do_get_list(
            self.client,
            f"/api/projects/{self.project_pk}/ag_test_suites/",
            ag_schema.AGTestSuite,
        )
        test_suites = {item["name"]: item for item in test_suites}

        for suite_data in self.config.project.test_suites:
            print("* Checking test suite", suite_data.name, "...")
            if suite_data.name not in test_suites:
                response = do_post(
                    self.client,
                    f"/api/projects/{self.project_pk}/ag_test_suites/",
                    self._make_save_test_suite_request_body(suite_data),
                    ag_schema.AGTestSuite,
                )
                test_suites[suite_data.name] = response
                print("  Created", suite_data.name)
            else:
                do_patch(
                    self.client,
                    f'/api/ag_test_suites/{test_suites[suite_data.name]["pk"]}/',
                    self._make_save_test_suite_request_body(suite_data),
                    ag_schema.AGTestSuite,
                )
                print("  Updated", suite_data.name)

            test_cases = {
                test["name"]: test for test in test_suites[suite_data.name]["ag_test_cases"]
            }
            for tests in suite_data.test_cases:
                for test in tests.do_repeat():
                    self._save_test_case(test, test_suites[suite_data.name]["pk"], test_cases)

        suite_order = [
            test_suites[suite.name]["pk"] for suite in self.config.project.test_suites
        ]
        suite_order_response = self.client.put(
            f"/api/projects/{self.project_pk}/ag_test_suites/order/",
            json=suite_order,
        )
        check_response_status(suite_order_response)

    def _make_save_test_suite_request_body(self, suite_config: TestSuiteConfig):
        return suite_config.model_dump(
            exclude={"test_cases"},
            # We do NOT want to exclude unset. Unsetting a field
            # should set it to the CLI default.
        ) | {
            "sandbox_docker_image": self.sandbox_images[suite_config.sandbox_docker_image],
            "student_files_needed": [
                self.student_files[pattern] for pattern in suite_config.student_files_needed
            ],
            "instructor_files_needed": [
                self.instructor_files[name] for name in suite_config.instructor_files_needed
            ],
            "normal_fdbk_config": self._get_suite_setup_fdbk_conf(suite_config.normal_fdbk_config),
            "ultimate_submission_fdbk_config": self._get_suite_setup_fdbk_conf(
                suite_config.ultimate_submission_fdbk_config
            ),
            "past_limit_submission_fdbk_config": self._get_suite_setup_fdbk_conf(
                suite_config.past_limit_submission_fdbk_config
            ),
            "staff_viewer_fdbk_config": self._get_suite_setup_fdbk_conf(
                suite_config.staff_viewer_fdbk_config
            ),
        }

    def _get_suite_setup_fdbk_conf(
        self, val: str | ag_schema.AGTestSuiteFeedbackConfig
    ) -> ag_schema.AGTestSuiteFeedbackConfig:
        if isinstance(val, str):
            if val not in self.config.feedback_presets_test_suite_setup:
                print(f'Suite setup feedback preset "{val}" not found')
            return self.config.feedback_presets_test_suite_setup[val]

        return val

    def _save_test_case(
        self,
        test: SingleCmdTestCaseConfig | MultiCmdTestCaseConfig,
        suite_pk: int,
        existing_tests: Mapping[str, ag_schema.AGTestCase],
    ):
        existing_tests = dict(copy.deepcopy(existing_tests))
        print("  * Checking test case", test.name, "...")
        if test.name not in existing_tests:
            test_data = do_post(
                self.client,
                f"/api/ag_test_suites/{suite_pk}/ag_test_cases/",
                self._make_save_test_case_request_body(test),
                ag_schema.AGTestCase,
            )
            print("    Created", test.name)
        else:
            test_data = do_patch(
                self.client,
                f'/api/ag_test_cases/{existing_tests[test.name]["pk"]}/',
                self._make_save_test_case_request_body(test),
                ag_schema.AGTestCase,
            )
            print("    Updated", test.name)

        existing_cmds = {cmd_data["name"]: cmd_data for cmd_data in test_data["ag_test_commands"]}

        match (test):
            case SingleCmdTestCaseConfig():
                print("    * Checking command for", test.name)
                if test.name not in existing_cmds:
                    do_post(
                        self.client,
                        f'/api/ag_test_cases/{test_data["pk"]}/ag_test_commands/',
                        self._make_save_single_cmd_test_request_body(test),
                        ag_schema.AGTestCommand,
                    )
                    print("      Created")
                else:
                    do_patch(
                        self.client,
                        f'/api/ag_test_commands/{existing_cmds[test.name]["pk"]}/',
                        self._make_save_single_cmd_test_request_body(test),
                        ag_schema.AGTestCommand,
                    )
                    print("      Updated")
            case MultiCmdTestCaseConfig():
                # FIXME
                for _ in test.commands:
                    pass

    def _make_save_test_case_request_body(
        self, test: SingleCmdTestCaseConfig | MultiCmdTestCaseConfig
    ) -> ag_schema.CreateAGTestCase:
        match test:
            case SingleCmdTestCaseConfig():
                return {
                    "name": test.name,
                    "internal_admin_notes": test.internal_admin_notes,
                    "staff_description": test.staff_description,
                    "student_description": test.student_description,
                }
            case MultiCmdTestCaseConfig():
                return {
                    "name": test.name,
                    "internal_admin_notes": test.internal_admin_notes,
                    "staff_description": test.staff_description,
                    "student_description": test.student_description,
                    "normal_fdbk_config": test.feedback.normal_fdbk_config,
                    "ultimate_submission_fdbk_config": (
                        test.feedback.ultimate_submission_fdbk_config
                    ),
                    "past_limit_submission_fdbk_config": (
                        test.feedback.past_limit_submission_fdbk_config
                    ),
                    "staff_viewer_fdbk_config": test.feedback.staff_viewer_fdbk_config,
                }

    def _make_save_single_cmd_test_request_body(
        self,
        test: SingleCmdTestCaseConfig,
    ) -> ag_schema.AGTestCommand:
        body: ag_schema.AGTestCommand = {
            "name": test.name,
            "cmd": test.cmd,
            "internal_admin_notes": test.internal_admin_notes,
            "staff_description": test.staff_description,
            "student_description": test.student_description,
            "student_on_fail_description": test.student_on_fail_description,
            "stdin_source": test.input.source,
            "stdin_text": test.input.text,
            # The schema is incorrect, stdin_instructor_file should be nullable.
            "stdin_instructor_file": self._get_instructor_file(test.input.instructor_file),  # type: ignore
            "expected_return_code": test.return_code.expected,
            "points_for_correct_return_code": int(test.return_code.points),
            "expected_stdout_source": test.stdout.compare_with,
            "expected_stdout_text": test.stdout.text,
            # The schema is incorrect, expected_stdout_instructor_file should be nullable.
            "expected_stdout_instructor_file": self._get_instructor_file(test.stdout.instructor_file),  # type: ignore
            "points_for_correct_stdout": int(test.stdout.points),
            "expected_stderr_source": test.stderr.compare_with,
            "expected_stderr_text": test.stderr.text,
            # The schema is incorrect, expected_stderr_instructor_file should be nullable.
            "expected_stderr_instructor_file": self._get_instructor_file(test.stderr.instructor_file),  # type: ignore
            "points_for_correct_stderr": int(test.stderr.points),
            "ignore_case": test.diff_options.ignore_case,
            "ignore_whitespace": test.diff_options.ignore_whitespace,
            "ignore_whitespace_changes": test.diff_options.ignore_whitespace_changes,
            "ignore_blank_lines": test.diff_options.ignore_blank_lines,
            "normal_fdbk_config": self._get_fdbk_conf(test.feedback.normal_fdbk_config),
            "first_failed_test_normal_fdbk_config": self._get_fdbk_conf(
                test.feedback.first_failed_test_normal_fdbk_config
            ),
            "ultimate_submission_fdbk_config": self._get_fdbk_conf(
                test.feedback.ultimate_submission_fdbk_config
            ),
            "past_limit_submission_fdbk_config": self._get_fdbk_conf(
                test.feedback.past_limit_submission_fdbk_config
            ),
            "staff_viewer_fdbk_config": self._get_fdbk_conf(
                test.feedback.staff_viewer_fdbk_config
            ),
            "time_limit": test.resources.time_limit,
            "use_virtual_memory_limit": test.resources.virtual_memory_limit is not None,
            "block_process_spawn": test.resources.block_process_spawn,
        }

        if test.resources.virtual_memory_limit is not None:
            body["virtual_memory_limit"] = test.resources.virtual_memory_limit

        return body

    def _get_fdbk_conf(
        self,
        val: str | ag_schema.AGTestCommandFeedbackConfig | None,
    ) -> ag_schema.AGTestCommandFeedbackConfig | None:
        if val is None:
            return None

        if isinstance(val, str):
            if val not in self.config.feedback_presets:
                print(f'Feedback preset "{val}" not found.')
            return self.config.feedback_presets[val]

        return val

    def _get_instructor_file(self, filename: str | None) -> ag_schema.InstructorFile | None:
        if filename is None:
            return None

        if filename not in self.instructor_files:
            raise AGConfigError(f'Instructor file "{filename}" not found.')

        return self.instructor_files[filename]


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
