pip install --user pip-tools
pip-sync requirements.txt requirements-dev.txt
pip install --user --editable .
