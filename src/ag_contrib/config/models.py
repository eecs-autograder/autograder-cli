from __future__ import annotations

import datetime
import itertools
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Final, Literal, TypeAlias, cast
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    Discriminator,
    Field,
    PlainSerializer,
    PlainValidator,
    Tag,
    ValidationInfo,
    WrapSerializer,
    computed_field,
    field_validator,
    model_validator,
)
from tzlocal import get_localzone

from ag_contrib.config.generated import schema as ag_schema

from .time_processing import (
    serialize_datetime,
    serialize_duration,
    serialize_timezone,
    validate_datetime,
    validate_duration,
    validate_time,
    validate_timezone,
)


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


class ProjectConfig(BaseModel):
    name: str
    timezone: Annotated[
        ZoneInfo,
        PlainValidator(validate_timezone),
        PlainSerializer(serialize_timezone),
    ]
    course: CourseSelection
    settings: ProjectSettings
    student_files: list[ExpectedStudentFile] = []
    instructor_files: list[InstructorFileConfig] = []
    test_suites: list[TestSuiteConfig] = []

    @field_validator('settings', mode='before')
    @classmethod
    def allow_empty_settings(cls, value: object, info: ValidationInfo):
        if value is None:
            print(ProjectSettings(_timezone=info.data['timezone']))
            return ProjectSettings(_timezone=info.data['timezone'])

        return value


class CourseSelection(BaseModel):
    name: str
    semester: Literal["Fall", "Winter", "Spring", "Summer"] | None
    year: int | None


class DeadlineWithRelativeCutoff(BaseModel):
    cutoff_type: Literal["relative"]
    deadline: Annotated[
        datetime.datetime,
        PlainValidator(validate_datetime),
        PlainSerializer(serialize_datetime),
    ]
    cutoff: Annotated[
        datetime.timedelta,
        PlainValidator(validate_duration),
        PlainSerializer(serialize_duration),
    ] = datetime.timedelta(hours=0)


class DeadlineWithFixedCutoff(BaseModel):
    cutoff_type: Literal["fixed"]

    deadline: Annotated[
        datetime.datetime,
        PlainValidator(validate_datetime),
        PlainSerializer(serialize_datetime, when_used="unless-none"),
    ]

    cutoff: Annotated[
        datetime.datetime,
        PlainValidator(validate_datetime),
        PlainSerializer(serialize_datetime, when_used="unless-none"),
    ]

    @model_validator(mode="after")
    def validate_cutoff(self):
        if self.cutoff < self.deadline:
            raise ValueError("A fixed cutoff must be >= the deadline.")

        return self


class DeadlineWithNoCutoff(BaseModel):
    cutoff_type: Literal["none"]

    deadline: Annotated[
        datetime.datetime,
        PlainValidator(validate_datetime),
        PlainSerializer(serialize_datetime),
    ]


class ProjectSettings(BaseModel):
    _timezone: ZoneInfo
    guests_can_submit: Annotated[bool, Field(alias="anyone_with_link_can_submit")] = False
    deadline: (
        Annotated[
            DeadlineWithRelativeCutoff | DeadlineWithFixedCutoff | DeadlineWithNoCutoff,
            Field(discriminator="cutoff_type"),
        ]
        | None
    ) = None

    allow_late_days: bool = False

    ultimate_submission_policy: Annotated[
        Literal["most_recent", "best"], Field(alias="final_graded_submission_policy")
    ] = "most_recent"

    min_group_size: int = 1
    max_group_size: int = 1

    submission_limit_per_day: int | None = None
    allow_submissions_past_limit: bool = True
    groups_combine_daily_submissions: bool = False
    submission_limit_reset_time: Annotated[
        datetime.time,
        PlainValidator(validate_time),
        WrapSerializer(lambda value, _: value.strftime("%I:%M%p")),
    ] = datetime.time(hour=0)
    num_bonus_submissions: int = 0

    send_email_receipts: bool | Literal["on_received", "on_finish"] = False

    @computed_field
    @property
    def send_email_on_submission_received(self) -> bool:
        return self.send_email_receipts is True or self.send_email_receipts == "on_received"

    @computed_field
    @property
    def send_email_on_non_deferred_tests_finished(self) -> bool:
        return self.send_email_receipts is True or self.send_email_receipts == "on_finish"

    honor_pledge: str | None = ""

    @computed_field
    @property
    def use_honor_pledge(self) -> bool:
        return self.honor_pledge is not None

    @computed_field
    @property
    def honor_pledge_text(self) -> str:
        return self.honor_pledge if self.honor_pledge is not None else ""

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
) -> Literal["exact_match", "fnmatch"] | None:
    if isinstance(value, dict):
        if "filename" in value:
            return "exact_match"

        if "pattern" in value:
            return "fnmatch"

        return None

    if hasattr(value, "filename"):
        return "exact_match"

    if hasattr(value, "pattern"):
        return "fnmatch"

    return None


ExpectedStudentFile: TypeAlias = Annotated[
    Annotated[ExactMatchExpectedStudentFile, Tag("exact_match")]
    | Annotated[FnmatchExpectedStudentFile, Tag("fnmatch")],
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
    internal_admin_notes: str = ""
    staff_description: str = ""
    student_description: str = ""
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
    return_code: MultiCmdTestReturnCodeCheckSettings = Field(
        default_factory=lambda: MultiCmdTestReturnCodeCheckSettings()
    )
    stdout: MultiCmdTestOutputSettings = Field(
        default_factory=lambda: MultiCmdTestOutputSettings()
    )
    stderr: MultiCmdTestOutputSettings = Field(
        default_factory=lambda: MultiCmdTestOutputSettings()
    )
    diff_options: DiffOptions = Field(default_factory=lambda: DiffOptions())
    feedback: CommandFeedbackSettings = Field(default_factory=lambda: CommandFeedbackSettings())
    resources: ResourceLimits = Field(default_factory=lambda: ResourceLimits())

    repeat: list[dict[str, object]] = []

    def do_repeat(self) -> list[MultiCommandConfig]:
        raise NotImplementedError


class SingleCmdTestCaseConfig(BaseModel):
    name: str
    type: Literal["default", "single_cmd"] = "default"

    internal_admin_notes: str = ""
    staff_description: str = ""
    student_description: str = ""
    student_on_fail_description: str = ""

    cmd: str

    input: StdinSettings = Field(default_factory=lambda: StdinSettings())
    return_code: SingleCmdTestReturnCodeCheckSettings = Field(
        default_factory=lambda: SingleCmdTestReturnCodeCheckSettings()
    )
    stdout: SingleCmdTestOutputSettings = Field(
        default_factory=lambda: SingleCmdTestOutputSettings()
    )
    stderr: SingleCmdTestOutputSettings = Field(
        default_factory=lambda: SingleCmdTestOutputSettings()
    )
    diff_options: DiffOptions = Field(default_factory=lambda: DiffOptions())
    feedback: CommandFeedbackSettings = Field(default_factory=lambda: CommandFeedbackSettings())
    resources: ResourceLimits = Field(default_factory=lambda: ResourceLimits())

    repeat: list[dict[str, object]] = []

    def do_repeat(self) -> list[SingleCmdTestCaseConfig]:
        if not self.repeat:
            return [self]

        new_tests: list[SingleCmdTestCaseConfig] = []
        for substitution in self.repeat:
            new_data = self.model_dump(exclude_unset=True) | {
                "name": apply_substitutions(self.name, substitution),
                "cmd": apply_substitutions(self.cmd, substitution),
            }

            if self.input.instructor_file is not None:
                new_data["input"]["instructor_file"] = apply_substitutions(
                    self.input.instructor_file, substitution
                )
            if self.stdout.instructor_file is not None:
                new_data["stdout"]["instructor_file"] = apply_substitutions(
                    self.stdout.instructor_file, substitution
                )
            if self.stderr.instructor_file is not None:
                new_data["stderr"]["instructor_file"] = apply_substitutions(
                    self.stderr.instructor_file, substitution
                )

            if _REPEAT_OVERRIDE_KEY in substitution:
                overrides = substitution[_REPEAT_OVERRIDE_KEY]
                if not isinstance(overrides, dict):
                    raise AGConfigError(
                        "Expected a dictionary for repeat overrides, "
                        f'but was "{type(overrides)}"'
                    )

                # See https://github.com/microsoft/pyright/discussions/1792
                for key, value in cast(Mapping[Any, Any], overrides).items():
                    if key not in new_data or not isinstance(key, str):
                        raise AGConfigError(
                            f'Warning: unrecognized field "{key}" in '
                            'repeat override for test "{self.name}"'
                        )

                    if isinstance(value, dict):
                        new_data[key].update(value)
                    else:
                        new_data[key] = value

            new_tests.append(SingleCmdTestCaseConfig.model_validate(new_data))

        return new_tests


def apply_substitutions(string: str, sub: dict[str, object]) -> str:
    for placeholder, replacement in sub.items():
        if placeholder != _REPEAT_OVERRIDE_KEY:
            string = string.replace(placeholder, str(replacement))

    return string


_REPEAT_OVERRIDE_KEY: Final = "_override"


class StdinSettings(BaseModel):
    source: ag_schema.StdinSource = "none"
    text: str = ""
    instructor_file: str | None = None


class SingleCmdTestReturnCodeCheckSettings(BaseModel):
    expected: ag_schema.ExpectedReturnCode = "none"
    points: int = 0


class MultiCmdTestReturnCodeCheckSettings(BaseModel):
    expected: ag_schema.ExpectedReturnCode = "none"
    points: int = 0
    deduction: int = 0


class SingleCmdTestOutputSettings(BaseModel):
    compare_with: ag_schema.ExpectedOutputSource = "none"
    text: str = ""
    instructor_file: str | None = None
    points: int = 0


class MultiCmdTestOutputSettings(BaseModel):
    compare_with: ag_schema.ExpectedOutputSource = "none"
    text: str = ""
    instructor_file: str | None = None
    points: int = 0
    deduction: int = 0


class DiffOptions(BaseModel):
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
