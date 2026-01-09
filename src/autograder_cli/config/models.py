from __future__ import annotations

import datetime
import itertools
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any, Final, Literal, TypeAlias, cast
from zoneinfo import ZoneInfo

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    PlainSerializer,
    PlainValidator,
    Tag,
    ValidationInfo,
    computed_field,
    field_validator,
    model_validator,
)

from autograder_cli.config.autograder_io_schema import schema as ag_schema

from .time_processing import (
    serialize_datetime,
    serialize_duration,
    serialize_time,
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
    # TODO: Restore when we add image building support
    # docker_images: dict[str, DockerImage] = {}


class ProjectConfig(BaseModel):
    name: str
    timezone: Annotated[
        ZoneInfo,
        PlainValidator(validate_timezone),
        PlainSerializer(serialize_timezone),
    ]
    course: CourseSelection
    settings: ProjectSettings
    student_files: Sequence[ExpectedStudentFile] = []
    instructor_files: list[InstructorFileConfig] = []
    test_suites: list[TestSuiteConfig] = []
    mutation_suites: list[MutationSuiteConfig] = []

    handgrading: HandgradingConfig | None = None

    @field_validator("settings", mode="before")
    @classmethod
    def allow_empty_settings(cls, value: object, info: ValidationInfo):
        if value is None:
            return ProjectSettings(_timezone=info.data["timezone"])

        return value

    @model_validator(mode="after")
    def set_timezones(self, info: ValidationInfo):
        if not isinstance(info.context, dict):
            return self

        if not info.context.get("read_yaml"):  # type: ignore
            return self

        if self.settings.deadline is None:
            return self

        self.settings.deadline.deadline = self.settings.deadline.deadline.replace(
            tzinfo=self.timezone
        )
        match (self.settings.deadline.cutoff_type):
            case "fixed":
                self.settings.deadline.cutoff = self.settings.deadline.cutoff.replace(
                    tzinfo=self.timezone
                )
            case "relative" | "none":
                pass

        return self


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
    # TODO: Replace with validate_by_name and validate_by_alias when we
    # update to Pydantic 2.11:
    # https://docs.pydantic.dev/latest/api/config/#pydantic.config.ConfigDict.populate_by_name
    model_config = ConfigDict(populate_by_name=True)

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
        PlainSerializer(serialize_time),
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

    honor_pledge: str | None = None

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


ExactMatchExpectedStudentFile: TypeAlias = str


class FnmatchExpectedStudentFile(BaseModel):
    pattern: str
    min_num_matches: int = 1
    max_num_matches: int

    def __str__(self) -> str:
        return self.pattern


def _get_expected_student_file_discriminator(
    value: object,
) -> Literal["exact_match", "fnmatch"] | None:
    if isinstance(value, str):
        return "exact_match"

    if isinstance(value, dict):
        if "pattern" in value:
            return "fnmatch"

        return None

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


class TestSuiteFeedbackSettings(BaseModel):
    normal: str | ag_schema.AGTestSuiteFeedbackConfig = "public"
    final_graded_submission: str | ag_schema.AGTestSuiteFeedbackConfig = "public"
    past_limit_submission: str | ag_schema.AGTestSuiteFeedbackConfig = "public"
    staff_viewer: str | ag_schema.AGTestSuiteFeedbackConfig = "public"


class TestSuiteConfig(BaseModel):
    # TODO: Replace with validate_by_name and validate_by_alias when we
    # update to Pydantic 2.11:
    # https://docs.pydantic.dev/latest/api/config/#pydantic.config.ConfigDict.populate_by_name
    model_config = ConfigDict(populate_by_name=True)

    name: str
    sandbox_docker_image: str = "Default"
    instructor_files_needed: list[str] = []
    read_only_instructor_files: bool = True
    student_files_needed: list[str] = []

    allow_network_access: bool = False
    deferred: bool = False

    setup_suite_cmd: Annotated[str, Field(alias="setup_cmd")] = ""
    setup_suite_cmd_name: Annotated[str, Field(alias="setup_label")] = ""
    reject_submission_if_setup_fails: bool = False

    feedback: TestSuiteFeedbackSettings = TestSuiteFeedbackSettings()

    test_cases: list[SingleCmdTestCaseConfig | MultiCmdTestCaseConfig] = []

    @classmethod
    def from_api(cls, data: ag_schema.AGTestSuite) -> TestSuiteConfig:
        return TestSuiteConfig(
            name=data["name"],
            sandbox_docker_image=data["sandbox_docker_image"]["display_name"],
            instructor_files_needed=[file["name"] for file in data["instructor_files_needed"]],
            read_only_instructor_files=data["read_only_instructor_files"],
            student_files_needed=[file["pattern"] for file in data["student_files_needed"]],
            allow_network_access=data["allow_network_access"],
            deferred=data["deferred"],
            setup_suite_cmd=data["setup_suite_cmd"],
            setup_suite_cmd_name=data["setup_suite_cmd_name"],
            reject_submission_if_setup_fails=data["reject_submission_if_setup_fails"],
            feedback=TestSuiteFeedbackSettings(
                normal=_suite_fdbk_dict_to_preset(data["normal_fdbk_config"]),
                final_graded_submission=_suite_fdbk_dict_to_preset(
                    data["ultimate_submission_fdbk_config"]
                ),
                past_limit_submission=_suite_fdbk_dict_to_preset(
                    data["past_limit_submission_fdbk_config"]
                ),
                staff_viewer=_suite_fdbk_dict_to_preset(data["staff_viewer_fdbk_config"]),
            ),
            test_cases=[_test_case_from_api(test_case) for test_case in data["ag_test_cases"]],
        )


def _suite_fdbk_dict_to_preset(
    fdbk_config: ag_schema.AGTestSuiteFeedbackConfig,
) -> str | ag_schema.AGTestSuiteFeedbackConfig:
    search_for = sorted(fdbk_config.items())

    for preset_name, preset_value in BUILTIN_TEST_SUITE_FDBK_PRESETS.items():
        if search_for == sorted(preset_value.items()):
            return preset_name

    return fdbk_config


def _test_case_from_api(data: ag_schema.AGTestCase):
    num_cmds = len(data["ag_test_commands"])
    if num_cmds == 0:
        return SingleCmdTestCaseConfig(
            name=data["name"],
            type="single_cmd",
            internal_admin_notes=data["internal_admin_notes"],
            staff_description=data["staff_description"],
            student_description=data["student_description"],
            student_on_fail_description="",
            cmd="",
        )
    elif num_cmds == 1:
        cmd = data["ag_test_commands"][0]
        return SingleCmdTestCaseConfig(
            name=cmd["name"],
            type="single_cmd",
            internal_admin_notes=cmd["internal_admin_notes"],
            staff_description=cmd["staff_description"],
            student_description=cmd["student_description"],
            student_on_fail_description=cmd["student_on_fail_description"],
            cmd=cmd["cmd"],
            input=StdinSettings(
                source=cmd["stdin_source"],
                text=cmd["stdin_text"],
                instructor_file=_get_instructor_file_name(cmd["stdin_instructor_file"]),
            ),
            return_code=SingleCmdTestReturnCodeCheckSettings(
                expected=cmd["expected_return_code"],
                points=cmd["points_for_correct_return_code"],
            ),
            stdout=SingleCmdTestOutputSettings(
                compare_with=cmd["expected_stdout_source"],
                text=cmd["expected_stdout_text"],
                instructor_file=_get_instructor_file_name(cmd["expected_stdout_instructor_file"]),
                points=cmd["points_for_correct_stdout"],
            ),
            stderr=SingleCmdTestOutputSettings(
                compare_with=cmd["expected_stderr_source"],
                text=cmd["expected_stderr_text"],
                instructor_file=_get_instructor_file_name(cmd["expected_stderr_instructor_file"]),
                points=cmd["points_for_correct_stderr"],
            ),
            diff_options=DiffOptions(
                ignore_case=cmd["ignore_case"],
                ignore_whitespace=cmd["ignore_whitespace"],
                ignore_whitespace_changes=cmd["ignore_whitespace_changes"],
                ignore_blank_lines=cmd["ignore_blank_lines"],
            ),
            feedback=TestCommandFeedbackSettings(
                normal=_cmd_fdbk_dict_to_preset(cmd["normal_fdbk_config"]),
                first_failed_test=(
                    _cmd_fdbk_dict_to_preset(cmd["first_failed_test_normal_fdbk_config"])
                    if cmd["first_failed_test_normal_fdbk_config"] is not None
                    else None
                ),
                final_graded_submission=_cmd_fdbk_dict_to_preset(
                    cmd["ultimate_submission_fdbk_config"]
                ),
                past_limit_submission=_cmd_fdbk_dict_to_preset(
                    cmd["past_limit_submission_fdbk_config"]
                ),
                staff_viewer=_cmd_fdbk_dict_to_preset(cmd["staff_viewer_fdbk_config"]),
            ),
            resources=ResourceLimits(
                time_limit=cmd["time_limit"],
                virtual_memory_limit=(
                    cmd["virtual_memory_limit"] if cmd["use_virtual_memory_limit"] else None
                ),
                block_process_spawn=cmd["block_process_spawn"],
            ),
        )
    else:
        return MultiCmdTestCaseConfig(
            name=data["name"],
            type="multi_cmd",
            internal_admin_notes=data["internal_admin_notes"],
            staff_description=data["staff_description"],
            student_description=data["student_description"],
            feedback=MultiCmdTestCaseFdbkConfig(
                normal=data["normal_fdbk_config"],
                past_limit_submission=data["past_limit_submission_fdbk_config"],
                staff_viewer=data["staff_viewer_fdbk_config"],
                final_graded_submission=data["ultimate_submission_fdbk_config"],
            ),
            commands=[
                MultiCommandConfig(
                    name=cmd["name"],
                    internal_admin_notes=cmd["internal_admin_notes"],
                    staff_description=cmd["staff_description"],
                    student_description=cmd["student_description"],
                    student_on_fail_description=cmd["student_on_fail_description"],
                    cmd=cmd["cmd"],
                    input=StdinSettings(
                        source=cmd["stdin_source"],
                        text=cmd["stdin_text"],
                        instructor_file=_get_instructor_file_name(cmd["stdin_instructor_file"]),
                    ),
                    return_code=MultiCmdTestReturnCodeCheckSettings(
                        expected=cmd["expected_return_code"],
                        points=cmd["points_for_correct_return_code"],
                        deduction=cmd["deduction_for_wrong_return_code"],
                    ),
                    stdout=MultiCmdTestOutputSettings(
                        compare_with=cmd["expected_stdout_source"],
                        text=cmd["expected_stdout_text"],
                        instructor_file=_get_instructor_file_name(
                            cmd["expected_stdout_instructor_file"]
                        ),
                        points=cmd["points_for_correct_stdout"],
                        deduction=cmd["deduction_for_wrong_stdout"],
                    ),
                    stderr=MultiCmdTestOutputSettings(
                        compare_with=cmd["expected_stderr_source"],
                        text=cmd["expected_stderr_text"],
                        instructor_file=_get_instructor_file_name(
                            cmd["expected_stderr_instructor_file"]
                        ),
                        points=cmd["points_for_correct_stderr"],
                        deduction=cmd["deduction_for_wrong_stderr"],
                    ),
                    diff_options=DiffOptions(
                        ignore_case=cmd["ignore_case"],
                        ignore_whitespace=cmd["ignore_whitespace"],
                        ignore_whitespace_changes=cmd["ignore_whitespace_changes"],
                        ignore_blank_lines=cmd["ignore_blank_lines"],
                    ),
                    feedback=TestCommandFeedbackSettings(
                        normal=_cmd_fdbk_dict_to_preset(cmd["normal_fdbk_config"]),
                        first_failed_test=(
                            _cmd_fdbk_dict_to_preset(cmd["first_failed_test_normal_fdbk_config"])
                            if cmd["first_failed_test_normal_fdbk_config"] is not None
                            else None
                        ),
                        final_graded_submission=_cmd_fdbk_dict_to_preset(
                            cmd["ultimate_submission_fdbk_config"]
                        ),
                        past_limit_submission=_cmd_fdbk_dict_to_preset(
                            cmd["past_limit_submission_fdbk_config"]
                        ),
                        staff_viewer=_cmd_fdbk_dict_to_preset(cmd["staff_viewer_fdbk_config"]),
                    ),
                    resources=ResourceLimits(
                        time_limit=cmd["time_limit"],
                        virtual_memory_limit=(
                            cmd["virtual_memory_limit"]
                            if cmd["use_virtual_memory_limit"]
                            else None
                        ),
                        block_process_spawn=cmd["block_process_spawn"],
                    ),
                )
                for cmd in data["ag_test_commands"]
            ],
        )


def _get_instructor_file_name(file: ag_schema.InstructorFile | None) -> str | None:
    return file["name"] if file is not None else None


def _cmd_fdbk_dict_to_preset(
    fdbk_config: ag_schema.AGTestCommandFeedbackConfig,
) -> str | ag_schema.AGTestCommandFeedbackConfig:
    search_for = sorted(fdbk_config.items())

    for preset_name, preset_value in BUILTIN_CMD_FDBK_PRESETS.items():
        if search_for == sorted(preset_value.items()):
            return preset_name

    return fdbk_config


class MultiCmdTestCaseConfig(BaseModel):
    name: str
    type: Literal["multi_cmd"] = "multi_cmd"
    repeat: list[dict[str, object]] = []
    internal_admin_notes: str = ""
    staff_description: str = ""
    student_description: str = ""
    feedback: MultiCmdTestCaseFdbkConfig = Field(
        default_factory=lambda: MultiCmdTestCaseFdbkConfig()
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

                    if command.input.instructor_file is not None:
                        command.input.instructor_file = apply_substitutions(
                            command.input.instructor_file, substitution
                        )
                    if command.stdout.instructor_file is not None:
                        command.stdout.instructor_file = apply_substitutions(
                            command.stdout.instructor_file, substitution
                        )
                    if command.stderr.instructor_file is not None:
                        command.stderr.instructor_file = apply_substitutions(
                            command.stderr.instructor_file, substitution
                        )

                    # FIXME: Docs: don't support _override here (unclear
                    # how to specify which command an override applies to)

                new_tests.append(new_test)

        # Command repeating should happen regardless of whether
        # the test case itself is repeating.
        for new_test in new_tests:
            new_test.commands = list(
                itertools.chain(*[cmd.do_repeat() for cmd in new_test.commands])
            )

        return new_tests


class MultiCmdTestCaseFdbkConfig(BaseModel):
    normal: ag_schema.AGTestCaseFeedbackConfig = {
        "visible": True,
        "show_individual_commands": True,
        "show_student_description": True,
    }
    final_graded_submission: ag_schema.AGTestCaseFeedbackConfig = {
        "visible": True,
        "show_individual_commands": True,
        "show_student_description": True,
    }
    past_limit_submission: ag_schema.AGTestCaseFeedbackConfig = {
        "visible": True,
        "show_individual_commands": True,
        "show_student_description": True,
    }
    staff_viewer: ag_schema.AGTestCaseFeedbackConfig = {
        "visible": True,
        "show_individual_commands": True,
        "show_student_description": True,
    }


class MultiCommandConfig(BaseModel):
    name: str
    cmd: str

    internal_admin_notes: str = ""
    staff_description: str = ""
    student_description: str = ""
    student_on_fail_description: str = ""

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
    feedback: TestCommandFeedbackSettings = Field(
        default_factory=lambda: TestCommandFeedbackSettings()
    )
    resources: ResourceLimits = Field(default_factory=lambda: ResourceLimits())

    repeat: list[dict[str, object]] = []

    def do_repeat(self) -> list[MultiCommandConfig]:
        if not self.repeat:
            return [self]

        new_cmds: list[MultiCommandConfig] = []
        for substitution in self.repeat:
            new_data = self.model_dump() | {
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
                    if not isinstance(key, str) or key not in new_data:
                        raise AGConfigError(
                            f'Warning: unrecognized field "{key}" in '
                            f'repeat override for test "{self.name}"'
                        )

                    if isinstance(value, dict):
                        new_data[key].update(value)
                    else:
                        new_data[key] = value

            new_cmds.append(MultiCommandConfig.model_validate(new_data))

        return new_cmds


class SingleCmdTestCaseConfig(BaseModel):
    name: str
    type: Literal["single_cmd"] = "single_cmd"

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
    feedback: TestCommandFeedbackSettings = Field(
        default_factory=lambda: TestCommandFeedbackSettings()
    )
    resources: ResourceLimits = Field(default_factory=lambda: ResourceLimits())

    repeat: list[dict[str, object]] = []

    def do_repeat(self) -> list[SingleCmdTestCaseConfig]:
        if not self.repeat:
            return [self]

        new_tests: list[SingleCmdTestCaseConfig] = []
        for substitution in self.repeat:
            new_data = self.model_dump() | {
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
                    if not isinstance(key, str) or key not in new_data:
                        raise AGConfigError(
                            f'Warning: unrecognized field "{key}" in '
                            f'repeat override for test "{self.name}"'
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


class TestCommandFeedbackSettings(BaseModel):
    normal: ag_schema.AGTestCommandFeedbackConfig | str = "pass/fail"
    first_failed_test: ag_schema.AGTestCommandFeedbackConfig | str | None = None
    final_graded_submission: ag_schema.AGTestCommandFeedbackConfig | str = "pass/fail"
    past_limit_submission: ag_schema.AGTestCommandFeedbackConfig | str = "private"
    staff_viewer: ag_schema.AGTestCommandFeedbackConfig | str = "public"


class ResourceLimits(BaseModel):
    time_limit: int = 10
    virtual_memory_limit: int | None = None
    block_process_spawn: bool = False


class MutationCommandFeedbackOptions(BaseModel):
    show_return_code: bool
    show_stdout: bool
    show_stderr: bool


class MutationSetupCmdFeedback(BaseModel):
    normal: MutationCommandFeedbackOptions = MutationCommandFeedbackOptions(
        show_return_code=True,
        show_stdout=False,
        show_stderr=False,
    )
    final_graded_submission: MutationCommandFeedbackOptions = MutationCommandFeedbackOptions(
        show_return_code=True,
        show_stdout=False,
        show_stderr=False,
    )
    past_limit_submission: MutationCommandFeedbackOptions = MutationCommandFeedbackOptions(
        show_return_code=False,
        show_stdout=False,
        show_stderr=False,
    )
    staff_viewer: MutationCommandFeedbackOptions = MutationCommandFeedbackOptions(
        show_return_code=True,
        show_stdout=True,
        show_stderr=True,
    )


class MutationSetupCmd(BaseModel):
    cmd: str
    label: str = "Setup"
    feedback: MutationSetupCmdFeedback = MutationSetupCmdFeedback()
    resources: ResourceLimits = ResourceLimits()


class TestDiscoveryFeedback(BaseModel):
    normal: MutationCommandFeedbackOptions = MutationCommandFeedbackOptions(
        show_return_code=True,
        show_stdout=True,
        show_stderr=True,
    )
    final_graded_submission: MutationCommandFeedbackOptions = MutationCommandFeedbackOptions(
        show_return_code=True,
        show_stdout=True,
        show_stderr=True,
    )
    past_limit_submission: MutationCommandFeedbackOptions = MutationCommandFeedbackOptions(
        show_return_code=False,
        show_stdout=False,
        show_stderr=False,
    )
    staff_viewer: MutationCommandFeedbackOptions = MutationCommandFeedbackOptions(
        show_return_code=True,
        show_stdout=True,
        show_stderr=True,
    )


class TestDiscoveryCmd(BaseModel):
    # We set different defaults than the ones in the API for
    # cmd and max_num_student_tests so that these fields are
    # written to the YAML file from load_project if they have
    # the API defaults.
    cmd: str = (
        'echo "Replace this command with one that '
        'finds and prints the names of student-written test cases."'
    )
    max_num_student_tests: int = 20
    delimiter: Literal["newline", "any_whitespace"] = "any_whitespace"
    feedback: TestDiscoveryFeedback = TestDiscoveryFeedback()
    resources: ResourceLimits = ResourceLimits()


class MutationCommandOutputFeedbackOptions(BaseModel):
    show_stdout: bool
    show_stderr: bool


class FalsePositivesFeedback(BaseModel):
    normal: MutationCommandOutputFeedbackOptions = MutationCommandOutputFeedbackOptions(
        show_stdout=False,
        show_stderr=False,
    )
    final_graded_submission: MutationCommandOutputFeedbackOptions = (
        MutationCommandOutputFeedbackOptions(
            show_stdout=False,
            show_stderr=False,
        )
    )
    past_limit_submission: MutationCommandOutputFeedbackOptions = (
        MutationCommandOutputFeedbackOptions(
            show_stdout=False,
            show_stderr=False,
        )
    )
    staff_viewer: MutationCommandOutputFeedbackOptions = MutationCommandOutputFeedbackOptions(
        show_stdout=True,
        show_stderr=True,
    )


class FalsePositivesCmd(BaseModel):
    cmd: str = (
        'echo "Replace this with a command that includes '
        'the placeholder ${student_test_name}". '
        "The command should run that test against a correct "
        "implementation and exit nonzero (report a false positive) "
        "if the test incorrectly reports a bug "
        "in the correct implementation."
    )
    feedback: FalsePositivesFeedback = FalsePositivesFeedback()
    resources: ResourceLimits = ResourceLimits()


class FindBugsFeedback(BaseModel):
    normal: MutationCommandOutputFeedbackOptions = MutationCommandOutputFeedbackOptions(
        show_stdout=False,
        show_stderr=False,
    )
    final_graded_submission: MutationCommandOutputFeedbackOptions = (
        MutationCommandOutputFeedbackOptions(
            show_stdout=False,
            show_stderr=False,
        )
    )
    past_limit_submission: MutationCommandOutputFeedbackOptions = (
        MutationCommandOutputFeedbackOptions(
            show_stdout=False,
            show_stderr=False,
        )
    )
    staff_viewer: MutationCommandOutputFeedbackOptions = MutationCommandOutputFeedbackOptions(
        show_stdout=True,
        show_stderr=True,
    )


class FindBugsCmd(BaseModel):
    cmd: str = (
        'echo "Replace this with a command that includes '
        "the placeholders ${student_test_name} and ${buggy_impl_name}. "
        "The command should run that test against that buggy implementation "
        'and exit nonzero if the test detects the bug."'
    )
    resources: ResourceLimits = ResourceLimits()
    feedback: FindBugsFeedback = FindBugsFeedback()


BugsDetectedFeedback: TypeAlias = Literal[
    "hide", "num_bugs_detected", "detected_bug_names", "all_bug_names"
]


class MutationSuiteFeedbackSettings(BaseModel):
    visible: bool = True
    show_invalid_test_names: bool
    show_points: bool
    bugs_detected: BugsDetectedFeedback


class MutationSuiteFeedback(BaseModel):
    normal: MutationSuiteFeedbackSettings = MutationSuiteFeedbackSettings(
        show_invalid_test_names=True,
        show_points=True,
        bugs_detected="num_bugs_detected",
    )
    final_graded_submission: MutationSuiteFeedbackSettings = MutationSuiteFeedbackSettings(
        show_invalid_test_names=True,
        show_points=True,
        bugs_detected="num_bugs_detected",
    )
    past_limit_submission: MutationSuiteFeedbackSettings = MutationSuiteFeedbackSettings(
        show_invalid_test_names=False,
        show_points=False,
        bugs_detected="hide",
    )
    staff_viewer: MutationSuiteFeedbackSettings = MutationSuiteFeedbackSettings(
        show_invalid_test_names=True,
        show_points=True,
        bugs_detected="detected_bug_names",
    )


class MutantHintOptions(BaseModel):
    hint_limit_per_day: int | None = None
    daily_limit_reset_time: Annotated[
        datetime.time,
        PlainValidator(validate_time),
        PlainSerializer(serialize_time),
    ] = datetime.time(hour=0)
    hint_limit_per_submission: int | None = None

    obfuscate_bug_names: Literal["none", "sequential", "hash"] = "sequential"
    obfuscated_bug_names_prefix: str = "Bug "


class MutationSuiteConfig(BaseModel):
    name: str
    sandbox_docker_image: str = "Default"
    instructor_files_needed: list[str] = []
    read_only_instructor_files: bool = True
    student_files_needed: list[str] = []

    allow_network_access: bool = False
    deferred: bool = False

    bug_names: list[str] | dict[str, list[str]] = []
    points_per_bug: Decimal = Decimal(0)
    max_points: int | None = None

    setup: MutationSetupCmd | None = None
    test_discovery: TestDiscoveryCmd = TestDiscoveryCmd()
    false_positives_check: FalsePositivesCmd = FalsePositivesCmd()
    find_bugs: FindBugsCmd = FindBugsCmd()

    feedback: MutationSuiteFeedback = MutationSuiteFeedback()
    hint_options: MutantHintOptions = MutantHintOptions()


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


class HandgradingConfig(BaseModel):
    # TODO: Replace with validate_by_name and validate_by_alias when we
    # update to Pydantic 2.11:
    # https://docs.pydantic.dev/latest/api/config/#pydantic.config.ConfigDict.populate_by_name
    model_config = ConfigDict(populate_by_name=True)

    points_style: ag_schema.PointsStyle
    max_points: int | None = None

    show_only_applied_rubric_to_students: Annotated[
        bool,
        Field(
            alias="hide_unapplied_rubric_items",
            description="When handgrading grades are published, "
            "only show students rubric items that were applied "
            "to their submission.",
        ),
    ] = False

    handgraders_can_leave_comments: bool = False
    handgraders_can_adjust_points: bool = False

    criteria: list[HandgradingCriterionConfig] = []
    annotations: list[HandgradingAnnotationConfig] = []


class HandgradingCriterionConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    short_description: Annotated[str, Field(alias="name")] = ""
    long_description: str = ""
    points: int = 0


class HandgradingAnnotationConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    short_description: Annotated[str, Field(alias="name")] = ""
    long_description: str = ""
    deduction: int = 0
    max_deduction: int | None = None
