#! /bin/bash

set -e

# Generate Python schema classes from the Autograder.io API schema.
# Uses the version of the API schema saved to
# src/ag_contrib/config/autograder_io_schema/schema.yml
# Replace that file and rerun this script to update to a newer version.

project_root=$(dirname "$(realpath $0)")/..

datamodel-codegen \
    --input $project_root/src/ag_contrib/config/autograder_io_schema/schema.yml \
    --input-file-type openapi \
    --output $project_root/src/ag_contrib/config/autograder_io_schema/schema.py \
    --output-model-type typing.TypedDict \
    --disable-timestamp \
    --use-annotated \
    --use-generic-container-types \
    --use-standard-collections \
    --use-non-positive-negative-number-constrained-types \
    --use-schema-description \
    --use-union-operator \
    --target-python-version 3.10 \
    --strip-default-none \
    --strict-nullable \
    --enum-field-as-literal one \
    --use-subclass-enum
