#! /bin/bash

project_root=$(dirname "$(realpath $0)")/..

pip-compile -o $project_root/requirements.txt $project_root/requirements.in
pip-compile -o $project_root/requirements-dev.txt $project_root/requirements-dev.in
pip-sync $project_root/requirements.txt $project_root/requirements-dev.txt
