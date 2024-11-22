"""
Set up autograder.io assignments using a YAML config file.
"""

import argparse
from typing import get_args

from .config.generated.schema import Semester
from .config.init_project import init_project
from .config.load_project import load_project
from .config.save_project import save_project


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
    config_parser = tool_parsers.add_parser("project")
    subparsers = config_parser.add_subparsers(required=True)

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
        default='fixed',
    )
    load_project_parser.set_defaults(func=load_project)

    return parser.parse_args()


DEFAULT_config_file = "ag_project.yml"


if __name__ == "__main__":
    main()
