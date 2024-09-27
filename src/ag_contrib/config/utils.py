from typing import Literal, Mapping, TypeVar, overload

from pydantic import TypeAdapter
from requests import Response

import ag_contrib.config.generated.schema as ag_schema

from ..http_client import HTTPClient, check_response_status
from .models import AGConfigError

T = TypeVar("T")


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
