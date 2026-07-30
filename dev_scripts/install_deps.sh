#! /bin/bash

set -e

pip install pip-tools
pip install --upgrade typing-extensions
pip-sync requirements.txt requirements-dev.txt
