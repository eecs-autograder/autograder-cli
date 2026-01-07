import warnings
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal
from zoneinfo import ZoneInfo

from pydantic import TypeAdapter
from requests import HTTPError

import autograder_cli.config.autograder_io_schema.schema as ag_schema
from autograder_cli.http_client import HTTPClient
from autograder_cli.utils import get_api_token

from .models import (
    AGConfig,
    BugsDetectedFeedback,
    CourseSelection,
    DeadlineWithFixedCutoff,
    DeadlineWithNoCutoff,
    DeadlineWithRelativeCutoff,
    ExpectedStudentFile,
    FalsePositivesCmd,
    FalsePositivesFeedback,
    FindBugsCmd,
    FindBugsFeedback,
    HandgradingAnnotationConfig,
    HandgradingConfig,
    HandgradingCriterionConfig,
    InstructorFileConfig,
    MutantHintOptions,
    MutationCommandFeedbackOptions,
    MutationCommandOutputFeedbackOptions,
    MutationSetupCmd,
    MutationSetupCmdFeedback,
    MutationSuiteConfig,
    MutationSuiteFeedback,
    MutationSuiteFeedbackSettings,
    ProjectConfig,
    ProjectSettings,
    ResourceLimits,
    TestDiscoveryCmd,
    TestDiscoveryFeedback,
    TestSuiteConfig,
    validate_datetime,
    validate_timezone,
)
from .time_processing import validate_time
from .utils import do_get, do_get_list, get_project_from_course, write_yaml


def load_project(
    course_name: str,
    course_term: ag_schema.Semester,
    course_year: int,
    project_name: str,
    deadline_cutoff_preference: Literal["relative", "fixed"],
    output_file: str,
    *,
    base_url: str,
    token_file: str,
):
    client = HTTPClient(get_api_token(token_file), base_url)

    output_dir = Path(output_file).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    print("Created project directory ", output_dir)

    print("Loading project settings...")
    _, project_data = get_project_from_course(
        client,
        course_name,
        course_term,
        course_year,
        project_name,
        raise_if_not_found=True,
    )

    if project_data["ultimate_submission_policy"] == "best_basic_score":
        warnings.warn(
            'The "best_basic_score" final graded submission policy is deprecated. '
            'Use "best" instead.'
        )
        project_data["ultimate_submission_policy"] = "best"

    timezone = validate_timezone(project_data["submission_limit_reset_timezone"])

    settings = ProjectSettings(
        _timezone=timezone,
        guests_can_submit=project_data["guests_can_submit"],
        deadline=_process_deadline(project_data, deadline_cutoff_preference, timezone),
        allow_late_days=project_data["allow_late_days"],
        ultimate_submission_policy=project_data["ultimate_submission_policy"],
        min_group_size=project_data["min_group_size"],
        max_group_size=project_data["max_group_size"],
        submission_limit_per_day=project_data["submission_limit_per_day"],
        allow_submissions_past_limit=project_data["allow_submissions_past_limit"],
        groups_combine_daily_submissions=project_data["groups_combine_daily_submissions"],
        submission_limit_reset_time=validate_time(project_data["submission_limit_reset_time"]),
        num_bonus_submissions=project_data["num_bonus_submissions"],
        send_email_receipts=_process_email_receipts(project_data),
        honor_pledge=(
            project_data["honor_pledge_text"] if project_data["use_honor_pledge"] else None
        ),
        total_submission_limit=project_data["total_submission_limit"],
    )

    print("Loading expected student files...")
    student_file_data = _load_expected_student_files(client, project_data["pk"])

    print("Loading instructor files...")
    instructor_file_data = _load_instructor_files(client, project_data["pk"], output_dir)

    print("Loading test suites...")
    test_suites = _load_test_suites(client, project_data["pk"])

    print("Loading mutation suites...")
    mutation_suites = _load_mutation_suites(client, project_data["pk"])

    print("Loading handgrading...")
    handgrading = _load_handgrading(client, project_data["pk"])

    write_yaml(
        AGConfig(
            project=ProjectConfig(
                name=project_name,
                timezone=timezone,
                course=CourseSelection(
                    name=course_name,
                    semester=course_term,
                    year=course_year,
                ),
                settings=settings,
                student_files=student_file_data,
                instructor_files=instructor_file_data,
                test_suites=test_suites,
                mutation_suites=mutation_suites,
                handgrading=handgrading,
            )
        ),
        output_file,
        exclude_defaults=True,
    )
    print("Project data written to", output_file)


def _process_deadline(
    project_data: ag_schema.Project,
    deadline_cutoff_preference: Literal["relative", "fixed"],
    timezone: ZoneInfo,
) -> DeadlineWithRelativeCutoff | DeadlineWithFixedCutoff | DeadlineWithNoCutoff | None:
    soft_deadline = validate_datetime(project_data["soft_closing_time"])
    if soft_deadline is not None:
        soft_deadline = soft_deadline.astimezone(timezone)

    hard_deadline = validate_datetime(project_data.get("closing_time", None))
    if hard_deadline is not None:
        hard_deadline = hard_deadline.astimezone(timezone)

    if soft_deadline is not None and hard_deadline is not None:
        if deadline_cutoff_preference == "relative":
            return DeadlineWithRelativeCutoff(
                cutoff_type="relative",
                deadline=soft_deadline,
                cutoff=hard_deadline - soft_deadline,
            )
        else:
            return DeadlineWithFixedCutoff(
                cutoff_type="fixed",
                deadline=soft_deadline,
                cutoff=hard_deadline,
            )

    if soft_deadline is not None and hard_deadline is None:
        return DeadlineWithNoCutoff(cutoff_type="none", deadline=soft_deadline)

    if soft_deadline is None and hard_deadline is not None:
        # Default cutoff for relative is 0
        return DeadlineWithRelativeCutoff(cutoff_type="relative", deadline=hard_deadline)

    if soft_deadline is None and hard_deadline is None:
        return None


def _process_email_receipts(project_data: ag_schema.Project):
    on_received = project_data["send_email_on_submission_received"]
    on_finish = project_data["send_email_on_non_deferred_tests_finished"]
    if on_received and on_finish:
        return True

    if on_received:
        return "on_received"

    if on_finish:
        return "on_finish"

    return False


def _load_expected_student_files(client: HTTPClient, project_pk: int) -> list[ExpectedStudentFile]:
    student_file_data = do_get_list(
        client,
        f"/api/projects/{project_pk}/expected_student_files/",
        ag_schema.ExpectedStudentFile,
    )

    return TypeAdapter(list[ExpectedStudentFile]).validate_python(
        [
            (
                item["pattern"]
                if item["min_num_matches"] == 1 and item["max_num_matches"] == 1
                else item
            )
            for item in student_file_data
        ]
    )


def _load_instructor_files(
    client: HTTPClient, project_pk: int, output_dir: Path
) -> list[InstructorFileConfig]:
    instructor_file_data = do_get_list(
        client,
        f"/api/projects/{project_pk}/instructor_files/",
        ag_schema.InstructorFile,
    )

    instructor_files: list[InstructorFileConfig] = []
    for item in instructor_file_data:
        _download_file(
            client, f"/api/instructor_files/{item['pk']}/content/", output_dir / item["name"]
        )
        instructor_files.append(InstructorFileConfig(local_path=Path(item["name"])))

    return sorted(instructor_files, key=lambda file: file.local_path.name)


def _download_file(client: HTTPClient, url: str, save_to: Path):
    with client.get(url, stream=True) as r:
        r.raise_for_status()
        with open(save_to, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                # If you have chunk encoded response uncomment if
                # and set chunk_size parameter to None.
                # if chunk:
                f.write(chunk)

    return save_to


def _load_test_suites(client: HTTPClient, project_pk: int) -> list[TestSuiteConfig]:
    suite_data = do_get_list(
        client,
        f"/api/projects/{project_pk}/ag_test_suites/",
        ag_schema.AGTestSuite,
    )

    return [TestSuiteConfig.from_api(item) for item in suite_data]


def _load_mutation_suites(client: HTTPClient, project_pk: int) -> list[MutationSuiteConfig]:
    suite_response = do_get_list(
        client,
        f"/api/projects/{project_pk}/mutation_test_suites/",
        ag_schema.MutationTestSuite,
    )

    suites: list[MutationSuiteConfig] = []
    for suite_dict in suite_response:
        bug_names = list(suite_dict["buggy_impl_names"])
        hint_options = MutantHintOptions()
        try:
            hint_dict = do_get(
                client,
                f'/api/mutation_test_suites/{suite_dict["pk"]}/hint_config/',
                ag_schema.MutationTestSuiteHintConfig,
            )
            bug_names = {bug: hint_dict["hints_by_mutant_name"].get(bug, []) for bug in bug_names}
            hint_options = MutantHintOptions(
                hint_limit_per_day=hint_dict["num_hints_per_day"],
                daily_limit_reset_time=validate_time(hint_dict["hint_limit_reset_time"]),
                hint_limit_per_submission=hint_dict["num_hints_per_submission"],
                obfuscate_bug_names=hint_dict["obfuscate_mutant_names"],
                obfuscated_bug_names_prefix=hint_dict["obfuscated_mutant_name_prefix"],
            )
        except HTTPError as e:
            if e.response.status_code != 404:
                raise

        suite = MutationSuiteConfig(
            name=suite_dict["name"],
            sandbox_docker_image=suite_dict["sandbox_docker_image"]["display_name"],
            instructor_files_needed=[
                file["name"] for file in suite_dict["instructor_files_needed"]
            ],
            read_only_instructor_files=suite_dict["read_only_instructor_files"],
            student_files_needed=[file["pattern"] for file in suite_dict["student_files_needed"]],
            allow_network_access=suite_dict["allow_network_access"],
            deferred=suite_dict["deferred"],
            bug_names=bug_names if bug_names else [],
            points_per_bug=Decimal(suite_dict["points_per_exposed_bug"]),
            max_points=suite_dict["max_points"],
            setup=(
                MutationSetupCmd(
                    cmd=suite_dict["setup_command"]["cmd"],
                    label=suite_dict["setup_command"]["name"],
                    feedback=MutationSetupCmdFeedback(
                        normal=MutationCommandFeedbackOptions(
                            show_return_code=suite_dict["normal_fdbk_config"][
                                "show_setup_return_code"
                            ],
                            show_stdout=suite_dict["normal_fdbk_config"]["show_setup_stdout"],
                            show_stderr=suite_dict["normal_fdbk_config"]["show_setup_stderr"],
                        ),
                        final_graded_submission=MutationCommandFeedbackOptions(
                            show_return_code=suite_dict["ultimate_submission_fdbk_config"][
                                "show_setup_return_code"
                            ],
                            show_stdout=suite_dict["ultimate_submission_fdbk_config"][
                                "show_setup_stdout"
                            ],
                            show_stderr=suite_dict["ultimate_submission_fdbk_config"][
                                "show_setup_stderr"
                            ],
                        ),
                        past_limit_submission=MutationCommandFeedbackOptions(
                            show_return_code=suite_dict["past_limit_submission_fdbk_config"][
                                "show_setup_return_code"
                            ],
                            show_stdout=suite_dict["past_limit_submission_fdbk_config"][
                                "show_setup_stdout"
                            ],
                            show_stderr=suite_dict["past_limit_submission_fdbk_config"][
                                "show_setup_stderr"
                            ],
                        ),
                        staff_viewer=MutationCommandFeedbackOptions(
                            show_return_code=suite_dict["staff_viewer_fdbk_config"][
                                "show_setup_return_code"
                            ],
                            show_stdout=suite_dict["staff_viewer_fdbk_config"][
                                "show_setup_stdout"
                            ],
                            show_stderr=suite_dict["staff_viewer_fdbk_config"][
                                "show_setup_stderr"
                            ],
                        ),
                    ),
                    resources=ResourceLimits(
                        time_limit=suite_dict["setup_command"]["time_limit"],
                        virtual_memory_limit=(
                            suite_dict["setup_command"]["virtual_memory_limit"]
                            if suite_dict["setup_command"]["use_virtual_memory_limit"]
                            else None
                        ),
                        block_process_spawn=suite_dict["setup_command"]["block_process_spawn"],
                    ),
                )
                if suite_dict["use_setup_command"]
                else None
            ),
            test_discovery=TestDiscoveryCmd(
                cmd=suite_dict["get_student_test_names_command"]["cmd"],
                max_num_student_tests=suite_dict["max_num_student_tests"],
                delimiter=suite_dict["test_name_discovery_whitespace_handling"],
                feedback=TestDiscoveryFeedback(
                    normal=MutationCommandFeedbackOptions(
                        show_return_code=suite_dict["normal_fdbk_config"][
                            "show_get_test_names_return_code"
                        ],
                        show_stdout=suite_dict["normal_fdbk_config"]["show_get_test_names_stdout"],
                        show_stderr=suite_dict["normal_fdbk_config"]["show_get_test_names_stderr"],
                    ),
                    final_graded_submission=MutationCommandFeedbackOptions(
                        show_return_code=suite_dict["ultimate_submission_fdbk_config"][
                            "show_get_test_names_return_code"
                        ],
                        show_stdout=suite_dict["ultimate_submission_fdbk_config"][
                            "show_get_test_names_stdout"
                        ],
                        show_stderr=suite_dict["ultimate_submission_fdbk_config"][
                            "show_get_test_names_stderr"
                        ],
                    ),
                    past_limit_submission=MutationCommandFeedbackOptions(
                        show_return_code=suite_dict["past_limit_submission_fdbk_config"][
                            "show_get_test_names_return_code"
                        ],
                        show_stdout=suite_dict["past_limit_submission_fdbk_config"][
                            "show_get_test_names_stdout"
                        ],
                        show_stderr=suite_dict["past_limit_submission_fdbk_config"][
                            "show_get_test_names_stderr"
                        ],
                    ),
                    staff_viewer=MutationCommandFeedbackOptions(
                        show_return_code=suite_dict["staff_viewer_fdbk_config"][
                            "show_get_test_names_return_code"
                        ],
                        show_stdout=suite_dict["staff_viewer_fdbk_config"][
                            "show_get_test_names_stdout"
                        ],
                        show_stderr=suite_dict["staff_viewer_fdbk_config"][
                            "show_get_test_names_stderr"
                        ],
                    ),
                ),
                resources=ResourceLimits(
                    time_limit=suite_dict["get_student_test_names_command"]["time_limit"],
                    virtual_memory_limit=(
                        suite_dict["get_student_test_names_command"]["virtual_memory_limit"]
                        if suite_dict["get_student_test_names_command"]["use_virtual_memory_limit"]
                        else None
                    ),
                    block_process_spawn=suite_dict["get_student_test_names_command"][
                        "block_process_spawn"
                    ],
                ),
            ),
            false_positives_check=FalsePositivesCmd(
                cmd=suite_dict["student_test_validity_check_command"]["cmd"],
                feedback=FalsePositivesFeedback(
                    normal=MutationCommandOutputFeedbackOptions(
                        show_stdout=suite_dict["normal_fdbk_config"]["show_validity_check_stdout"],
                        show_stderr=suite_dict["normal_fdbk_config"]["show_validity_check_stderr"],
                    ),
                    final_graded_submission=MutationCommandOutputFeedbackOptions(
                        show_stdout=suite_dict["ultimate_submission_fdbk_config"][
                            "show_validity_check_stdout"
                        ],
                        show_stderr=suite_dict["ultimate_submission_fdbk_config"][
                            "show_validity_check_stderr"
                        ],
                    ),
                    past_limit_submission=MutationCommandOutputFeedbackOptions(
                        show_stdout=suite_dict["past_limit_submission_fdbk_config"][
                            "show_validity_check_stdout"
                        ],
                        show_stderr=suite_dict["past_limit_submission_fdbk_config"][
                            "show_validity_check_stderr"
                        ],
                    ),
                    staff_viewer=MutationCommandOutputFeedbackOptions(
                        show_stdout=suite_dict["staff_viewer_fdbk_config"][
                            "show_validity_check_stdout"
                        ],
                        show_stderr=suite_dict["staff_viewer_fdbk_config"][
                            "show_validity_check_stderr"
                        ],
                    ),
                ),
                resources=ResourceLimits(
                    time_limit=suite_dict["student_test_validity_check_command"]["time_limit"],
                    virtual_memory_limit=(
                        suite_dict["student_test_validity_check_command"]["virtual_memory_limit"]
                        if suite_dict["student_test_validity_check_command"][
                            "use_virtual_memory_limit"
                        ]
                        else None
                    ),
                    block_process_spawn=suite_dict["student_test_validity_check_command"][
                        "block_process_spawn"
                    ],
                ),
            ),
            find_bugs=FindBugsCmd(
                cmd=suite_dict["grade_buggy_impl_command"]["cmd"],
                feedback=FindBugsFeedback(
                    normal=MutationCommandOutputFeedbackOptions(
                        show_stdout=suite_dict["normal_fdbk_config"][
                            "show_grade_buggy_impls_stdout"
                        ],
                        show_stderr=suite_dict["normal_fdbk_config"][
                            "show_grade_buggy_impls_stderr"
                        ],
                    ),
                    final_graded_submission=MutationCommandOutputFeedbackOptions(
                        show_stdout=suite_dict["ultimate_submission_fdbk_config"][
                            "show_grade_buggy_impls_stdout"
                        ],
                        show_stderr=suite_dict["ultimate_submission_fdbk_config"][
                            "show_grade_buggy_impls_stderr"
                        ],
                    ),
                    past_limit_submission=MutationCommandOutputFeedbackOptions(
                        show_stdout=suite_dict["past_limit_submission_fdbk_config"][
                            "show_grade_buggy_impls_stdout"
                        ],
                        show_stderr=suite_dict["past_limit_submission_fdbk_config"][
                            "show_grade_buggy_impls_stderr"
                        ],
                    ),
                    staff_viewer=MutationCommandOutputFeedbackOptions(
                        show_stdout=suite_dict["staff_viewer_fdbk_config"][
                            "show_grade_buggy_impls_stdout"
                        ],
                        show_stderr=suite_dict["staff_viewer_fdbk_config"][
                            "show_grade_buggy_impls_stderr"
                        ],
                    ),
                ),
                resources=ResourceLimits(
                    time_limit=suite_dict["grade_buggy_impl_command"]["time_limit"],
                    virtual_memory_limit=(
                        suite_dict["grade_buggy_impl_command"]["virtual_memory_limit"]
                        if suite_dict["grade_buggy_impl_command"]["use_virtual_memory_limit"]
                        else None
                    ),
                    block_process_spawn=suite_dict["grade_buggy_impl_command"][
                        "block_process_spawn"
                    ],
                ),
            ),
            feedback=MutationSuiteFeedback(
                normal=MutationSuiteFeedbackSettings(
                    show_invalid_test_names=suite_dict["normal_fdbk_config"][
                        "show_invalid_test_names"
                    ],
                    show_points=suite_dict["normal_fdbk_config"]["show_points"],
                    bugs_detected=_bugs_exposed_fdbk_api_to_config[
                        suite_dict["normal_fdbk_config"]["bugs_exposed_fdbk_level"]
                    ],
                ),
                final_graded_submission=MutationSuiteFeedbackSettings(
                    show_invalid_test_names=suite_dict["ultimate_submission_fdbk_config"][
                        "show_invalid_test_names"
                    ],
                    show_points=suite_dict["ultimate_submission_fdbk_config"]["show_points"],
                    bugs_detected=_bugs_exposed_fdbk_api_to_config[
                        suite_dict["ultimate_submission_fdbk_config"]["bugs_exposed_fdbk_level"]
                    ],
                ),
                past_limit_submission=MutationSuiteFeedbackSettings(
                    show_invalid_test_names=suite_dict["past_limit_submission_fdbk_config"][
                        "show_invalid_test_names"
                    ],
                    show_points=suite_dict["past_limit_submission_fdbk_config"]["show_points"],
                    bugs_detected=_bugs_exposed_fdbk_api_to_config[
                        suite_dict["past_limit_submission_fdbk_config"]["bugs_exposed_fdbk_level"]
                    ],
                ),
                staff_viewer=MutationSuiteFeedbackSettings(
                    show_invalid_test_names=suite_dict["staff_viewer_fdbk_config"][
                        "show_invalid_test_names"
                    ],
                    show_points=suite_dict["staff_viewer_fdbk_config"]["show_points"],
                    bugs_detected=_bugs_exposed_fdbk_api_to_config[
                        suite_dict["staff_viewer_fdbk_config"]["bugs_exposed_fdbk_level"]
                    ],
                ),
            ),
            hint_options=hint_options,
        )
        suites.append(suite)

    return suites


_bugs_exposed_fdbk_api_to_config: Final[
    dict[ag_schema.BugsExposedFeedbackLevel, BugsDetectedFeedback]
] = {
    "no_feedback": "hide",
    "num_bugs_exposed": "num_bugs_detected",
    "exposed_bug_names": "detected_bug_names",
    "all_bug_names": "all_bug_names",
}


def _load_handgrading(client: HTTPClient, project_pk: int) -> HandgradingConfig | None:
    try:
        rubric_data = do_get(
            client,
            f"/api/projects/{project_pk}/handgrading_rubric/",
            ag_schema.HandgradingRubric,
        )
    except HTTPError as e:
        if e.response.status_code != 404:
            raise
        return None

    max_points = int(rubric_data["max_points"]) if rubric_data["max_points"] is not None else None
    if max_points != rubric_data["max_points"]:
        print(
            "WARNING: Loaded HandgradingRubric max_points value was a float. "
            "Trucating to an integer."
        )

    return HandgradingConfig(
        points_style=rubric_data["points_style"],
        max_points=max_points,
        show_only_applied_rubric_to_students=rubric_data["show_only_applied_rubric_to_students"],
        handgraders_can_leave_comments=rubric_data["handgraders_can_leave_comments"],
        handgraders_can_adjust_points=rubric_data["handgraders_can_adjust_points"],
        criteria=[
            HandgradingCriterionConfig.model_validate(criterion_data)
            for criterion_data in rubric_data["criteria"]
        ],
        annotations=[
            HandgradingAnnotationConfig.model_validate(annotation_data)
            for annotation_data in rubric_data["annotations"]
        ],
    )
