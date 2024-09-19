from __future__ import annotations

import datetime
import itertools
from pathlib import Path
import re
from typing import Annotated, Literal, TypeAlias
from zoneinfo import ZoneInfo
import zoneinfo
from dateutil.parser import parse as parse_datetime
from pydantic import (
    BaseModel,
    Discriminator,
    Field,
    PlainSerializer,
    PlainValidator,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    Tag,
    WrapSerializer,
    computed_field,
    field_serializer,
    field_validator,
)

from ag_contrib.config.generated import schema as ag_schema


class AGConfigError(Exception):
    pass


class AGConfig(BaseModel):
    project: ProjectConfig
    feedback_presets: dict[str, ag_schema.AGTestCommandFeedbackConfig] = Field(
        default_factory=lambda: BUILTIN_CMD_FDBK_PRESETS
    )
    feedback_presets_test_suite_setup: dict[str, ag_schema.AGTestSuiteFeedbackConfig] = Field(
        default_factory=lambda: BUILTIN_TEST_SUITE_FDBK_PRESETS
    )
    docker_images: dict[str, DockerImage] = {}


def validate_timezone(timezone: object) -> ZoneInfo:
    if isinstance(timezone, ZoneInfo):
        return timezone

    if not isinstance(timezone, str):
        raise ValueError("Expected a string representing a timezone.")

    # TODO/Future: Once the API has an endpoint of supported timezones,
    # load from there instead.
    if timezone not in zoneinfo.available_timezones():
        raise ValueError("Unrecognized timezone.")

    return ZoneInfo(timezone)


def serialize_timezone(timezone: ZoneInfo) -> str:
    return timezone.key


class ProjectConfig(BaseModel):
    name: str
    course: CourseSelection
    settings: ProjectSettings
    student_files: list[ExpectedStudentFile] = []
    instructor_files: list[InstructorFileConfig] = []
    test_suites: list[TestSuiteConfig] = []


class CourseSelection(BaseModel):
    name: str
    semester: Literal["Fall", "Winter", "Spring", "Summer"] | None
    year: int | None


def _seven_days_from_now():
    now = datetime.datetime.now().replace(minute=0, second=0, microsecond=0)
    return now + datetime.timedelta(days=7)


def validate_datetime(value: object) -> datetime.datetime | None:
    if value is None:
        return None

    parsed = parse_datetime(value) if isinstance(value, str) else value
    if not isinstance(parsed, datetime.datetime):
        raise ValueError("Unrecognized datetime format.")
    return parsed


def serialize_datetime(
    value: datetime.datetime,
    handler: SerializerFunctionWrapHandler,
    info: SerializationInfo,
):
    if info.by_alias:
        return value.strftime("%b %d, %Y %I:%M%p")

    return handler(value)


def validate_time(value: object) -> datetime.time | None:
    parsed = parse_datetime(value) if isinstance(value, str) else value
    if not isinstance(parsed, datetime.datetime):
        raise ValueError("Unrecognized time format.")

    return parsed.time()


class ProjectSettings(BaseModel):
    timezone: Annotated[
        ZoneInfo,
        PlainValidator(validate_timezone),
        PlainSerializer(serialize_timezone),
    ]

    guests_can_submit: Annotated[bool, Field(alias="anyone_with_link_can_submit")] = False
    deadline: Annotated[
        datetime.datetime | None,
        PlainValidator(validate_datetime),
        WrapSerializer(serialize_datetime, when_used="unless-none"),
    ] = _seven_days_from_now()
    grace_period: datetime.timedelta = datetime.timedelta(hours=0)

    @field_serializer("grace_period")
    def serialize_grace_period(self, value: datetime.timedelta) -> str:
        days = value.days
        hours = value.seconds // 3600
        minutes = value.seconds % 60

        result = ''
        if days:
            result += f'{days}d'

        if hours:
            result += f'{hours}h'

        if minutes:
            result += f'{minutes}'

        return result

    @field_validator("grace_period", mode="plain")
    @classmethod
    def validate_grace_period(cls, value: object) -> datetime.timedelta:
        error_msg = 'Expected a time string in the format "XhXm"'
        if not isinstance(value, str):
            raise ValueError(error_msg)

        match = re.match(
            r"""\s*(((?P<days>\d+)\s*d)?)
            \s*(((?P<hours>\d+)\s*h)?)
            \s*(((?P<minutes>\d+)\s*m)?)""",
            value,
            re.VERBOSE,
        )
        if match is None or not (matches := match.groupdict()):
            raise ValueError(error_msg)

        return datetime.timedelta(
            days=int(matches.get("days", 0)),
            hours=int(matches.get("hours", 0)),
            minutes=int(matches.get("minutes", 0)),
        )

    allow_late_days: bool = False

    # Future: we can probably use a serialization context to serialize
    # datetimes as ISO vs human readable
    @computed_field
    @property
    def soft_closing_time(self) -> str | None:
        if self.deadline is None:
            return None

        return self.deadline.replace(tzinfo=self.timezone).isoformat()

    @computed_field
    @property
    def closing_time(self) -> str | None:
        if self.deadline is None:
            return None

        return (self.deadline + self.grace_period).replace(tzinfo=self.timezone).isoformat()

    ultimate_submission_policy: Annotated[
        Literal["most_recent", "best"], Field(alias="final_graded_submission_policy")
    ] = "most_recent"

    min_group_size: int = 1
    max_group_size: int = 1

    submission_limit_per_day: int | None = None
    allow_submissions_past_limit: bool = False
    groups_combine_daily_submissions: bool = False
    submission_limit_reset_time: Annotated[
        datetime.time,
        PlainValidator(validate_time),
        WrapSerializer(lambda value, _: value.strftime("%I:%M%p")),
    ] = datetime.time(hour=0)
    num_bonus_submissions: int = 0

    @computed_field
    @property
    def submission_limit_reset_timezone(self) -> str:
        return self.timezone.key

    send_email_receipts: bool = False

    @computed_field
    @property
    def send_email_on_submission_received(self) -> bool:
        return self.send_email_receipts

    @computed_field
    @property
    def send_email_on_non_deferred_tests_finished(self) -> bool:
        return self.send_email_receipts

    use_honor_pledge: bool = False
    honor_pledge_text: str = ""

    total_submission_limit: int | None = None


class DockerImage(BaseModel):
    build_dir: Path
    include: list[Path] = []
    exclude: list[Path] = []


class ExactMatchExpectedStudentFile(BaseModel):
    filename: str

    def __str__(self) -> str:
        return self.filename


class FnmatchExpectedStudentFile(BaseModel):
    pattern: str
    min_num_matches: int
    max_num_matches: int

    def __str__(self) -> str:
        return self.pattern


def _get_expected_student_file_discriminator(
    value: object,
) -> Literal['exact_match', 'fnmatch'] | None:
    if isinstance(value, dict):
        if 'filename' in value:
            return 'exact_match'

        if 'pattern' in value:
            return 'fnmatch'

        return None

    if hasattr(value, 'filename'):
        return 'exact_match'

    if hasattr(value, 'pattern'):
        return 'fnmatch'

    return None


ExpectedStudentFile: TypeAlias = Annotated[
    Annotated[ExactMatchExpectedStudentFile, Tag('exact_match')]
    | Annotated[FnmatchExpectedStudentFile, Tag('fnmatch')],
    Discriminator(_get_expected_student_file_discriminator),
]


class InstructorFileConfig(BaseModel):
    local_path: Path

    @property
    def name(self) -> str:
        return self.local_path.name


class TestSuiteConfig(BaseModel):
    name: str
    instructor_files_needed: list[str] = []
    read_only_instructor_files: bool = True
    student_files_needed: list[str] = []

    allow_network_access: bool = False
    deferred: bool = False
    sandbox_docker_image: str = "Default"

    setup_suite_cmd: str = (
        'echo "Configure your setup command here. Set to empty string to not use a setup command"'
    )
    setup_suite_cmd_name: str = "Setup"
    reject_submission_if_setup_fails: bool = False

    normal_fdbk_config: str | ag_schema.AGTestSuiteFeedbackConfig = "public"
    ultimate_submission_fdbk_config: str | ag_schema.AGTestSuiteFeedbackConfig = "public"
    past_limit_submission_fdbk_config: str | ag_schema.AGTestSuiteFeedbackConfig = "public"
    staff_viewer_fdbk_config: str | ag_schema.AGTestSuiteFeedbackConfig = "public"

    test_cases: list[SingleCmdTestCaseConfig | MultiCmdTestCaseConfig] = []


class MultiCmdTestCaseConfig(BaseModel):
    name: str
    type: Literal["multi_cmd"] = "multi_cmd"
    repeat: list[dict[str, object]] = []
    internal_admin_notes: str = ''
    staff_description: str = ''
    student_description: str = ''
    feedback: TestCaseAdvancedFdbkConfig = Field(
        default_factory=lambda: TestCaseAdvancedFdbkConfig()
    )
    commands: list[MultiCommandConfig] = []

    def do_repeat(self) -> list[MultiCmdTestCaseConfig]:
        new_tests: list[MultiCmdTestCaseConfig] = []
        if not self.repeat:
            new_tests.append(self)
        else:
            for substitution in self.repeat:
                new_test = self.model_copy(deep=True)
                new_test.name = apply_substitutions(new_test.name, substitution)

                for command in new_test.commands:
                    command.name = apply_substitutions(command.name, substitution)
                    command.cmd = apply_substitutions(command.cmd, substitution)

                    command.return_code.points_for_correct_return_code = apply_points_substitution(
                        command.return_code.points_for_correct_return_code, substitution
                    )
                    command.output_diff.points_for_correct_stdout = apply_points_substitution(
                        command.output_diff.points_for_correct_stdout, substitution
                    )
                    command.output_diff.points_for_correct_stderr = apply_points_substitution(
                        command.output_diff.points_for_correct_stderr, substitution
                    )

                new_test.commands = list(
                    itertools.chain(*[cmd.do_repeat() for cmd in new_test.commands])
                )

                new_tests.append(new_test)

        return new_tests


class TestCaseAdvancedFdbkConfig(BaseModel):
    normal_fdbk_config: ag_schema.AGTestCaseFeedbackConfig = {
        "visible": True,
        "show_individual_commands": True,
        "show_student_description": True,
    }
    ultimate_submission_fdbk_config: ag_schema.AGTestCaseFeedbackConfig = {
        "visible": True,
        "show_individual_commands": True,
        "show_student_description": True,
    }
    past_limit_submission_fdbk_config: ag_schema.AGTestCaseFeedbackConfig = {
        "visible": True,
        "show_individual_commands": True,
        "show_student_description": True,
    }
    staff_viewer_fdbk_config: ag_schema.AGTestCaseFeedbackConfig = {
        "visible": True,
        "show_individual_commands": True,
        "show_student_description": True,
    }


class MultiCommandConfig(BaseModel):
    name: str
    cmd: str

    input: StdinSettings = Field(default_factory=lambda: StdinSettings())
    return_code: MultiCmdReturnCodeCheckSettings = Field(
        default_factory=lambda: MultiCmdReturnCodeCheckSettings()
    )
    output_diff: MultiCmdDiffSettings = Field(default_factory=lambda: MultiCmdDiffSettings())
    feedback: CommandFeedbackSettings = Field(default_factory=lambda: CommandFeedbackSettings())
    resources: ResourceLimits = Field(default_factory=lambda: ResourceLimits())

    repeat: list[dict[str, object]] = []

    def do_repeat(self) -> list[MultiCommandConfig]:
        raise NotImplementedError


class SingleCmdTestCaseConfig(BaseModel):
    name: str
    type: Literal["default", "single_cmd"] = "default"

    internal_admin_notes: str = ''
    staff_description: str = ''
    student_description: str = ''

    cmd: str

    input: StdinSettings = Field(default_factory=lambda: StdinSettings())
    return_code: SingleCmdReturnCodeCheckSettings = Field(
        default_factory=lambda: SingleCmdReturnCodeCheckSettings()
    )
    output_diff: SingleCmdDiffSettings = Field(default_factory=lambda: SingleCmdDiffSettings())
    feedback: CommandFeedbackSettings = Field(default_factory=lambda: CommandFeedbackSettings())
    resources: ResourceLimits = Field(default_factory=lambda: ResourceLimits())

    repeat: list[dict[str, object]] = []

    def do_repeat(self) -> list[SingleCmdTestCaseConfig]:
        if not self.repeat:
            return [self]

        new_tests: list[SingleCmdTestCaseConfig] = []
        for substitution in self.repeat:
            new_test = self.model_copy(deep=True)
            new_test.name = apply_substitutions(new_test.name, substitution)
            new_test.cmd = apply_substitutions(new_test.name, substitution)

            new_test.return_code.points_for_correct_return_code = apply_points_substitution(
                new_test.return_code.points_for_correct_return_code, substitution
            )
            new_test.output_diff.points_for_correct_stdout = apply_points_substitution(
                new_test.output_diff.points_for_correct_stdout, substitution
            )
            new_test.output_diff.points_for_correct_stderr = apply_points_substitution(
                new_test.output_diff.points_for_correct_stderr, substitution
            )

            new_tests.append(new_test)

        return new_tests


def apply_substitutions(string: str, sub: dict[str, object]) -> str:
    for placeholder, replacement in sub.items():
        string = string.replace(placeholder, str(replacement))

    return string


def apply_points_substitution(original_points_val: str | int, sub: dict[str, object]) -> int:
    if isinstance(original_points_val, int):
        return original_points_val

    if original_points_val not in sub:
        raise PointsSubstitutionError(f'Repeater key "{original_points_val}" not found.')

    sub_value = sub[original_points_val]
    if not isinstance(sub_value, int):
        raise PointsSubstitutionError(
            "Point value substitutions must be an integer, "
            f'but got type "{type(original_points_val)}"'
        )

    return sub_value


class PointsSubstitutionError(AGConfigError):
    pass


class StdinSettings(BaseModel):
    stdin_source: ag_schema.StdinSource = "none"
    stdin_text: str = ""
    stdin_instructor_file: str | None = None


class MultiCmdReturnCodeCheckSettings(BaseModel):
    expected_return_code: ag_schema.ExpectedReturnCode = "none"
    points_for_correct_return_code: int = 0
    deduction_for_wrong_return_code: int = 0


class SingleCmdReturnCodeCheckSettings(BaseModel):
    expected_return_code: ag_schema.ExpectedReturnCode = "none"
    points_for_correct_return_code: int | str = 0


class MultiCmdDiffSettings(BaseModel):
    expected_stdout_source: ag_schema.ExpectedOutputSource = "none"
    expected_stdout_text: str = ""
    expected_stdout_instructor_file: str | None = None
    points_for_correct_stdout: int = 0
    deduction_for_wrong_stdout: int = 0

    expected_stderr_source: ag_schema.ExpectedOutputSource = "none"
    expected_stderr_text: str = ""
    expected_stderr_instructor_file: str | None = None
    points_for_correct_stderr: int = 0
    deduction_for_wrong_stderr: int = 0

    ignore_case: bool = False
    ignore_whitespace: bool = False
    ignore_whitespace_changes: bool = False
    ignore_blank_lines: bool = False


class SingleCmdDiffSettings(BaseModel):
    expected_stdout_source: ag_schema.ExpectedOutputSource = "none"
    expected_stdout_text: str = ""
    expected_stdout_instructor_file: str | None = None
    points_for_correct_stdout: int | str = 0

    expected_stderr_source: ag_schema.ExpectedOutputSource = "none"
    expected_stderr_text: str = ""
    expected_stderr_instructor_file: str | None = None
    points_for_correct_stderr: int | str = 0

    ignore_case: bool = False
    ignore_whitespace: bool = False
    ignore_whitespace_changes: bool = False
    ignore_blank_lines: bool = False


class CommandFeedbackSettings(BaseModel):
    normal_fdbk_config: ag_schema.AGTestCommandFeedbackConfig | str = "pass/fail"
    first_failed_test_normal_fdbk_config: ag_schema.AGTestCommandFeedbackConfig | str | None = None
    ultimate_submission_fdbk_config: ag_schema.AGTestCommandFeedbackConfig | str = "pass/fail"
    past_limit_submission_fdbk_config: ag_schema.AGTestCommandFeedbackConfig | str = "private"
    staff_viewer_fdbk_config: ag_schema.AGTestCommandFeedbackConfig | str = "public"


class ResourceLimits(BaseModel):
    time_limit: int = 10
    virtual_memory_limit: int | None = None
    block_process_spawn: bool = False


BUILTIN_TEST_SUITE_FDBK_PRESETS = {
    "public": ag_schema.AGTestSuiteFeedbackConfig(
        visible=True,
        show_individual_tests=True,
        show_student_description=True,
        show_setup_return_code=True,
        show_setup_timed_out=True,
        show_setup_stdout=True,
        show_setup_stderr=True,
    ),
    "pass/fail": ag_schema.AGTestSuiteFeedbackConfig(
        visible=True,
        show_individual_tests=True,
        show_student_description=True,
        show_setup_return_code=True,
        show_setup_timed_out=True,
        show_setup_stdout=False,
        show_setup_stderr=False,
    ),
    "private": ag_schema.AGTestSuiteFeedbackConfig(
        visible=True,
        show_individual_tests=True,
        show_student_description=False,
        show_setup_return_code=False,
        show_setup_timed_out=False,
        show_setup_stdout=False,
        show_setup_stderr=False,
    ),
}


BUILTIN_CMD_FDBK_PRESETS = {
    "pass/fail": ag_schema.AGTestCommandFeedbackConfig(
        visible=True,
        show_student_description=True,
        return_code_fdbk_level="correct_or_incorrect",
        stdout_fdbk_level="correct_or_incorrect",
        stderr_fdbk_level="correct_or_incorrect",
        show_points=True,
        show_actual_return_code=False,
        show_actual_stdout=False,
        show_actual_stderr=False,
        show_whether_timed_out=False,
    ),
    "pass/fail+timeout": ag_schema.AGTestCommandFeedbackConfig(
        visible=True,
        show_student_description=True,
        return_code_fdbk_level="correct_or_incorrect",
        stdout_fdbk_level="correct_or_incorrect",
        stderr_fdbk_level="correct_or_incorrect",
        show_points=True,
        show_actual_return_code=False,
        show_actual_stdout=False,
        show_actual_stderr=False,
        show_whether_timed_out=True,
    ),
    "pass/fail+exit_status": ag_schema.AGTestCommandFeedbackConfig(
        visible=True,
        show_student_description=True,
        return_code_fdbk_level="correct_or_incorrect",
        stdout_fdbk_level="correct_or_incorrect",
        stderr_fdbk_level="correct_or_incorrect",
        show_points=True,
        show_actual_return_code=True,
        show_actual_stdout=False,
        show_actual_stderr=False,
        show_whether_timed_out=True,
    ),
    "pass/fail+output": ag_schema.AGTestCommandFeedbackConfig(
        visible=True,
        show_student_description=True,
        return_code_fdbk_level="correct_or_incorrect",
        stdout_fdbk_level="correct_or_incorrect",
        stderr_fdbk_level="correct_or_incorrect",
        show_points=True,
        show_actual_return_code=False,
        show_actual_stdout=True,
        show_actual_stderr=True,
        show_whether_timed_out=False,
    ),
    "pass/fail+diff": ag_schema.AGTestCommandFeedbackConfig(
        visible=True,
        show_student_description=True,
        return_code_fdbk_level="correct_or_incorrect",
        stdout_fdbk_level="expected_and_actual",
        stderr_fdbk_level="expected_and_actual",
        show_points=True,
        show_actual_return_code=False,
        show_actual_stdout=False,
        show_actual_stderr=False,
        show_whether_timed_out=False,
    ),
    "private": ag_schema.AGTestCommandFeedbackConfig(
        visible=True,
        show_student_description=False,
        return_code_fdbk_level="no_feedback",
        stdout_fdbk_level="no_feedback",
        stderr_fdbk_level="no_feedback",
        show_points=False,
        show_actual_return_code=False,
        show_actual_stdout=False,
        show_actual_stderr=False,
        show_whether_timed_out=False,
    ),
    "public": ag_schema.AGTestCommandFeedbackConfig(
        visible=True,
        show_student_description=True,
        return_code_fdbk_level="expected_and_actual",
        stdout_fdbk_level="expected_and_actual",
        stderr_fdbk_level="expected_and_actual",
        show_points=True,
        show_actual_return_code=True,
        show_actual_stdout=True,
        show_actual_stderr=True,
        show_whether_timed_out=True,
    ),
}
