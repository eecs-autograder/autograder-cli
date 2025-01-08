#! /bin/bash

# When "init" is passed as the first argument to this scripts,
# builds and starts the local test stack and generates gpg secrets
# for the stack.
# Otherwise, acts as an alias for the "docker compose" command using
# the local stack's docker-compose file.

set -ex

project_root=$(dirname "$(realpath $0)")/..
docker_compose="docker compose -f $project_root/tests/local_stack/docker-compose.yml"

if [ $1 == "init" ]; then
    $docker_compose build
    $docker_compose pull
    $docker_compose up -d
    docker ps -a
    echo "Generating autograder-server gpg secrets"
    python -m pip install Django==3.1 python-gnupg
    cd tests/local_stack/autograder-server && python3 generate_secrets.py
    python -m pip uninstall -y Django==3.1 python-gnupg
else
    $docker_compose $@
fi

