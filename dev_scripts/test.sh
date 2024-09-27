script_dir=$(dirname "$(realpath $0)")
pytest --ignore=$script_dir/../tests/local_stack
