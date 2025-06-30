"""
Command-line entrypoints for project management commands
and http client usage.
"""

import argparse
import json
from pathlib import Path
from typing import get_args

from requests import HTTPError

from .config.autograder_io_schema.schema import Semester
from .config.init_project import init_project
from .config.load_project import load_project
from .config.models import AGConfig
from .config.save_project import save_project
from .http_client import HTTPClient, check_response_status


def main():
    args = parse_args()
    kwargs = vars(args)
    func = kwargs.pop("func")
    func(**kwargs)


def parse_args():
    parser = argparse.ArgumentParser()

    parser.add_argument("--base_url", "-u", type=str, default="https://autograder.io/")
    parser.add_argument(
        "--token_file",
        "-t",
        type=str,
        default=".agtoken",
        help="A filename or a path describing where to find the API token. "
        "If a filename, searches the current directory and each "
        "directory up to and including the current user's home "
        "directory until the file is found.",
    )

    tool_parsers = parser.add_subparsers(required=True)

    project_config_parser = tool_parsers.add_parser("project")
    _project_config_parse_args(project_config_parser)

    http_parser = tool_parsers.add_parser("http")
    _http_parse_args(http_parser)

    write_schema_parser = tool_parsers.add_parser("write-schema")
    write_schema_parser.add_argument(
        "filename", nargs="?", default="autograder_io_cli_schema.json"
    )
    write_schema_parser.set_defaults(func=write_json_schema)

    return parser.parse_args()


def _project_config_parse_args(project_config_parser: argparse.ArgumentParser):
    subparsers = project_config_parser.add_subparsers(required=True)

    init_project_parser = subparsers.add_parser("init")
    init_project_parser.add_argument("course_name")
    init_project_parser.add_argument("course_term", choices=get_args(Semester))
    init_project_parser.add_argument("course_year")
    init_project_parser.add_argument("project_name")
    init_project_parser.add_argument("--config_file", "-f", default=DEFAULT_config_file)
    init_project_parser.set_defaults(func=init_project)

    save_project_parser = subparsers.add_parser("save")
    save_project_parser.add_argument("--config_file", "-f", default=DEFAULT_config_file)
    save_project_parser.set_defaults(func=save_project)

    load_project_parser = subparsers.add_parser("load")
    load_project_parser.add_argument("course_name")
    load_project_parser.add_argument("course_term", choices=get_args(Semester))
    load_project_parser.add_argument("course_year")
    load_project_parser.add_argument("project_name")
    load_project_parser.add_argument("output_file")
    load_project_parser.add_argument(
        "--deadline_cutoff_preference",
        "-d",
        choices=["relative", "fixed"],
        default="fixed",
    )
    load_project_parser.set_defaults(func=load_project)


DEFAULT_config_file = "agproject.yml"


def http_main(
    action: str, url: str, *, quiet: bool, json_body: str | None, base_url: str, token_file: str
):
    body: dict[str, object] = {} if json_body is None else json.loads(json_body)

    client = HTTPClient.make_default(token_filename=token_file, base_url=base_url)
    try:
        if action == "get":
            response = client.get(url)
            check_response_status(response)
            print(json.dumps(response.json(), indent=4))
        elif action == "get_pages":
            response = list(client.get_paginated(url))
            print(json.dumps(response, indent=4))
        elif action == "post":
            response = client.post(url, json=body)
            check_response_status(response)
            if not quiet:
                print(json.dumps(response.json(), indent=4))
        elif action == "put":
            response = client.put(url, json=body)
            check_response_status(response)
            if not quiet:
                print(json.dumps(response.json(), indent=4))
        elif action == "patch":
            response = client.patch(url, json=body)
            check_response_status(response)
            if not quiet:
                print(json.dumps(response.json(), indent=4))
    except HTTPError as e:
        if not quiet:
            print(json.dumps(e.response.json()))
        exit(1)


def _http_parse_args(http_parser: argparse.ArgumentParser):
    http_parser.add_argument("action", choices=("get", "get_pages", "post", "put", "patch"))
    http_parser.add_argument("url", type=str)

    http_parser.add_argument(
        "--json_body",
        "-j",
        type=str,
        default=None,
        help="JSON data (string-encoded) to be added to the request body.",
    )
    http_parser.add_argument(
        "--quiet",
        "-q",
        default=False,
        action="store_true",
        help="Don't print the response data for POST, PUT, and PATCH requests.",
    )

    http_parser.set_defaults(func=http_main)


def write_json_schema(filename: str, *args: object, **kwargs: object):
    with open(filename, "w") as f:
        json.dump(AGConfig.model_json_schema(), f, indent=2)

    print("If using VSCode, add the following to your workspace settings:")
    print(f"""
    "yaml.schemas": {{
        "{Path(filename).absolute()}": [
            "**/agproject.yml",
            "**/*.agproject.yml",
            "agproject.*.yml"
        ]
    }}
""")


if __name__ == "__main__":
    main()
