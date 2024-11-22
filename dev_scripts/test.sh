script_dir=$(dirname "$(realpath $0)")
pytest --tb=short --ignore=$script_dir/../tests/local_stack $@
