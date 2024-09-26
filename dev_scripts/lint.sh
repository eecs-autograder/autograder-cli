set -xe

isort --check src test
black --check src test
pycodestyle src test
pydocstyle src test
pyright
