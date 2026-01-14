#! /bin/bash

set -e

project_root=$(dirname "$(realpath $0)")/..

$project_root/tests/new_save_modify_load_test.sh $@
