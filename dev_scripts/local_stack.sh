#! /bin/bash

set -e

project_root=$(dirname "$(realpath $0)")/..

docker compose -f $project_root/tests/local_stack/docker-compose.yml $@

