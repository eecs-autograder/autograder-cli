import itertools
from collections.abc import Mapping
from pathlib import Path
from typing import Final, Protocol, overload

import yaml
from requests import HTTPError

import autograder_cli.config.autograder_io_schema.schema as ag_schema
from autograder_cli.http_client import HTTPClient, check_response_status
from autograder_cli.utils import get_api_token

from .models import (
    AGConfig,
    AGConfigError,
    BugsDetectedFeedback,
    DeadlineWithFixedCutoff,
    DeadlineWithNoCutoff,
    DeadlineWithRelativeCutoff,
    ExactMatchExpectedStudentFile,
    ExpectedStudentFile,
    FalsePositivesFeedback,
    FindBugsFeedback,
    FnmatchExpectedStudentFile,
    HandgradingConfig,
    MultiCmdTestCaseConfig,
    MultiCommandConfig,
    MutationCommandFeedbackOptions,
    MutationCommandOutputFeedbackOptions,
    MutationSetupCmdFeedback,
    MutationSuiteConfig,
    MutationSuiteFeedback,
    MutationSuiteFeedbackSettings,
    SingleCmdTestCaseConfig,
    TestDiscoveryFeedback,
    TestSuiteConfig,
)
from .utils import do_get, do_get_list, do_patch, do_post, get_project_from_course


def save_project(config_file: str, *, base_url: str, token_file: str):
    _ProjectSaver(config_file, base_url=base_url, token_file=token_file).save_project()


class _ProjectSaver:
    student_files: dict[str, ag_schema.ExpectedStudentFile] = {}
    instructor_files: dict[str, ag_schema.InstructorFile] = {}
    sandbox_images: dict[str, ag_schema.SandboxDockerImage] = {}

    def __init__(self, config_file: str, *, base_url: str, token_file: str):
        with open(config_file) as f:
            self.config = AGConfig.model_validate(yaml.safe_load(f), context={"read_yaml": True})

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
        self._save_mutation_suites()
        self._save_handgrading_config()

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
                new_pattern = do_post(
                    self.client,
                    f"/api/projects/{self.project_pk}/expected_student_files/",
                    self._get_expected_student_file_request_body(student_file_config),
                    ag_schema.ExpectedStudentFile,
                )
                self.student_files[new_pattern["pattern"]] = new_pattern
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

            glob_matches = sorted(self.project_config_dir.glob(str(file_config.local_path)))
            if not glob_matches:
                raise AGConfigError(f"File not found: {file_config.name}")

            for local_file in glob_matches:
                if local_file.is_dir():
                    print("  Skipping directory", local_file)
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
                    self.instructor_files[local_file.name] = response.json()
                    print("  Created", local_file.name, "from", local_file)

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
        existing_suites = {
            suite["name"]: suite
            for suite in do_get_list(
                self.client,
                f"/api/projects/{self.project_pk}/ag_test_suites/",
                ag_schema.AGTestSuite,
            )
        }

        suite_order: list[int] = []
        for suite_config in self.config.project.test_suites:
            print("* Checking test suite", suite_config.name, "...")
            if suite_config.name not in existing_suites:
                suite_data = do_post(
                    self.client,
                    f"/api/projects/{self.project_pk}/ag_test_suites/",
                    self._make_save_test_suite_request_body(suite_config),
                    ag_schema.AGTestSuite,
                )
                existing_suites[suite_data["name"]] = suite_data
                print("  Created", suite_config.name)
            else:
                suite_data = do_patch(
                    self.client,
                    f'/api/ag_test_suites/{existing_suites[suite_config.name]["pk"]}/',
                    self._make_save_test_suite_request_body(suite_config),
                    ag_schema.AGTestSuite,
                )
                print("  Updated", suite_config.name)

            suite_order.append(suite_data["pk"])

            existing_tests = {
                test["name"]: test for test in existing_suites[suite_config.name]["ag_test_cases"]
            }
            test_order: list[int] = []
            for test_config in suite_config.test_cases:
                for unrolled_test in test_config.do_repeat():
                    test_data = self._save_test_case(
                        unrolled_test,
                        existing_suites[suite_config.name]["pk"],
                        existing_tests,
                    )

                    existing_tests[test_data["name"]] = test_data
                    test_order.append(test_data["pk"])

            test_order_response = self.client.put(
                f"/api/ag_test_suites/{suite_data['pk']}/ag_test_cases/order/",
                json=test_order,
            )
            check_response_status(test_order_response)

        suite_order_response = self.client.put(
            f"/api/projects/{self.project_pk}/ag_test_suites/order/",
            json=suite_order,
        )
        check_response_status(suite_order_response)

    def _make_save_test_suite_request_body(self, suite_config: TestSuiteConfig):
        return suite_config.model_dump(
            exclude={"test_cases", "feedback"},
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
            "normal_fdbk_config": self._get_suite_setup_fdbk_conf(suite_config.feedback.normal),
            "ultimate_submission_fdbk_config": self._get_suite_setup_fdbk_conf(
                suite_config.feedback.final_graded_submission
            ),
            "past_limit_submission_fdbk_config": self._get_suite_setup_fdbk_conf(
                suite_config.feedback.past_limit_submission
            ),
            "staff_viewer_fdbk_config": self._get_suite_setup_fdbk_conf(
                suite_config.feedback.staff_viewer
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
                command_order: list[int] = []
                for cmd in test.commands:
                    # Note: Commands are already unrolled
                    # in MultiCmdTestCaseConfig.do_repeat(),
                    # so we don't need to call do_repeat() on each
                    # command here.
                    print("    * Checking command", cmd.name, "...")
                    if cmd.name not in existing_cmds:
                        cmd_data = do_post(
                            self.client,
                            f'/api/ag_test_cases/{test_data["pk"]}/ag_test_commands/',
                            request_body=self._make_save_multi_cmd_test_request_body(cmd),
                            response_type=ag_schema.AGTestCommand,
                        )
                        print("      Created")
                    else:
                        cmd_data = do_patch(
                            self.client,
                            f'/api/ag_test_commands/{existing_cmds[cmd.name]["pk"]}/',
                            request_body=self._make_save_multi_cmd_test_request_body(cmd),
                            response_type=ag_schema.AGTestCommand,
                        )
                        print("      Updated")

                    command_order.append(cmd_data["pk"])

                print("    Updating command order")
                command_order_response = self.client.put(
                    f"/api/ag_test_cases/{test_data['pk']}/ag_test_commands/order/",
                    json=command_order,
                )
                check_response_status(command_order_response)

        return test_data

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
                    "normal_fdbk_config": test.feedback.normal,
                    "ultimate_submission_fdbk_config": test.feedback.final_graded_submission,
                    "past_limit_submission_fdbk_config": test.feedback.past_limit_submission,
                    "staff_viewer_fdbk_config": test.feedback.staff_viewer,
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
            "normal_fdbk_config": self._get_fdbk_conf(test.feedback.normal),
            "first_failed_test_normal_fdbk_config": self._get_fdbk_conf(
                test.feedback.first_failed_test
            ),
            "ultimate_submission_fdbk_config": self._get_fdbk_conf(
                test.feedback.final_graded_submission
            ),
            "past_limit_submission_fdbk_config": self._get_fdbk_conf(
                test.feedback.past_limit_submission
            ),
            "staff_viewer_fdbk_config": self._get_fdbk_conf(test.feedback.staff_viewer),
            "time_limit": test.resources.time_limit,
            "use_virtual_memory_limit": test.resources.virtual_memory_limit is not None,
            "block_process_spawn": test.resources.block_process_spawn,
        }

        if test.resources.virtual_memory_limit is not None:
            body["virtual_memory_limit"] = test.resources.virtual_memory_limit

        return body

    def _make_save_multi_cmd_test_request_body(
        self,
        cmd: MultiCommandConfig,
    ) -> ag_schema.AGTestCommand:
        body: ag_schema.AGTestCommand = {
            "name": cmd.name,
            "cmd": cmd.cmd,
            "internal_admin_notes": cmd.internal_admin_notes,
            "staff_description": cmd.staff_description,
            "student_description": cmd.student_description,
            "student_on_fail_description": cmd.student_on_fail_description,
            "stdin_source": cmd.input.source,
            "stdin_text": cmd.input.text,
            # The schema is incorrect, stdin_instructor_file should be nullable.
            "stdin_instructor_file": self._get_instructor_file(cmd.input.instructor_file),  # type: ignore
            "expected_return_code": cmd.return_code.expected,
            "points_for_correct_return_code": int(cmd.return_code.points),
            "deduction_for_wrong_return_code": int(cmd.return_code.deduction),
            "expected_stdout_source": cmd.stdout.compare_with,
            "expected_stdout_text": cmd.stdout.text,
            # The schema is incorrect, expected_stdout_instructor_file should be nullable.
            "expected_stdout_instructor_file": self._get_instructor_file(cmd.stdout.instructor_file),  # type: ignore
            "points_for_correct_stdout": int(cmd.stdout.points),
            "deduction_for_wrong_stdout": int(cmd.stdout.deduction),
            "expected_stderr_source": cmd.stderr.compare_with,
            "expected_stderr_text": cmd.stderr.text,
            # The schema is incorrect, expected_stderr_instructor_file should be nullable.
            "expected_stderr_instructor_file": self._get_instructor_file(cmd.stderr.instructor_file),  # type: ignore
            "points_for_correct_stderr": int(cmd.stderr.points),
            "deduction_for_wrong_stderr": int(cmd.stderr.deduction),
            "ignore_case": cmd.diff_options.ignore_case,
            "ignore_whitespace": cmd.diff_options.ignore_whitespace,
            "ignore_whitespace_changes": cmd.diff_options.ignore_whitespace_changes,
            "ignore_blank_lines": cmd.diff_options.ignore_blank_lines,
            "normal_fdbk_config": self._get_fdbk_conf(cmd.feedback.normal),
            "first_failed_test_normal_fdbk_config": self._get_fdbk_conf(
                cmd.feedback.first_failed_test
            ),
            "ultimate_submission_fdbk_config": self._get_fdbk_conf(
                cmd.feedback.final_graded_submission
            ),
            "past_limit_submission_fdbk_config": self._get_fdbk_conf(
                cmd.feedback.past_limit_submission
            ),
            "staff_viewer_fdbk_config": self._get_fdbk_conf(cmd.feedback.staff_viewer),
            "time_limit": cmd.resources.time_limit,
            "use_virtual_memory_limit": cmd.resources.virtual_memory_limit is not None,
            "block_process_spawn": cmd.resources.block_process_spawn,
        }

        if cmd.resources.virtual_memory_limit is not None:
            body["virtual_memory_limit"] = cmd.resources.virtual_memory_limit

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

    def _save_mutation_suites(self):
        assert self.project_pk is not None

        print("Checking mutation suites")
        mutation_suites = do_get_list(
            self.client,
            f"/api/projects/{self.project_pk}/mutation_test_suites/",
            ag_schema.MutationTestSuite,
        )
        mutation_suites = {item["name"]: item for item in mutation_suites}

        for suite_config in self.config.project.mutation_suites:
            print("* Checking mutation suite", suite_config.name, "...")
            if suite_config.name not in mutation_suites:
                response = do_post(
                    self.client,
                    f"/api/projects/{self.project_pk}/mutation_test_suites/",
                    self._make_save_mutation_suite_request_body(suite_config),
                    ag_schema.MutationTestSuite,
                )
                mutation_suites[response["name"]] = response
            else:
                response = do_patch(
                    self.client,
                    f'/api/mutation_test_suites/{mutation_suites[suite_config.name]["pk"]}/',
                    self._make_save_mutation_suite_request_body(suite_config),
                    ag_schema.MutationTestSuite,
                )

            self._save_mutant_hint_config(suite_config, response["pk"])

        print("Setting mutation suite order")
        suite_order = [
            mutation_suites[suite.name]["pk"] for suite in self.config.project.mutation_suites
        ]
        suite_order_response = self.client.put(
            f"/api/projects/{self.project_pk}/mutation_test_suites/order/",
            json=suite_order,
        )
        check_response_status(suite_order_response)

    def _make_save_mutation_suite_request_body(self, suite_config: MutationSuiteConfig):
        setup_cmd_data = {"cmd": "true"}
        if suite_config.setup is not None:
            setup_cmd_data = {
                "cmd": suite_config.setup.cmd,
                "name": suite_config.setup.label,
                "time_limit": suite_config.setup.resources.time_limit,
                **self._make_vmem_limit_dict(suite_config.setup.resources.virtual_memory_limit),
                "block_process_spawn": suite_config.setup.resources.block_process_spawn,
            }

        return {
            "name": suite_config.name,
            "sandbox_docker_image": self.sandbox_images[suite_config.sandbox_docker_image],
            "instructor_files_needed": [
                self.instructor_files[name] for name in suite_config.instructor_files_needed
            ],
            "read_only_instructor_files": suite_config.read_only_instructor_files,
            "student_files_needed": [
                self.student_files[pattern] for pattern in suite_config.student_files_needed
            ],
            "buggy_impl_names": list(suite_config.bug_names),
            "use_setup_command": suite_config.setup is not None,
            "setup_command": setup_cmd_data,
            "get_student_test_names_command": {
                "cmd": suite_config.test_discovery.cmd,
                "time_limit": suite_config.test_discovery.resources.time_limit,
                "time_limit": suite_config.test_discovery.resources.time_limit,
                **self._make_vmem_limit_dict(
                    suite_config.test_discovery.resources.virtual_memory_limit
                ),
                "block_process_spawn": suite_config.test_discovery.resources.block_process_spawn,
            },
            "test_name_discovery_whitespace_handling": suite_config.test_discovery.delimiter,
            "max_num_student_tests": suite_config.test_discovery.max_num_student_tests,
            "student_test_validity_check_command": {
                "cmd": suite_config.false_positives_check.cmd,
                "time_limit": suite_config.false_positives_check.resources.time_limit,
                **self._make_vmem_limit_dict(
                    suite_config.false_positives_check.resources.virtual_memory_limit
                ),
                "block_process_spawn": (
                    suite_config.false_positives_check.resources.block_process_spawn
                ),
            },
            "grade_buggy_impl_command": {
                "cmd": suite_config.find_bugs.cmd,
                "time_limit": suite_config.find_bugs.resources.time_limit,
                **self._make_vmem_limit_dict(
                    suite_config.find_bugs.resources.virtual_memory_limit
                ),
                "block_process_spawn": suite_config.find_bugs.resources.block_process_spawn,
            },
            "points_per_exposed_bug": str(suite_config.points_per_bug),
            "max_points": suite_config.max_points,
            "deferred": suite_config.deferred,
            "allow_network_access": suite_config.allow_network_access,
            "normal_fdbk_config": self._make_mutation_feedback_dict(
                suite_config,
                # As far as I can tell, there isn't currently a good way
                # to represent this type. We would need either conditional types
                # or "typeof" expressions.
                lambda fdbk: fdbk.normal,  # type: ignore
            ),
            "ultimate_submission_fdbk_config": self._make_mutation_feedback_dict(
                suite_config,
                lambda fdbk: fdbk.final_graded_submission,  # type: ignore
            ),
            "past_limit_submission_fdbk_config": self._make_mutation_feedback_dict(
                suite_config,
                lambda fdbk: fdbk.past_limit_submission,  # type: ignore
            ),
            "staff_viewer_fdbk_config": self._make_mutation_feedback_dict(
                suite_config,
                lambda fdbk: fdbk.staff_viewer,  # type: ignore
            ),
        }

    def _make_vmem_limit_dict(self, vmem_limit: int | None):
        return {
            "use_virtual_memory_limit": vmem_limit is not None,
            "virtual_memory_limit": vmem_limit if vmem_limit is not None else 500000000,
        }

    # Ideally, the type of this function would be:
    # - Input: A type var bounded by the union of the 5 input types below.
    # - Return: The type of the "normal" attribute on the input type.
    class _GetFdbkFnType(Protocol):
        @overload
        def __call__(
            self, fdbk: MutationSetupCmdFeedback | TestDiscoveryFeedback
        ) -> MutationCommandFeedbackOptions: ...

        @overload
        def __call__(
            self, fdbk: FalsePositivesFeedback | FindBugsFeedback
        ) -> MutationCommandOutputFeedbackOptions: ...

        @overload
        def __call__(self, fdbk: MutationSuiteFeedback) -> MutationSuiteFeedbackSettings: ...

    def _make_mutation_feedback_dict(
        self,
        suite_config: MutationSuiteConfig,
        get_fdbk_fn: _GetFdbkFnType,
    ) -> dict[str, object]:
        setup_fdbk_dict = {}
        if suite_config.setup is not None:
            setup_fdbk_dict = {
                "show_setup_return_code": get_fdbk_fn(
                    suite_config.setup.feedback
                ).show_return_code,
                "show_setup_stdout": get_fdbk_fn(suite_config.setup.feedback).show_stdout,
                "show_setup_stderr": get_fdbk_fn(suite_config.setup.feedback).show_stderr,
            }
        return {
            "visible": get_fdbk_fn(suite_config.feedback).visible,
            **setup_fdbk_dict,
            "show_get_test_names_return_code": get_fdbk_fn(
                suite_config.test_discovery.feedback
            ).show_return_code,
            "show_get_test_names_stdout": get_fdbk_fn(
                suite_config.test_discovery.feedback
            ).show_stdout,
            "show_get_test_names_stderr": get_fdbk_fn(
                suite_config.test_discovery.feedback
            ).show_stderr,
            "show_validity_check_stdout": get_fdbk_fn(
                suite_config.false_positives_check.feedback
            ).show_stdout,
            "show_validity_check_stderr": get_fdbk_fn(
                suite_config.false_positives_check.feedback
            ).show_stderr,
            "show_grade_buggy_impls_stdout": get_fdbk_fn(
                suite_config.find_bugs.feedback
            ).show_stdout,
            "show_grade_buggy_impls_stderr": get_fdbk_fn(
                suite_config.find_bugs.feedback
            ).show_stderr,
            "show_invalid_test_names": get_fdbk_fn(suite_config.feedback).show_invalid_test_names,
            "show_points": get_fdbk_fn(suite_config.feedback).show_points,
            "bugs_exposed_fdbk_level": self._bugs_exposed_fdbk_config_to_api[
                get_fdbk_fn(suite_config.feedback).bugs_detected
            ],
        }

    _bugs_exposed_fdbk_config_to_api: Final[
        dict[BugsDetectedFeedback, ag_schema.BugsExposedFeedbackLevel]
    ] = {
        "hide": "no_feedback",
        "num_bugs_detected": "num_bugs_exposed",
        "detected_bug_names": "exposed_bug_names",
        "all_bug_names": "all_bug_names",
    }

    def _save_mutant_hint_config(self, suite_config: MutationSuiteConfig, suite_pk: int):
        print("  Checking mutant hint config...")

        if isinstance(suite_config.bug_names, dict):
            try:
                hint_config = do_get(
                    self.client,
                    f"/api/mutation_test_suites/{suite_pk}/hint_config/",
                    ag_schema.MutationTestSuiteHintConfig,
                )
                print("  Hint config loaded")
            except HTTPError as e:
                if e.response.status_code != 404:
                    raise

                hint_config = do_post(
                    self.client,
                    f"/api/mutation_test_suites/{suite_pk}/hint_config/",
                    {},
                    ag_schema.MutationTestSuiteHintConfig,
                )
                print("  Hint config created")

            print("  Updating hint config")
            do_patch(
                self.client,
                f'/api/mutation_test_suite_hint_configs/{hint_config["pk"]}/',
                {
                    "hints_by_mutant_name": suite_config.bug_names,
                    "num_hints_per_day": suite_config.hint_options.hint_limit_per_day,
                    "hint_limit_reset_time": (
                        suite_config.hint_options.daily_limit_reset_time.isoformat()
                    ),
                    "hint_limit_reset_timezone": self.config.project.timezone.key,
                    "num_hints_per_submission": (
                        suite_config.hint_options.hint_limit_per_submission
                    ),
                    "obfuscate_mutant_names": suite_config.hint_options.obfuscate_bug_names,
                    "obfuscated_mutant_name_prefix": (
                        suite_config.hint_options.obfuscated_bug_names_prefix
                    ),
                },
                ag_schema.MutationTestSuiteHintConfig,
            )
            print("  Hint config updated")

    def _save_handgrading_config(self):
        assert self.project_pk is not None

        print("Checking handgrading config...")
        handgrading_config = self.config.project.handgrading
        if handgrading_config is None:
            print("No handgrading config")
            return

        handgrading_data = None
        try:
            handgrading_data = do_get(
                self.client,
                f"/api/projects/{self.project_pk}/handgrading_rubric/",
                ag_schema.HandgradingRubric,
            )
        except HTTPError as e:
            if e.response.status_code != 404:
                raise

        if not handgrading_data:
            handgrading_data = do_post(
                self.client,
                f"/api/projects/{self.project_pk}/handgrading_rubric/",
                ag_schema.CreateHandgradingRubric(
                    points_style=handgrading_config.points_style,
                    max_points=handgrading_config.max_points,
                    show_only_applied_rubric_to_students=handgrading_config.show_only_applied_rubric_to_students,
                    handgraders_can_leave_comments=handgrading_config.handgraders_can_leave_comments,
                    handgraders_can_adjust_points=handgrading_config.handgraders_can_adjust_points,
                ),
                ag_schema.HandgradingRubric,
            )
            print("Created handgrading")
        else:
            handgrading_data = do_patch(
                self.client,
                f"/api/handgrading_rubrics/{handgrading_data['pk']}/",
                ag_schema.UpdateHandgradingRubric(
                    points_style=handgrading_config.points_style,
                    max_points=handgrading_config.max_points,
                    show_only_applied_rubric_to_students=handgrading_config.show_only_applied_rubric_to_students,
                    handgraders_can_leave_comments=handgrading_config.handgraders_can_leave_comments,
                    handgraders_can_adjust_points=handgrading_config.handgraders_can_adjust_points,
                ),
                ag_schema.HandgradingRubric,
            )
            print("Updated handgrading")

        self._save_criteria(handgrading_config, handgrading_data)
        self._save_annotations(handgrading_config, handgrading_data)

    def _save_criteria(
        self, handgrading_config: HandgradingConfig, handgrading_data: ag_schema.HandgradingRubric
    ):
        handgrading_pk = handgrading_data["pk"]

        existing_criteria = {
            criterion["short_description"]: criterion for criterion in handgrading_data["criteria"]
        }

        criteria_order: list[int] = []
        for criterion_config in handgrading_config.criteria:
            print('* Checking criterion "', criterion_config.short_description.strip(), '"...')
            if criterion_config.short_description not in existing_criteria:
                criterion_data = do_post(
                    self.client,
                    f"/api/handgrading_rubrics/{handgrading_pk}/criteria/",
                    ag_schema.CreateCriterion(
                        short_description=criterion_config.short_description,
                        long_description=criterion_config.long_description,
                        points=criterion_config.points,
                    ),
                    ag_schema.Criterion,
                )
            else:
                criterion_data = do_patch(
                    self.client,
                    f"/api/criteria/{existing_criteria[criterion_config.short_description]['pk']}/",
                    ag_schema.UpdateCriterion(
                        short_description=criterion_config.short_description,
                        long_description=criterion_config.long_description,
                        points=criterion_config.points,
                    ),
                    ag_schema.Criterion,
                )

            criteria_order.append(criterion_data["pk"])
            print("  Updating criteria order")
            criteria_order_response = self.client.put(
                f"/api/handgrading_rubrics/{handgrading_pk}/criteria/order/",
                json=criteria_order,
            )
            check_response_status(criteria_order_response)

    def _save_annotations(
        self, handgrading_config: HandgradingConfig, handgrading_data: ag_schema.HandgradingRubric
    ):
        handgrading_pk = handgrading_data["pk"]

        existing_annotations = {
            annotation["short_description"]: annotation
            for annotation in handgrading_data["annotations"]
        }

        annotations_order: list[int] = []
        for annotation_config in handgrading_config.annotations:
            print('* Checking annotation "', annotation_config.short_description.strip(), '"...')
            if annotation_config.short_description not in existing_annotations:
                annotation_data = do_post(
                    self.client,
                    f"/api/handgrading_rubrics/{handgrading_pk}/annotations/",
                    ag_schema.CreateAnnotation(
                        short_description=annotation_config.short_description,
                        long_description=annotation_config.long_description,
                        deduction=annotation_config.deduction,
                        max_deduction=annotation_config.max_deduction,
                    ),
                    ag_schema.Annotation,
                )
            else:
                annotation_data = do_patch(
                    self.client,
                    f"/api/annotations/{existing_annotations[annotation_config.short_description]['pk']}/",
                    ag_schema.UpdateAnnotation(
                        short_description=annotation_config.short_description,
                        long_description=annotation_config.long_description,
                        deduction=annotation_config.deduction,
                        max_deduction=annotation_config.max_deduction,
                    ),
                    ag_schema.Annotation,
                )

            annotations_order.append(annotation_data["pk"])
            print("  Updating annotations order")
            annotations_order_response = self.client.put(
                f"/api/handgrading_rubrics/{handgrading_pk}/annotations/order/",
                json=annotations_order,
            )
            check_response_status(annotations_order_response)
