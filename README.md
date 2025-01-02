# Autograder.io Command-Line Interface
Contains utilities for writing applications that use the autograder.io API.

We recommend Amir Kamil's [autograder-tools](https://gitlab.eecs.umich.edu/akamil/autograder-tools/tree/master) for a larger collection of applications.

# Install with pip
```
pip install autograder-contrib
```

# Obtaining a Token
Visit https://autograder.io/web/__apitoken__ and sign in.
Save the file you are prompted to download as `.agtoken` in your home directory or the directory.

# The Command Line Interface
This library provides a simple command line interface for sending requests:
```
$ agcli get /api/users/current/
```

This interface notably does not support delete requests for safety reasons. If you wish to delete something, please do so through the autograder.io website or (at your own risk) you may use the HTTPClient class described in the next section.

# The HTTPClient
The `HTTPClient` class is a starting point for sending custom requests in Python applications.
```
import json
from ag_contrib.http_client import HTTPClient, check_response_status

client = HTTPClient.make_default()
response = client.get('/api/users/current/')
check_response_status(response)
print(json.dumps(response.json(), indent=4))
```
# Developer Setup
https://github.com/homeport/dyff
curl --silent --location https://git.io/JYfAY | bash
