#! /bin/bash

set -e

script_dir=$(dirname "$(realpath $0)")
python $script_dir/../tests/roundtrip/setup_db.py
pytest -n auto --tb=short --ignore=$script_dir/../tests/local_stack $@
