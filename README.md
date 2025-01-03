# Autograder.io Command-Line Interface
A command-line tool for managing assignments on Autograder.io.

We also recommend Amir Kamil's [autograder-tools](https://gitlab.eecs.umich.edu/akamil/autograder-tools/tree/master) as a complimentary collection of applications.

## Quickstart
### Install
While this tool is usable in its current state, things may change between now and our first official release.
To install the latest development release, pass the `--pre` flag to pip as below:
```
pip install --pre autograder-cli
```

### Obtain API Token
Visit https://autograder.io/web/__apitoken__ and sign in.
Save the file you are prompted to download as `.agtoken` in your home directory or the directory.

### Common Usage
#### Create a New Project
#### Download an Existing Project
#### Save a Project

## Dev Setup
### Install Dependencies
```
pip install pip-tools
./dev_scripts/install_deps.sh

# dyff is used for comparing yaml files in test cases
https://github.com/homeport/dyff
curl --silent --location https://git.io/JYfAY | bash
```

### Linters
```
./dev_scripts/lint.sh
```
This command runs isort, black, pycodestyle, pydocstyle, and pyright to check for style, formatting, and type issues.
Python code should be formatted using isort and black.

### Tests
To generate a new roundtrip test, run:
```
./dev_scripts/new_roundtrip_test.sh {test name}
```

The test name can include directories (e.g., ag_test_suite/setup_cmd).
This will initialize a roundtrip test in tests/roundtrip/{test name}.test.
Roundtrip tests consist of the following steps:
1. Save the project found in `{test name}/project.create.yml`.
2. Load that project and compare the loaded version with `{test name}/project.create.expected.yml`.
3. Save the project found in `{test name}/project.update.yml`. (this is intended to be the same project that was created in step one, but with some fields changed)
4. Load that project and compare the loaded version with `{test name}/project.update.expected.yml`.

When testing deadline formats (e.g., fixed cutoff, relative cutoff), you can specify which format to load deadlines into in the file `{test name}/deadline_cutoff_preference`.

### The HTTPClient
The `HTTPClient` class is a starting point for sending custom requests in Python applications.
```
import json
from ag_contrib.http_client import HTTPClient, check_response_status

client = HTTPClient.make_default()
response = client.get('/api/users/current/')
check_response_status(response)
print(json.dumps(response.json(), indent=4))
```
