import ag_contrib.config.generated.schema as ag_schema
from ag_contrib.http_client import HTTPClient
from ag_contrib.utils import get_api_token

from .models import ProjectSettings
from .utils import do_get, get_project_from_course


def load_project(
    course_name: str,
    course_term: ag_schema.Semester,
    course_year: int,
    project_name: str,
    save_to: str,
    *,
    base_url: str,
    token_file: str,
):
    client = HTTPClient(get_api_token(token_file), base_url)

    course_data, project_data = get_project_from_course(
        client,
        course_name,
        course_term,
        course_year,
        project_name,
        raise_if_not_found=True,
    )

    hard_deadline = project_data.get("closing_time", None)
    soft_deadline = project_data['soft_closing_time']
    if hard_deadline is None and soft_deadline is None:
        deadline = None
        grace_period = 0
    if hard_deadline is not None and soft_deadline is None:
        deadline = hard_deadline
        grace_period = 0
        if soft_deadline is None:
            soft_deadline = hard_deadline


        grace_period


    settings = ProjectSettings(
        timezone=project_data["submission_limit_reset_timezone"],
        guests_can_submit=project_data["guests_can_submit"],
        deadline=hard_deadline,
        grace_period=project_data["grace_period"],
        allow_late_days=project_data["allow_late_days"],
        ultimate_submission_policy=project_data["ultimate_submission_policy"],
        min_group_size=project_data["min_group_size"],
        max_group_size=project_data["max_group_size"],
        submission_limit_per_day=project_data["submission_limit_per_day"],
        allow_submissions_past_limit=project_data["allow_submissions_past_limit"],
        groups_combine_daily_submissions=project_data["groups_combine_daily_submissions"],
        submission_limit_reset_time=project_data["submission_limit_reset_time"],
        num_bonus_submissions=project_data["num_bonus_submissions"],
        submission_limit_reset_timezone=project_data["submission_limit_reset_timezone"],
        send_email_receipts=project_data["send_email_receipts"],
        send_email_on_submission_received=project_data["send_email_on_submission_received"],
        send_email_on_non_deferred_tests_finished=project_data[
            "send_email_on_non_deferred_tests_finished"
        ],
        use_honor_pledge=project_data["use_honor_pledge"],
        honor_pledge_text=project_data["honor_pledge_text"],
        total_submission_limit=project_data["total_submission_limit"],
    )

    pass
