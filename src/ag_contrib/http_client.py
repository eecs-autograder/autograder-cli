from typing import TYPE_CHECKING, Mapping, TypeAlias, TypedDict
from urllib.parse import urljoin

import requests
from typing_extensions import Unpack

from . import utils

_HeadersMapping: TypeAlias = Mapping[str, str | bytes]
if TYPE_CHECKING:
    from _typeshed import Incomplete
    from requests.sessions import _Auth  # pyright: ignore[reportPrivateUsage]
    from requests.sessions import _Cert  # pyright: ignore[reportPrivateUsage]
    from requests.sessions import _Data  # pyright: ignore[reportPrivateUsage]
    from requests.sessions import _Files  # pyright: ignore[reportPrivateUsage]
    from requests.sessions import _HooksInput  # pyright: ignore[reportPrivateUsage]
    from requests.sessions import _Params  # pyright: ignore[reportPrivateUsage]
    from requests.sessions import _TextMapping  # pyright: ignore[reportPrivateUsage]
    from requests.sessions import _Timeout  # pyright: ignore[reportPrivateUsage]
    from requests.sessions import _Verify  # pyright: ignore[reportPrivateUsage]
    from requests.sessions import RequestsCookieJar

    class RequestKwargs(TypedDict, total=False):
        params: _Params | None
        data: _Data | None
        headers: _HeadersMapping | None
        cookies: RequestsCookieJar | _TextMapping | None
        files: _Files | None
        auth: _Auth | None
        timeout: _Timeout | None
        allow_redirects: bool
        proxies: _TextMapping | None
        hooks: _HooksInput | None
        stream: bool | None
        verify: _Verify | None
        cert: _Cert | None
        json: Incomplete | None

else:

    class RequestKwargs(TypedDict):
        pass


class HTTPClient:
    """
    A convenience class that can be used to send authenticated requests
    to the API. Its HTTP methods use the requests library
    (https://requests.readthedocs.io/), and so they accept all keyword
    arguments accepted by the corresponding requests methods.

    Avoid constructing HTTPClient directly.
    Instead, use HTTPClient.make_default.
    """

    @staticmethod
    def make_default(token_filename: str = ".agtoken", base_url: str = "https://autograder.io/"):
        """
        Creates an HTTPClient instance with the API token found in token_filename.
        Token file discovery works as follows:
        - If token_filename is just a filename (no path information),
        the current directory and every upward directory until the home
        directory will be searched for a file with that name.
        - If token_filename is an absolute path or a relative path that
        contains at least one directory, that file will be opened and
        the token read to it.

        base_url will be prepended to all URLs passed to the client's
        request methods and defaults to https://autograder.io/.
        """
        return HTTPClient(utils.get_api_token(token_filename), base_url)

    def __init__(self, api_token: str, base_url: str):
        """
        Avoid constructing HTTPClient directly.
        Instead, use HTTPClient.make_default.
        """
        self.api_token = api_token
        self.base_url = base_url

    def get(self, url: str, **kwargs: Unpack[RequestKwargs]):
        return self.do_request("get", url, **kwargs)

    def get_paginated(self, url: str, **kwargs: Unpack[RequestKwargs]):
        page_url = url
        while page_url:
            response = self.get(page_url, **kwargs)
            check_response_status(response)
            for item in response.json()["results"]:
                yield item

            page_url = response.json()["next"]

    def post(self, url: str, **kwargs: Unpack[RequestKwargs]):
        return self.do_request("post", url, **kwargs)

    def put(self, url: str, **kwargs: Unpack[RequestKwargs]):
        return self.do_request("put", url, **kwargs)

    def patch(self, url: str, **kwargs: Unpack[RequestKwargs]):
        return self.do_request("patch", url, **kwargs)

    def delete(self, url: str, **kwargs: Unpack[RequestKwargs]):
        return self.do_request("delete", url, **kwargs)

    def do_request(self, method: str, url: str, **kwargs: Unpack[RequestKwargs]):
        updated_headers = {}
        if "headers" in kwargs and kwargs["headers"] is not None:
            updated_headers = dict(kwargs["headers"])

        updated_headers["Authorization"] = f"Token {self.api_token}"
        kwargs["headers"] = updated_headers

        return requests.request(method, urljoin(self.base_url, url), **kwargs)


def check_response_status(response: requests.Response):
    if not response.ok:
        if 500 <= response.status_code < 600:
            print(f"{response.status_code}: {response.reason}")
        else:
            try:
                print(response.json())
            except ValueError:
                print(response.text)

        response.raise_for_status()
