#! /bin/bash

set -e

script_dir=$(dirname $(realpath "$0"))

$script_dir/install_deps.sh
pip install --editable .
