"""Offline test setup: no AWS credentials, no network, nothing written into the kit folder."""

from __future__ import annotations

import datetime as dt
import importlib.util
import socket
import sys
from pathlib import Path

import pytest

KIT_DIR = Path(__file__).resolve().parent.parent
if str(KIT_DIR) not in sys.path:
    sys.path.insert(0, str(KIT_DIR))

import kitlib  # noqa: E402

SCRIPT_NAMES = [
    "00_check", "10_deploy", "50_invoke", "55_observe", "60_loadtest",
    "70_change_one_setting", "90_teardown", "99_verify_clean",
]
ACCOUNT = "111122223333"  # the AWS documentation's example account id, not a real account
REGION = "us-east-1"
WHEN = dt.datetime(2026, 10, 7, 12, 0, 0, tzinfo=dt.timezone.utc)


def load_script(name: str):
    path = KIT_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"kit_script_{name}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any attempt to open a socket fails the test."""

    def refuse(*args, **kwargs):
        raise AssertionError("a test tried to open a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch, tmp_path):
    """No real credentials or kit settings leak in; state and results go to a temporary folder."""
    for key in list(kitlib.DEFAULTS) + ["AWS_PROFILE", "AWS_DEFAULT_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
                                         "AWS_SESSION_TOKEN", "AWS_DEFAULT_REGION", "AWS_ROLE_ARN",
                                         "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
                                         "AWS_CONTAINER_CREDENTIALS_FULL_URI", "AWS_CONTAINER_AUTHORIZATION_TOKEN",
                                         "AWS_CA_BUNDLE", "BOTO_CONFIG"]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "empty-home"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-aws-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-aws-credentials"))
    monkeypatch.setattr(kitlib, "STATE_FILE", tmp_path / ".state.json")
    monkeypatch.setattr(kitlib, "RESULTS_DIR", tmp_path / "results")


@pytest.fixture
def cfg():
    return kitlib.load_config(environ={}, env_file=KIT_DIR / "does-not-exist.env")


@pytest.fixture
def state_path(tmp_path):
    return tmp_path / ".state.json"


class Stubs:
    """Real boto3 clients with fake credentials, each wrapped in a botocore Stubber.

    The Stubber validates every request and every canned response against the installed
    botocore service model and never sends anything.
    """

    def __init__(self):
        import boto3
        from botocore.stub import Stubber

        self.clients = {}
        self.stubbers = {}
        for service in ("sagemaker", "sagemaker-runtime", "service-quotas", "iam", "sts", "logs", "cloudwatch"):
            client = boto3.client(service, region_name=REGION, aws_access_key_id="testing",
                                  aws_secret_access_key="testing")
            stubber = Stubber(client)
            stubber.activate()
            self.clients[service] = client
            self.stubbers[service] = stubber

    def __getitem__(self, service):
        return self.stubbers[service]

    def aws(self, out=None, dry_run=False):
        return kitlib.Aws(REGION, dry_run, out=out or (lambda line: None), clients=self.clients)

    def assert_all_used(self):
        for stubber in self.stubbers.values():
            stubber.assert_no_pending_responses()


@pytest.fixture
def stubs():
    return Stubs()


class Lines(list):
    """Collects printed lines."""

    def __call__(self, line=""):
        self.append(str(line))

    @property
    def text(self):
        return "\n".join(self)


@pytest.fixture
def lines():
    return Lines()


class FakeClock:
    def __init__(self, start=1000.0, step=0.0):
        self.now = start
        self.step = step

    def __call__(self):
        value = self.now
        self.now += self.step
        return value

    def sleep(self, seconds):
        self.now += seconds


def arn(kind: str, name: str) -> str:
    return f"arn:aws:sagemaker:{REGION}:{ACCOUNT}:{kind}/{name}"


def endpoint_summary(name: str, status: str = "InService") -> dict:
    return {"EndpointName": name, "EndpointArn": arn("endpoint", name), "CreationTime": WHEN,
            "LastModifiedTime": WHEN, "EndpointStatus": status}


def config_summary(name: str) -> dict:
    return {"EndpointConfigName": name, "EndpointConfigArn": arn("endpoint-config", name), "CreationTime": WHEN}


def model_summary(name: str) -> dict:
    return {"ModelName": name, "ModelArn": arn("model", name), "CreationTime": WHEN}


def describe_endpoint_response(name: str, status: str, reason: str | None = None) -> dict:
    response = {"EndpointName": name, "EndpointArn": arn("endpoint", name), "EndpointStatus": status,
                "CreationTime": WHEN, "LastModifiedTime": WHEN}
    if reason:
        response["FailureReason"] = reason
    return response


def add_empty_inventory(stubs: Stubs, cfg, endpoints=(), configs=(), models=(), log_groups=()):
    """Queue the four calls find_remaining() makes when nothing needs a tag lookup.

    Since review round 2 the log group call lists everything under /aws/sagemaker/Endpoints/ and the
    kit's log groups are picked out by name, so that a log group under another prefix is not missed."""
    stubs["sagemaker"].add_response("list_endpoints", {"Endpoints": list(endpoints)}, {"MaxResults": 100})
    stubs["sagemaker"].add_response("list_endpoint_configs", {"EndpointConfigs": list(configs)}, {"MaxResults": 100})
    stubs["sagemaker"].add_response("list_models", {"Models": list(models)}, {"MaxResults": 100})
    stubs["logs"].add_response(
        "describe_log_groups", {"logGroups": [{"logGroupName": name} for name in log_groups]},
        {"logGroupNamePrefix": kitlib.LOG_GROUP_ROOT, "limit": 50})


def queue_identity(stubs: Stubs, account: str = ACCOUNT):
    """Queue the answer to the identity question every script asks before it reads the state file."""
    stubs["sts"].add_response("get_caller_identity", {
        "UserId": "AIDAEXAMPLE", "Account": account, "Arn": f"arn:aws:iam::{account}:user/example"}, {})


def not_found(stubs: Stubs, service: str, operation: str, what: str, expected_params=None):
    stubs[service].add_client_error(operation, service_error_code="ValidationException",
                                    service_message=f'Could not find {what}.', http_status_code=400,
                                    expected_params=expected_params)


# ---------------------------------------------------------------------------
# A plain fake account with more than one Region (no botocore, no network).
# Used for the scenarios the Stubber cannot express: the same script pointed at the wrong Region
# or the wrong account. Request shapes are covered by the Stubber tests; these fakes cover behaviour.
# ---------------------------------------------------------------------------

OTHER_ACCOUNT = "444455556666"  # another example account id from the AWS documentation, not a real account
OTHER_REGION = "us-east-2"


class FakeAwsError(Exception):
    """Shaped like botocore's ClientError: a .response dict with Error and ResponseMetadata."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(f"An error occurred ({code}): {message}")
        self.response = {"Error": {"Code": code, "Message": message}, "ResponseMetadata": {"HTTPStatusCode": status}}


class World:
    """Fake AWS: accounts -> Regions -> endpoints, endpoint configurations, models, tags, log groups."""

    def __init__(self):
        self.places = {}
        self.calls = []  # (account, region, service, operation, params)

    def place(self, account: str, region: str) -> dict:
        return self.places.setdefault((account, region), {"endpoints": {}, "configs": {}, "models": {},
                                                           "tags": {}, "logs": set()})

    def operations(self, prefix: str = "") -> list[str]:
        return [f"{region}:{operation}" for _, region, _, operation, _ in self.calls if operation.startswith(prefix)]


class _FakeClient:
    service = ""

    def __init__(self, world: World, account: str, region: str, fail: dict | None = None):
        self.world, self.account, self.region, self.fail = world, account, region, fail or {}

    @property
    def here(self) -> dict:
        return self.world.place(self.account, self.region)

    def _record(self, operation: str, params: dict) -> None:
        self.world.calls.append((self.account, self.region, self.service, operation, params))
        failure = self.fail.get(operation)
        if failure is not None:
            raise failure

    def _arn(self, kind: str, name: str) -> str:
        return f"arn:aws:sagemaker:{self.region}:{self.account}:{kind}/{name}"


class FakeSageMaker(_FakeClient):
    service = "sagemaker"

    def _missing(self, what: str, name: str):
        return FakeAwsError("ValidationException", f'Could not find {what} "{name}".')

    def create_model(self, **params):
        self._record("create_model", params)
        self.here["models"][params["ModelName"]] = params
        self.here["tags"][self._arn("model", params["ModelName"])] = params.get("Tags", [])
        return {"ModelArn": self._arn("model", params["ModelName"])}

    def create_endpoint_config(self, **params):
        self._record("create_endpoint_config", params)
        self.here["configs"][params["EndpointConfigName"]] = params
        self.here["tags"][self._arn("endpoint-config", params["EndpointConfigName"])] = params.get("Tags", [])
        return {"EndpointConfigArn": self._arn("endpoint-config", params["EndpointConfigName"])}

    def create_endpoint(self, **params):
        self._record("create_endpoint", params)
        self.here["endpoints"][params["EndpointName"]] = {"status": "InService", **params}
        self.here["tags"][self._arn("endpoint", params["EndpointName"])] = params.get("Tags", [])
        after = self.fail.get("create_endpoint_after")  # AWS made the endpoint, the client never got the answer
        if after is not None:
            raise after
        return {"EndpointArn": self._arn("endpoint", params["EndpointName"])}

    def describe_endpoint(self, EndpointName):
        self._record("describe_endpoint", {"EndpointName": EndpointName})
        if EndpointName not in self.here["endpoints"]:
            raise self._missing("endpoint", EndpointName)
        return {"EndpointName": EndpointName, "EndpointArn": self._arn("endpoint", EndpointName),
                "EndpointStatus": self.here["endpoints"][EndpointName]["status"]}

    def delete_endpoint(self, EndpointName):
        self._record("delete_endpoint", {"EndpointName": EndpointName})
        if EndpointName not in self.here["endpoints"]:
            raise self._missing("endpoint", EndpointName)
        del self.here["endpoints"][EndpointName]
        return {}

    def delete_endpoint_config(self, EndpointConfigName):
        self._record("delete_endpoint_config", {"EndpointConfigName": EndpointConfigName})
        if EndpointConfigName not in self.here["configs"]:
            raise self._missing("endpoint configuration", EndpointConfigName)
        del self.here["configs"][EndpointConfigName]
        return {}

    def delete_model(self, ModelName):
        self._record("delete_model", {"ModelName": ModelName})
        if ModelName not in self.here["models"]:
            raise self._missing("model", ModelName)
        del self.here["models"][ModelName]
        return {}

    def _listed(self, bucket: str, params: dict) -> list[str]:
        needle = params.get("NameContains", "")
        return [name for name in self.here[bucket] if needle in name]

    def list_endpoints(self, **params):
        self._record("list_endpoints", params)
        return {"Endpoints": [{"EndpointName": name, "EndpointArn": self._arn("endpoint", name),
                               "EndpointStatus": self.here["endpoints"][name]["status"]}
                              for name in self._listed("endpoints", params)]}

    def list_endpoint_configs(self, **params):
        self._record("list_endpoint_configs", params)
        return {"EndpointConfigs": [{"EndpointConfigName": name, "EndpointConfigArn": self._arn("endpoint-config", name)}
                                    for name in self._listed("configs", params)]}

    def list_models(self, **params):
        self._record("list_models", params)
        return {"Models": [{"ModelName": name, "ModelArn": self._arn("model", name)}
                           for name in self._listed("models", params)]}

    def list_tags(self, ResourceArn):
        self._record("list_tags", {"ResourceArn": ResourceArn})
        return {"Tags": self.here["tags"].get(ResourceArn, [])}


class FakeLogs(_FakeClient):
    service = "logs"

    def describe_log_groups(self, **params):
        self._record("describe_log_groups", params)
        names = sorted(name for name in self.here["logs"] if name.startswith(params["logGroupNamePrefix"]))
        start = int(params.get("nextToken", "0"))
        size = params.get("limit", 50)
        page = {"logGroups": [{"logGroupName": name} for name in names[start:start + size]]}
        if start + size < len(names):
            page["nextToken"] = str(start + size)
        return page

    def delete_log_group(self, logGroupName):
        self._record("delete_log_group", {"logGroupName": logGroupName})
        if logGroupName not in self.here["logs"]:
            raise FakeAwsError("ResourceNotFoundException", "The specified log group does not exist.")
        self.here["logs"].remove(logGroupName)
        return {}


class FakeSts(_FakeClient):
    service = "sts"

    def get_caller_identity(self):
        self._record("get_caller_identity", {})
        return {"UserId": "AIDAEXAMPLE", "Account": self.account, "Arn": f"arn:aws:iam::{self.account}:user/example"}


class FakeIam(_FakeClient):
    service = "iam"

    def get_role(self, RoleName):
        self._record("get_role", {"RoleName": RoleName})
        return {"Role": {"Arn": f"arn:aws:iam::{self.account}:role/{RoleName}", "AssumeRolePolicyDocument": {}}}


class FakeQuotas(_FakeClient):
    service = "service-quotas"

    def get_service_quota(self, **params):
        self._record("get_service_quota", params)
        return {"Quota": {"Value": 1.0}}


def world_aws(world: World, region: str = REGION, account: str = ACCOUNT, out=None, fail: dict | None = None):
    """A kitlib.Aws that talks to the fake World as `account` in `region`. Asking it for another Region
    (the clean check does that for Regions the state file names) gives the same account in that Region."""
    clients = {cls.service: cls(world, account, region, fail)
               for cls in (FakeSageMaker, FakeLogs, FakeSts, FakeIam, FakeQuotas)}
    aws = kitlib.Aws(region, False, out=out or (lambda line: None), clients=clients)
    aws.for_region = lambda other: aws if other == region else world_aws(world, other, account, out, fail)
    return aws


def deploy_into(world: World, cfg, state_path, region: str = REGION, account: str = ACCOUNT) -> dict:
    """Put one endpoint, configuration and model of this kit into the fake World and write the state file
    a deploy in that Region and account would have written. Returns the state."""
    place = world.place(account, region)
    model, config = cfg.model_name("r1"), cfg.endpoint_config_name("r1")

    def sm_arn(kind, name):
        return f"arn:aws:sagemaker:{region}:{account}:{kind}/{name}"

    place["models"][model] = {}
    place["configs"][config] = {}
    place["endpoints"][cfg.endpoint_name] = {"status": "InService"}
    for kind, name in (("model", model), ("endpoint-config", config), ("endpoint", cfg.endpoint_name)):
        place["tags"][sm_arn(kind, name)] = cfg.tags()
    created = kitlib.iso(kitlib.utc_now() - dt.timedelta(hours=1))
    state = {
        "kit": kitlib.KIT_NAME, "region": region, "prefix": cfg.prefix, "account_id": account, "history": [],
        "resources": [
            {"type": "model", "name": model, "arn": sm_arn("model", model), "created_utc": created},
            {"type": "endpoint_config", "name": config, "arn": sm_arn("endpoint-config", config), "created_utc": created},
            {"type": "endpoint", "name": cfg.endpoint_name, "arn": sm_arn("endpoint", cfg.endpoint_name), "created_utc": created},
        ],
        "deploy": {"revision": "r1", "instance_type": cfg.instance_type, "usd_per_hour": 1.222,
                   "hf_model_id": cfg.hf_model_id, "image_uri": cfg.image_uri, "env": cfg.container_env(),
                   "inference_ami_version": cfg.inference_ami_version, "create_called_utc": created,
                   "in_service_utc": created, "deadline_utc": kitlib.iso(kitlib.utc_now() + dt.timedelta(hours=2)),
                   "region": region, "prefix": cfg.prefix, "account_id": account},
    }
    kitlib.save_state(state, state_path)
    return state
