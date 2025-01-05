#! /bin/bash

set -xe

script_dir=$(dirname "$(realpath $0)")

isort --check src tests
black --check src tests
pycodestyle \
    --exclude=autograder_io_schema,tests/local_stack \
    --ignore=W503,E133,E704,E501 \
    src tests
pydocstyle src tests/roundtrip tests/unit
pyright
