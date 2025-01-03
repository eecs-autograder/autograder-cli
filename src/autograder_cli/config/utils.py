from typing import Literal, Mapping, TypeVar, overload

import yaml
from pydantic import TypeAdapter
from requests import Response

import autograder_cli.config.autograder_io_schema.schema as ag_schema

from ..http_client import HTTPClient, check_response_status
from .models import AGConfig, AGConfigError


def write_yaml(config: AGConfig, filename: str, *, exclude_defaults: bool):
    with open(filename, "w") as f:
        yaml.dump(
            config.model_dump(
                mode="json",
                by_alias=True,
                context={"write_yaml": True},
                exclude_defaults=exclude_defaults,
                exclude={
                    "project": {
                        "settings": {
                            "soft_closing_time",
                            "closing_time",
                            "submission_limit_reset_timezone",
                            "send_email_on_submission_received",
                            "send_email_on_non_deferred_tests_finished",
                            "use_honor_pledge",
                            "honor_pledge_text",
                        },
                    }
                },
            ),
            f,
            sort_keys=False,
        )


@overload
def get_project_from_course(
    client: HTTPClient,
    course_name: str,
    course_term: ag_schema.Semester | None,
    course_year: int | None,
    project_name: str,
    *,
    raise_if_not_found: Literal[True],
) -> tuple[ag_schema.Course, ag_schema.Project]: ...


@overload
def get_project_from_course(
    client: HTTPClient,
    course_name: str,
    course_term: ag_schema.Semester | None,
    course_year: int | None,
    project_name: str,
    *,
    raise_if_not_found: Literal[False] = False,
) -> tuple[ag_schema.Course, ag_schema.Project | None]: ...


def get_project_from_course(
    client: HTTPClient,
    course_name: str,
    course_term: ag_schema.Semester | None,
    course_year: int | None,
    project_name: str,
    *,
    raise_if_not_found: bool = False,
) -> tuple[ag_schema.Course, ag_schema.Project | None]:
    course = do_get(
        client,
        f"/api/course/{course_name}/{course_term}/{course_year}/",
        ag_schema.Course,
    )

    projects = do_get_list(
        client,
        f'/api/courses/{course["pk"]}/projects/',
        ag_schema.Project,
    )

    project = next((p for p in projects if p["name"] == project_name), None)

    if project is None and raise_if_not_found:
        raise AGConfigError(
            f'Project "{project_name}" not found on course '
            f'"{course_name} {course_term} {course_year}"'
        )

    return course, project


T = TypeVar("T")


def do_get(client: HTTPClient, url: str, response_type: type[T]) -> T:
    response = client.get(url)
    check_response_status(response)
    return response_to_schema_obj(response, response_type)


def do_post(client: HTTPClient, url: str, request_body: object, response_type: type[T]) -> T:
    response = client.post(url, json=request_body)
    check_response_status(response)
    return response_to_schema_obj(response, response_type)


def do_patch(
    client: HTTPClient, url: str, request_body: Mapping[str, object] | str, response_type: type[T]
) -> T:
    if isinstance(request_body, dict):
        response = client.patch(url, json=request_body)
    else:
        response = client.patch(
            url, data=request_body, headers={"Content-Type": "application/json"}
        )
    check_response_status(response)
    return response_to_schema_obj(response, response_type)


def response_to_schema_obj(response: Response, class_: type[T]) -> T:
    return TypeAdapter(class_).validate_python(response.json())


def do_get_list(client: HTTPClient, url: str, element_type: type[T]) -> list[T]:
    response = client.get(url)
    check_response_status(response)
    type_adapter = TypeAdapter(element_type)
    return [type_adapter.validate_python(obj) for obj in response.json()]
