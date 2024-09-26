project_root=$(dirname "$(realpath $0)")/..

docker compose -f $project_root/test/local_stack/docker-compose.yml $@

