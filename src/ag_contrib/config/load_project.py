import warnings
from typing import Literal

import ag_contrib.config.generated.schema as ag_schema
from ag_contrib.http_client import HTTPClient
from ag_contrib.utils import get_api_token

from .models import (
    AGConfig,
    CourseSelection,
    DeadlineWithFixedCutoff,
    DeadlineWithNoCutoff,
    DeadlineWithRelativeCutoff,
    ProjectConfig,
    ProjectSettings,
    validate_datetime,
    validate_timezone,
)
from .utils import do_get, get_project_from_course, write_yaml


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
        deadline=_process_deadline(project_data, deadline_cutoff_preference),
        allow_late_days=project_data["allow_late_days"],
        ultimate_submission_policy=project_data["ultimate_submission_policy"],
        min_group_size=project_data["min_group_size"],
        max_group_size=project_data["max_group_size"],
        submission_limit_per_day=project_data["submission_limit_per_day"],
        allow_submissions_past_limit=project_data["allow_submissions_past_limit"],
        groups_combine_daily_submissions=project_data["groups_combine_daily_submissions"],
        num_bonus_submissions=project_data["num_bonus_submissions"],
        send_email_receipts=_process_email_receipts(project_data),
        honor_pledge=(
            project_data["honor_pledge_text"] if project_data["use_honor_pledge"] else None
        ),
        total_submission_limit=project_data["total_submission_limit"],
    )

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
            )
        ),
        output_file,
        exclude_defaults=True,
    )
    print("Project data written to", output_file)


def _process_deadline(
    project_data: ag_schema.Project,
    deadline_cutoff_preference: Literal["relative", "fixed"],
) -> DeadlineWithRelativeCutoff | DeadlineWithFixedCutoff | DeadlineWithNoCutoff | None:
    soft_deadline = project_data["soft_closing_time"]
    hard_deadline = project_data.get("closing_time", None)

    if soft_deadline is not None and hard_deadline is not None:
        if deadline_cutoff_preference == "relative":
            parsed_soft = validate_datetime(soft_deadline)
            parsed_hard = validate_datetime(hard_deadline)
            return DeadlineWithRelativeCutoff(
                cutoff_type="relative",
                deadline=parsed_soft,
                cutoff=parsed_hard - parsed_soft,
            )
        else:
            return DeadlineWithFixedCutoff(
                cutoff_type="fixed",
                deadline=validate_datetime(soft_deadline),
                cutoff=validate_datetime(hard_deadline),
            )

    if soft_deadline is not None and hard_deadline is None:
        return DeadlineWithNoCutoff(cutoff_type="none", deadline=validate_datetime(soft_deadline))

    if soft_deadline is None and hard_deadline is not None:
        # Default cutoff for relative is 0
        return DeadlineWithRelativeCutoff(
            cutoff_type="relative", deadline=validate_datetime(hard_deadline)
        )

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
