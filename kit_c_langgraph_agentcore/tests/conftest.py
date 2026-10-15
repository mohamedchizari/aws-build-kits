"""Shared test setup. Every test in this folder runs offline.

- the kit folder is put on sys.path so `agent` and `kitlib` import;
- any attempt to open a network connection, or to look a host name up, fails the test;
- AWS credential and Region variables are removed, so a stray boto3 call could
  not reach an account even if one were configured on this machine.
"""
from __future__ import annotations

import json
import pathlib
import socket
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_AWS_VARS = [
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE", "AWS_REGION", "AWS_DEFAULT_REGION", "AWS_ROLE_ARN",
    "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI", "AWS_BEARER_TOKEN_BEDROCK",
    "KIT_PREFIX", "MODEL_ID", "PLATFORM_VERSION", "KIT_FAKE_MODEL",
]


class NetworkBlocked(RuntimeError):
    pass


COLLECTED: dict = {}


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config, items):
    """Remember how many tests exist per file, before any -k or -m selection, so test_readme.py
    can hold README section 8 to the real numbers."""
    COLLECTED.clear()
    for item in items:
        name = pathlib.Path(str(item.fspath)).name
        COLLECTED[name] = COLLECTED.get(name, 0) + 1


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    def refuse(self, address, *args, **kwargs):
        raise NetworkBlocked(f"a test tried to open a network connection to {address!r}")

    def refuse_lookup(*args, **kwargs):
        # Review round 4 (emulator, finding 7): connect was refused but the name lookup before
        # it was not, so one test sent a DNS query for a public host.
        raise NetworkBlocked(f"a test tried to look up or connect to {args[:2]!r}")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse_lookup)
    monkeypatch.setattr(socket, "getaddrinfo", refuse_lookup)
    for name in _AWS_VARS:
        monkeypatch.delenv(name, raising=False)
    # point the AWS SDK at files that do not exist and switch off the metadata lookup
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-aws-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-aws-credentials"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    yield


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, status: int, body):
        self.status_code = status
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("no JSON body")
        return self._body


class ReplaySession:
    """Stands in for requests.Session and answers from recorded fixtures.

    Each fixture holds the request that produced it. A request that matches no
    loaded fixture fails the test, so the tools cannot drift from what was recorded.
    """

    def __init__(self, *fixture_names: str, ignore_params: bool = False):
        self.records = [load_fixture(n) for n in fixture_names]
        self.ignore_params = ignore_params
        self.calls: list[dict] = []

    def get(self, url, params=None, headers=None, timeout=None):
        sent = [list(p) for p in (params or [])]
        self.calls.append({"url": url, "params": sent, "headers": headers, "timeout": timeout})
        for record in self.records:
            if record["request"]["url"] != url:
                continue
            if self.ignore_params or record["request"]["params"] == sent:
                return FakeResponse(record["status"], record["body"])
        raise AssertionError(f"no recorded fixture for GET {url} with params {sent}")


class CannedSession:
    """Stands in for requests.Session: answers by the end of the URL, (status, body) per ending.

    For failures that were never recorded, such as an HTTP 500 from the search.
    """

    def __init__(self, by_url_ending: dict):
        self.by_url_ending = by_url_ending
        self.calls: list[dict] = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": [list(p) for p in (params or [])]})
        for ending, (status, body) in self.by_url_ending.items():
            if url.endswith(ending):
                return FakeResponse(status, body)
        raise AssertionError(f"no canned answer for GET {url}")


class RaisingSession:
    def __init__(self, exc: Exception):
        self.exc = exc
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        raise self.exc


# --------------------------------------------------------------------------
# helpers for the script tests
# --------------------------------------------------------------------------
def load_script(relative_path: str):
    """Import a script whose file name starts with a digit, e.g. '30_deploy.py'."""
    import importlib.util

    path = ROOT / relative_path
    name = "kit_script_" + relative_path.replace("/", "_").replace(".py", "")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Stubs:
    """Real boto3 clients with botocore's Stubber in front of them.

    The Stubber checks every request against the service model that ships in
    the AWS SDK (parameter names, types, required fields) and checks the canned
    response against the response model. No request leaves the process.
    """

    def __init__(self, region: str = "us-east-1"):
        self.region = region
        self.clients: dict = {}
        self.stubbers: dict = {}

    def client(self, service: str):
        if service not in self.clients:
            import boto3
            from botocore.stub import Stubber

            client = boto3.client(
                service, region_name=self.region,
                aws_access_key_id="testing", aws_secret_access_key="testing",
            )
            stubber = Stubber(client)
            stubber.activate()
            self.clients[service] = client
            self.stubbers[service] = stubber
        return self.clients[service]

    def add(self, service: str, operation: str, response: dict | None = None,
            expected: dict | None = None) -> None:
        self.client(service)
        self.stubbers[service].add_response(operation, response or {}, expected)

    def add_error(self, service: str, operation: str, code: str, status: int = 400,
                  expected: dict | None = None) -> None:
        self.client(service)
        self.stubbers[service].add_client_error(
            operation, service_error_code=code, http_status_code=status, expected_params=expected
        )

    def assert_all_used(self) -> None:
        for stubber in self.stubbers.values():
            stubber.assert_no_pending_responses()


@pytest.fixture()
def kit(monkeypatch, tmp_path):
    """kitlib with no config.env, no sleeping, and state and build paths in a temp folder."""
    import kitlib

    monkeypatch.setattr(kitlib, "load_env_file", lambda path=None: None)
    monkeypatch.setattr(kitlib, "sleep", lambda seconds: None)
    monkeypatch.setattr(kitlib, "STATE_PATH", tmp_path / "state.json")
    build = tmp_path / "build"
    monkeypatch.setattr(kitlib, "BUILD_DIR", build)
    monkeypatch.setattr(kitlib, "PACKAGE_ZIP", build / "deployment_package.zip")
    return kitlib


@pytest.fixture()
def stubs():
    return Stubs()


def make_aws(kitlib, stubs: Stubs, lines: list[str]):
    return kitlib.Aws(stubs.region, dry_run=False, client_factory=stubs.client, out=lines.append)


class FakeClientError(Exception):
    """Shaped like botocore's ClientError as far as the kit reads it."""

    def __init__(self, code: str, message: str = "x"):
        super().__init__(f"{code}: {message}")
        self.response = {"Error": {"Code": code, "Message": message}}


def make_fake_aws(kitlib, handlers: dict, lines: list[str], region: str = "us-east-1"):
    """An Aws that keeps the kit's own parameter check against the SDK's service definitions
    and answers from a dict of handlers, {operation: response | callable(**params) | exception}.
    For flows with many similar calls, where queueing Stubber responses one by one hides the
    point of the test. An operation with no handler fails the test."""

    class FakeAws(kitlib.Aws):
        def __init__(self):
            super().__init__(region, dry_run=False, out=lines.append)
            self.calls: list[tuple[str, str, dict]] = []

        def warm(self, service, operation, attempts=3):
            self._operation_model(service, operation)

        def call(self, service, operation, dry_result=None, single_attempt=False, **params):
            self.validate(service, operation, params)
            self.calls.append((service, operation, dict(params, _single_attempt=single_attempt)))
            if operation not in handlers:
                raise AssertionError(f"unexpected AWS call {service}.{operation}")
            answer = handlers[operation]
            answer = answer(**params) if callable(answer) else answer
            if isinstance(answer, BaseException):
                raise answer
            return answer

    return FakeAws()


ACCOUNT = "000000000000"  # placeholder, not a real account
RUNTIME_ID = "kitdemo_kitc_fr_agent-abcdefghij"
RUNTIME_ARN = f"arn:aws:bedrock-agentcore:us-east-1:{ACCOUNT}:runtime/{RUNTIME_ID}"
