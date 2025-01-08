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

Check that you've authenticated correctly with the following command:
```
ag http get /api/users/current/
```
This command should return your user information.

**IMPORTANT**: If you are using your own deployment of Autograder.io, you will need to specify the base URL of that deployment for every command you run.
Specify the base URL with the --base_url flag, e.g.:
```
ag --base_url https://your.url.com http get /api/users/current/
```
You may want to alias `ag --base_url https://your.url.com` in your shell profile for convenience.

### Configure Autocomplete in VSCode
1. Install the [VSCode YAML plugin](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml) (published by RedHat).
2. Generate the Autograder.io CLI JSON Schema:
```
ag write-schema
```
This will create a file called `autograder_io_cli_schema.json` in the directory the above command was run in.
3. Add the following to your VSCode settings.json:
```
    "yaml.schemas": {
        "/path/to//autograder_io_cli_schema.json": ["agproject.yml", "*.agproject.yml"]
    }
```
This will cause the YAML plugin to recognize `agproject.yml` and `*.agproject.yml` files as using the Autograder.io CLI schema.

Pull requests are welcome that add instructions for setting up autocomplete on other editors.

### Common Usage
#### New Project From Scratch
Use the following command to create a project config file with default values.
Replace `'My Course' Fall 2025` with the name, term, and year of your course.
Replace `'My Project'` with the name of your assignment.
The course you identify by name, semester, and year must already exist before you can save the project.
This only creates the config file locally, it does not save any changes to Autograder.io.
```
ag project init 'My Course' Fall 2025 'My Project'
```

This will create a configuration file `agproject.yml`.
You can choose a different name with the `--config_file` flag.

This CLI attempts to detect your local timezone.
You can change the `timezone` field in the config file if you wish to use a different timezone.

See [Save a Project](Save-a-Project) to save your configured project

#### Download an Existing Project
This command creates a config file for an existing project and downloads instructor files associated with that project.
For example:
```
ag project load 'My Course' Fall 2025 'My Project' myproject.agproject.yml
```
will download the specified project and save its configuration to the file `myproject.agproject.yml`.
Instructor files for that project will be saved in the same directory as the config file.
That is, if you specify `../some/path/myproject.agproject.yml`, the instructor files will be saved to `../some/path/`.

#### Save a Project
To save your configured project to Autograder.io, run the following command from the same directory as the config file:
```
ag project save
```

You can specify a different config file with the `--config_file` flag.

## FAQ and Tips
### Repeating Test Cases
The config format provides a "repeat" mechanism for defining groups of similar test cases in a compact way.
For example:
```
project:
  # Project information and settings
  # ...
  test_suites:
  - name: Python Unit Tests
    test_cases:
    # $test_label is a user-chosen placeholder.
    # The leading $ is not required but helps readability.
    - name: Test $test_label
      cmd: python3 -m unittest -k $test_name
      return_code:
        expected: zero
      feedback:
        normal: pass/fail+timeout
        final_graded_submission: pass/fail+timeout
      # Define substitutions for our placeholders
      repeat:
        - $test_label: Normal 1
          $test_name: normal1
          # Specify specific values for this test case.
          _override:
            return_code:
              points: 2
        - $test_label: Edge 1
          $test_name: edge1
          _override:
            return_code:
              points: 3
```

Saving this configuration will create two test cases with the same feedback and expected return code settings, but with different names, commands, and point values.

### Default Values
Since there is not a perfect one-to-one mapping between CLI project configuration options and API fields, there are some cases where the CLI and API have different default values.
Removing a field from the config file and then saving the project will reset that value to its CLI default.

The `ag project init` command creates a config file with all fields present and set to their CLI defaults.
In contrast, the `ag project load` command creates a config file that only contains non-default values.

### Feedback Presets
The config file supports several presets for test case feedback settings.
You can also define your own feedback presets under the `feedback_presets` key (for single command tests or the commands in multi-command tests) and the `feedback_presets_test_suite_setup` key (for test suite setup commands).
The config file created by `ag project init` contains definitions for several built-in presets.
Do not edit the contents presets.
However, once you are familiar with the CLI's built-in presets, you may remove them from the config file.
The CLI will recognize them even if they are not present in the config file.

### Sandbox Images
The CLI does not yet support building sandbox images.
Please build your images through the Autograder.io website.
In test suite definitions in the config file, you may specify the name of any sandbox image you've built for the course on Autograder.io.

### Deleting Entries
The CLI currently does NOT support deleting entries such as instructor files, expected student files, or test cases.
Removing these entries from the config file and saving the project will NOT delete those entries.
If you need to delete those entires, please do so through the Autograder.io website.

## Versioning
This package uses calendar versioning following [Python conventions](https://packaging.python.org/en/latest/discussions/versioning/), with version numbers of the form `year.month.X`, where `X` is for minor versions.
We also make use of pre-release tags such as `.devX`.

The year and month of the release specify the earliest version of the Autograder.io API this package is compatible with.
However, the minor version number **does not correspond** to Autograder.io's minor version numbers.

## Dev Setup
### Clone the Repository
```
git clone --recursive git@github.com:eecs-autograder/autograder-cli.git
```

If you omitted the `--recursive` flag, initialize the submodule with:
```
git submodule update --init
```

### Install Dependencies
Create and activate a virtual environment:
```
python3.10 -m venv venv
source venv/bin/activate
```

Install package dependencies and install the autograder-cli as a local editable package:
```
pip install pip-tools
./dev_scripts/install_deps.sh
```

Install [dyff](https://github.com/homeport/dyff) for comparing yaml files in test cases:
```
curl --silent --location https://git.io/JYfAY | bash
```

### Build the Local autograder-server Stack
Build and start the stack:
```
./dev_scripts/local_stack.sh build
./dev_scripts/local_stack.sh up -d
```
`./dev_scripts/local_stack.sh` is an alias for a docker-compose command.

Generate the gpg secrets for the autograder-server stack:
```
python -m pip install Django==3.1 python-gnupg
cd tests/local_stack/autograder-server && python3 generate_secrets.py
```

[Running the tests](Tests) will finish preparing the stack by applying migrations and clearing the database.

### Linters
Run isort, black, pycodestyle, pydocstyle, and pyright to check for style, formatting, and type issues:
```
./dev_scripts/lint.sh
```
Python code should be formatted using isort and black.

### Tests
This project uses pytest as its test runner.
Most of the test cases are currently "roundtrip" tests that save and load a configuration.
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

In the `.expected.yml` files, if you haven't set any values in `project.settings`, you will need to set `project.settings` to an empty dictionary.
We haven't made the `new_roundtrip_test.sh` script make this change because it serves as a way to have new test cases fail until they are edited.

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

#### HTTP Client Command-Line Interface
This library provides a minimal command-line interface for sending custom HTTP requests to the Autograder.io API.
Run `ag http --help` for more details.
