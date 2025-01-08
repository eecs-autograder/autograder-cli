#! /bin/bash

set -e

script_dir=$(dirname "$(realpath $0)")
python $script_dir/../tests/local_stack/setup_db.py
echo "fake token" > tests.agtoken
pytest -n auto --tb=short --ignore=$script_dir/../tests/local_stack $@
