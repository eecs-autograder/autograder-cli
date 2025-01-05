#! /bin/bash

set -e

project_root=$(dirname "$(realpath $0)")/..

$project_root/tests/new_roundtrip_test.sh $@
