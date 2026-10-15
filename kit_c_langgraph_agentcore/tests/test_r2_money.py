"""Second independent review, 2026-10-07 (round 2), teardown and the clean check: BLOCKER 1,
MAJOR 7 and MINORS 8, 9, 11, 12 and 14. Every test here failed on the code as it was reviewed,
except the ones marked "unchanged".

BLOCKER 1  A lost, damaged or older state file plus another Region gave CLEAN, and teardown
           deleted the live runtime's bucket and role. Teardown set a damaged state file
           aside and so destroyed the only record of where the deploy was.
MAJOR 7    Teardown never finished when GetAgentRuntime reported a missing runtime with an
           error code other than "not found".
MINOR 8    Teardown exited 0 after printing leftovers; a gateway stuck in DELETING was
           counted as gone.
MINOR 9    Teardown --dry-run exited 0.
MINOR 11   The clean check failed on an informational X-Ray call.
MINOR 12   Teardown could not empty a versioned code bucket.
MINOR 14   The RESULT line did not say when no state file was found.

The tests drive the real scripts against World, a small account that remembers what exists:
runtimes, gateways, log groups and workload identities per Region; buckets and IAM roles
for the whole account, as on AWS. Every request is still checked against the SDK's own
service definitions (conftest.make_fake_aws).
"""
from __future__ import annotations

import inspect
import json

import pytest
from conftest import ACCOUNT, FakeClientError, load_script, make_fake_aws

EAST, WEST = "us-east-1", "us-west-2"
ROLE = "kitdemo-kitc-runtime-role"


def not_found():
    return FakeClientError("ResourceNotFoundException")


class World:
    def __init__(self, kit, account: str = ACCOUNT):
        self.kit = kit
        self.account = account
        self.runtimes: dict[str, dict] = {}     # region -> {id: {"name", "arn", "status"}}
        self.gateways: dict[str, dict] = {}     # region -> {id: {"name", "status", "targets": {}}}
        self.identities: dict[str, set] = {}
        self.log_groups: dict[str, set] = {}
        self.buckets: dict[str, dict] = {}      # name -> {"region", "versions": [...], "versioned"}
        self.roles: dict[str, dict] = {}        # name -> {"inline": set(), "trust_region": str}
        self.tags: dict[str, dict] = {}         # arn -> region
        self.stuck_gateways = False
        self.get_runtime_error: str | None = None   # an error code for every get_agent_runtime
        self.denied: set[str] = set()               # operations that answer AccessDenied
        self.calls: list[tuple[str, str]] = []
        self.serial = 0

    # ------------------------------------------------------------------ building a deploy
    def deploy(self, region: str, prefix: str = "kitdemo", versioned: bool = False, tagged: bool = True) -> dict:
        self.serial += 1
        name = f"{prefix.replace('-', '_')}_kitc_fr_agent"
        runtime_id = f"{name}-ab{self.serial:08d}"
        arn = f"arn:aws:bedrock-agentcore:{region}:{self.account}:runtime/{runtime_id}"
        self.runtimes.setdefault(region, {})[runtime_id] = {"name": name, "arn": arn, "status": "READY"}
        self.identities.setdefault(region, set()).add(runtime_id)
        self.log_groups.setdefault(region, set()).add(f"/aws/bedrock-agentcore/runtimes/{runtime_id}-DEFAULT")
        bucket = f"{prefix}-kitc-code-{self.account}-{region}"
        versions = [{"Key": f"{name}/deployment_package.zip", "VersionId": "v1" if versioned else "null",
                     "marker": False}]
        self.buckets[bucket] = {"region": region, "versions": versions, "versioned": versioned}
        role = f"{prefix}-kitc-runtime-role"
        self.roles.setdefault(role, {"inline": {f"{prefix}-kitc-runtime-policy"}, "trust_region": region})
        if tagged:
            self.tags[arn] = region
            self.tags[f"arn:aws:s3:::{bucket}"] = region
        return {"region": region, "prefix": prefix, "account_id": self.account, "runtime_id": runtime_id,
                "runtime_arn": arn, "bucket": bucket, "role_name": role,
                "deployed_at": "2026-10-07T09:00:00Z"}

    def add_gateway(self, region: str, prefix: str = "kitdemo") -> str:
        self.serial += 1
        gateway_id = f"{prefix}-kitc-gateway-gw{self.serial:06d}"
        self.gateways.setdefault(region, {})[gateway_id] = {
            "name": f"{prefix}-kitc-gateway", "status": "READY", "targets": {"TGT0001": "federal-register"}}
        self.roles[f"{prefix}-kitc-gateway-role"] = {"inline": set(), "trust_region": region}
        return gateway_id

    def left(self) -> list[str]:
        out = [f"runtime {i} in {r}" for r, items in self.runtimes.items() for i in items]
        out += [f"gateway {i} in {r}" for r, items in self.gateways.items() for i in items]
        out += [f"bucket {n}" for n in self.buckets]
        out += [f"role {n}" for n in self.roles]
        out += [f"log group {n} in {r}" for r, items in self.log_groups.items() for n in items]
        return sorted(out)

    # ------------------------------------------------------------------ the AWS it answers as
    def aws(self, region: str, lines: list[str]):
        return make_fake_aws(self.kit, self._handlers(region), lines, region)

    def _handlers(self, region: str) -> dict:
        world = self

        def wrap(name, fn):
            def handler(**params):
                world.calls.append((region, name))
                if name in world.denied:
                    return FakeClientError("AccessDeniedException")
                return fn(**params)
            return handler

        def list_buckets(**p):
            return {"Buckets": [{"Name": n, "BucketRegion": b["region"]} for n, b in sorted(world.buckets.items())
                                if n.startswith(p.get("Prefix", ""))]}

        def bucket(name):
            if name not in world.buckets:
                raise KeyError(name)
            return world.buckets[name]

        def current_keys(b):
            latest = {}
            for version in b["versions"]:
                latest[version["Key"]] = version
            return [k for k, v in latest.items() if not v["marker"]]

        def list_objects_v2(**p):
            if p["Bucket"] not in world.buckets:
                return FakeClientError("NoSuchBucket")
            return {"Contents": [{"Key": k} for k in current_keys(bucket(p["Bucket"]))]}

        def delete_one(b, key, version_id):
            if version_id is not None:
                b["versions"] = [v for v in b["versions"] if not (v["Key"] == key and v["VersionId"] == version_id)]
            elif b["versioned"]:
                world.serial += 1
                b["versions"].append({"Key": key, "VersionId": f"dm{world.serial}", "marker": True})
            else:
                b["versions"] = [v for v in b["versions"] if v["Key"] != key]

        def delete_object(**p):
            delete_one(bucket(p["Bucket"]), p["Key"], p.get("VersionId"))
            return {}

        def list_object_versions(**p):
            if p["Bucket"] not in world.buckets:
                return FakeClientError("NoSuchBucket")
            b = bucket(p["Bucket"])
            out = {"IsTruncated": False}
            versions = [{"Key": v["Key"], "VersionId": v["VersionId"]} for v in b["versions"] if not v["marker"]]
            markers = [{"Key": v["Key"], "VersionId": v["VersionId"]} for v in b["versions"] if v["marker"]]
            if versions:
                out["Versions"] = versions
            if markers:
                out["DeleteMarkers"] = markers
            return out

        def delete_objects(**p):
            for target in p["Delete"]["Objects"]:
                delete_one(bucket(p["Bucket"]), target["Key"], target.get("VersionId"))
            return {}

        def delete_bucket(**p):
            if p["Bucket"] not in world.buckets:
                return FakeClientError("NoSuchBucket")
            if world.buckets[p["Bucket"]]["versions"]:
                return FakeClientError("BucketNotEmpty")
            del world.buckets[p["Bucket"]]
            return {}

        def get_agent_runtime(**p):
            if world.get_runtime_error:
                return FakeClientError(world.get_runtime_error, "No agent runtime with that identifier exists")
            item = world.runtimes.get(region, {}).get(p["agentRuntimeId"])
            return {"status": item["status"]} if item else not_found()

        def delete_agent_runtime(**p):
            if p["agentRuntimeId"] not in world.runtimes.get(region, {}):
                return not_found()
            del world.runtimes[region][p["agentRuntimeId"]]
            world.identities.get(region, set()).discard(p["agentRuntimeId"])
            return {"status": "DELETING"}

        def get_gateway(**p):
            item = world.gateways.get(region, {}).get(p["gatewayIdentifier"])
            return {"status": item["status"], "name": item["name"]} if item else not_found()

        def delete_gateway(**p):
            item = world.gateways.get(region, {}).get(p["gatewayIdentifier"])
            if item is None:
                return not_found()
            if world.stuck_gateways:
                item["status"] = "DELETING"
            else:
                del world.gateways[region][p["gatewayIdentifier"]]
            return {"status": "DELETING"}

        def list_gateway_targets(**p):
            item = world.gateways.get(region, {}).get(p["gatewayIdentifier"])
            if item is None:
                return not_found()
            return {"items": [{"targetId": t, "name": n} for t, n in item["targets"].items()]}

        def delete_gateway_target(**p):
            world.gateways[region][p["gatewayIdentifier"]]["targets"].pop(p["targetId"], None)
            return {"status": "DELETING"}

        def delete_workload_identity(**p):
            world.identities.get(region, set()).discard(p["name"])
            return {}

        def describe_log_groups(**p):
            return {"logGroups": [{"logGroupName": n} for n in sorted(world.log_groups.get(region, set()))
                                  if n.startswith(p.get("logGroupNamePrefix", ""))]}

        def delete_log_group(**p):
            world.log_groups.get(region, set()).discard(p["logGroupName"])
            return {}

        def get_role(**p):
            role = world.roles.get(p["RoleName"])
            if role is None:
                return FakeClientError("NoSuchEntity")
            trust = {"Statement": [{"Condition": {"ArnLike": {
                "aws:SourceArn": f"arn:aws:bedrock-agentcore:{role['trust_region']}:{world.account}:*"}}}]}
            return {"Role": {"RoleName": p["RoleName"], "AssumeRolePolicyDocument": trust}}

        def delete_role_policy(**p):
            world.roles[p["RoleName"]]["inline"].discard(p["PolicyName"])
            return {}

        def delete_role(**p):
            if p["RoleName"] not in world.roles:
                return FakeClientError("NoSuchEntity")
            del world.roles[p["RoleName"]]
            return {}

        def get_resources(**p):
            def alive(arn):
                tail = arn.rsplit("/", 1)[-1].rsplit(":::", 1)[-1]
                return tail in world.runtimes.get(region, {}) or tail in world.buckets
            return {"ResourceTagMappingList": [{"ResourceARN": a} for a, r in sorted(world.tags.items())
                                               if r == region and alive(a)]}

        handlers = {
            "get_caller_identity": lambda **p: {"Account": world.account, "UserId": "A",
                                                "Arn": f"arn:aws:iam::{world.account}:user/x"},
            "list_agent_runtimes": lambda **p: {"agentRuntimes": [
                {"agentRuntimeId": i, "agentRuntimeArn": r["arn"], "agentRuntimeName": r["name"],
                 "status": r["status"]} for i, r in sorted(world.runtimes.get(region, {}).items())]},
            "get_agent_runtime": get_agent_runtime, "delete_agent_runtime": delete_agent_runtime,
            "list_gateways": lambda **p: {"items": [
                {"gatewayId": i, "name": g["name"], "status": g["status"]}
                for i, g in sorted(world.gateways.get(region, {}).items())]},
            "get_gateway": get_gateway, "delete_gateway": delete_gateway,
            "list_gateway_targets": list_gateway_targets, "delete_gateway_target": delete_gateway_target,
            "list_workload_identities": lambda **p: {"workloadIdentities": [
                {"name": n} for n in sorted(world.identities.get(region, set()))]},
            "delete_workload_identity": delete_workload_identity,
            "list_roles": lambda **p: {"Roles": [{"RoleName": n, "Arn": f"arn:aws:iam::{world.account}:role/{n}"}
                                                 for n in sorted(world.roles)]},
            "get_role": get_role,
            "list_role_policies": lambda **p: {"PolicyNames": sorted(world.roles[p["RoleName"]]["inline"])},
            "list_attached_role_policies": lambda **p: {"AttachedPolicies": []},
            "delete_role_policy": delete_role_policy, "delete_role": delete_role,
            "list_buckets": list_buckets, "list_objects_v2": list_objects_v2, "delete_object": delete_object,
            "list_object_versions": list_object_versions, "delete_objects": delete_objects,
            "delete_bucket": delete_bucket,
            "describe_log_groups": describe_log_groups, "delete_log_group": delete_log_group,
            "describe_deliveries": lambda **p: {"deliveries": []},
            "describe_delivery_sources": lambda **p: {"deliverySources": []},
            "describe_delivery_destinations": lambda **p: {"deliveryDestinations": []},
            "get_resources": get_resources,
            "get_trace_segment_destination": lambda **p: {"Destination": "XRay", "Status": "ACTIVE"},
            "stop_runtime_session": lambda **p: {},
        }
        return {name: wrap(name, fn) for name, fn in handlers.items()}


@pytest.fixture()
def world(kit):
    return World(kit)


def _run(kit, world, script_name, region, argv=(), prefix=None, monkeypatch=None):
    """Run one of the two scripts the way a shell would: Region and prefix from the environment,
    the state file from disk. Returns (exit code, lines)."""
    import os

    script = load_script(script_name)
    lines: list[str] = []
    os.environ["AWS_REGION"] = region
    if prefix:
        os.environ["KIT_PREFIX"] = prefix
    else:
        os.environ.pop("KIT_PREFIX", None)
    try:
        kwargs = {"aws": world.aws(region, lines), "out": lines.append}
        if "aws_for_region" in inspect.signature(script.main).parameters:
            kwargs["aws_for_region"] = lambda r: world.aws(r, lines)
        try:
            rc = script.main(list(argv), **kwargs)
        except SystemExit as stop:  # argparse refusing an option the script does not have
            rc = stop.code
    finally:
        os.environ.pop("AWS_REGION", None)
        os.environ.pop("KIT_PREFIX", None)
    return rc, lines


def teardown(kit, world, region=EAST, argv=(), prefix=None):
    return _run(kit, world, "90_teardown.py", region, argv, prefix)


def verify(kit, world, region=EAST, argv=(), prefix=None):
    return _run(kit, world, "99_verify_clean.py", region, argv, prefix)


def result_of(lines) -> str:
    return next((line for line in reversed(lines) if line.startswith("RESULT:")), "")


def write_state(kit, record: dict):
    kit.STATE_PATH.write_text(json.dumps(record))


# ====================================================================== unchanged: the plain case still works
def test_unchanged_a_recorded_deploy_is_torn_down_and_then_verified_clean(kit, world):
    write_state(kit, world.deploy(EAST))
    rc, lines = teardown(kit, world)
    assert rc == 0 and world.left() == [], "\n".join(lines)
    assert any(line.startswith("Teardown finished without errors.") for line in lines)
    rc, lines = verify(kit, world)
    assert rc == 0 and result_of(lines).startswith("RESULT: CLEAN:")


# ====================================================================== BLOCKER 1
def test_B1_state_lost_and_the_wrong_region_teardown_leaves_the_live_deploys_bucket_and_role(kit, world):
    """C06b: deploy in us-west-2, .state.json deleted, a new shell with no export."""
    deployed = world.deploy(WEST)
    rc, lines = teardown(kit, world, EAST)
    text = "\n".join(lines)
    assert deployed["bucket"] in world.buckets and ROLE in world.roles  # nothing the runtime needs was deleted
    assert f"runtime {deployed['runtime_id']} in {WEST}" in world.left()
    assert rc == 1
    assert "(Region us-west-2)" in text and "NOT deleted" in text
    assert "Run: AWS_REGION=us-west-2 KIT_PREFIX=kitdemo python 90_teardown.py" in text
    assert not any(line.startswith("Teardown finished without errors") for line in lines)
    rc, lines = verify(kit, world, EAST)
    assert rc == 1 and result_of(lines).startswith("RESULT: NOT CLEAN")
    assert "AWS_REGION=us-west-2" in "\n".join(lines)
    # and the command it names does finish the job
    assert teardown(kit, world, WEST)[0] == 0 and world.left() == []


def test_B1_a_second_deploy_after_state_loss_teardown_keeps_the_first_regions_bucket_and_the_shared_role(kit, world):
    """C05b: deploy east, state lost, deploy west, tear down west."""
    first = world.deploy(EAST)
    second = world.deploy(WEST)
    write_state(kit, second)
    rc, lines = teardown(kit, world, WEST)
    assert rc == 1
    assert first["bucket"] in world.buckets and ROLE in world.roles and first["runtime_id"] in world.runtimes[EAST]
    assert second["bucket"] not in world.buckets and world.runtimes[WEST] == {}
    assert any(line.startswith("Teardown finished, BUT 2 resource(s) of this kit remain") for line in lines)
    # the west record is closed (its own things are gone), so the east teardown is not blocked by it
    saved = json.loads(kit.STATE_PATH.read_text())
    assert "runtime_id" not in saved and saved["history"][-1]["region"] == WEST
    assert saved["history"][-1]["left_in_place"]
    rc, lines = teardown(kit, world, EAST)
    assert rc == 0 and world.left() == [], "\n".join(lines)
    assert any("checked Region us-west-2: no runtime or gateway of this kit there" in line for line in lines)


def test_B1_an_older_state_file_from_before_the_deploy_does_not_license_deleting_another_regions_bucket(kit, world):
    """C09b: the state is a copy from before this deploy (history only); the deploy is in us-west-2."""
    write_state(kit, {"history": [{"region": EAST, "prefix": "kitdemo", "account_id": ACCOUNT}]})
    deployed = world.deploy(WEST)
    rc, lines = teardown(kit, world, EAST)
    assert rc == 1 and deployed["bucket"] in world.buckets and ROLE in world.roles
    rc, lines = verify(kit, world, EAST)
    assert rc == 1 and result_of(lines).startswith("RESULT: NOT CLEAN")


def test_B1_the_role_is_kept_when_its_trust_policy_names_a_region_where_a_runtime_lives(kit, world):
    """The bucket in the other Region was deleted by hand; the role's own trust policy still says
    where it is used, and a runtime is found there."""
    deployed = world.deploy(WEST)
    del world.buckets[deployed["bucket"]]
    rc, lines = teardown(kit, world, EAST)
    assert rc == 1 and ROLE in world.roles
    assert "1 runtime(s) and 0 gateway(s) of this kit exist in Region us-west-2" in "\n".join(lines)


def test_B1_the_role_is_kept_when_the_region_its_trust_policy_names_cannot_be_checked(kit, world):
    deployed = world.deploy(WEST)
    del world.buckets[deployed["bucket"]]
    world.denied.add("list_agent_runtimes")
    script = load_script("90_teardown.py")
    lines: list[str] = []
    east = world.aws(EAST, lines)
    world.denied.clear()

    def west_denied(region):
        world.denied.add("list_agent_runtimes")
        return world.aws(region, lines)

    import os

    os.environ["AWS_REGION"] = EAST
    try:
        rc = script.main([], aws=east, out=lines.append, aws_for_region=west_denied)
    finally:
        os.environ.pop("AWS_REGION", None)
    assert rc == 1 and ROLE in world.roles
    assert "Region us-west-2 could not be checked for a runtime that uses the role" in "\n".join(lines)


@pytest.mark.parametrize("content", [b"", b'{"region": "us-west-2", "runtime_arn": "arn:aws:bedrock-agentcore:us-we',
                                      b"[1, 2, 3]", b"\xff\xfe\x00not text"])
def test_B1_a_damaged_state_file_is_never_moved_renamed_deleted_or_rewritten(kit, world, content):
    """C07 and C08: the first version set the damaged file aside and carried on in whatever
    Region the shell had, which destroyed the evidence and then deleted the bucket and role."""
    deployed = world.deploy(WEST)
    kit.STATE_PATH.write_bytes(content)
    folder_before = sorted(p.name for p in kit.STATE_PATH.parent.iterdir())

    rc, lines = teardown(kit, world, EAST)
    assert rc == kit.EXIT_STATE_MISMATCH
    assert lines[0].startswith("STOPPED:") and "could not be read" in lines[0]
    assert "python 90_teardown.py --region <Region> --prefix <prefix>" in "\n".join(lines)
    assert kit.STATE_PATH.read_bytes() == content
    assert sorted(p.name for p in kit.STATE_PATH.parent.iterdir()) == folder_before
    assert deployed["bucket"] in world.buckets and ROLE in world.roles and world.runtimes[WEST]

    rc, lines = verify(kit, world, EAST)   # sees the bucket and the role, as before teardown
    assert rc == 1 and result_of(lines).startswith("RESULT: NOT CLEAN")
    assert kit.STATE_PATH.read_bytes() == content


def test_B1_every_script_that_reads_state_stops_on_a_damaged_file_and_leaves_it(kit, world):
    kit.STATE_PATH.write_bytes(b'{"region": "us-west-2", "runtime_')
    before = kit.STATE_PATH.read_bytes()
    for name, argv in (("30_deploy.py", ["--i-understand-this-bills"]),
                       ("40_enable_observability.py", ["--i-understand-this-bills"]),
                       ("50_invoke_hosted.py", ["--i-understand-this-bills"]), ("60_read_usage.py", []),
                       ("optional_gateway/10_create_gateway.py", ["--i-understand-this-bills"]),
                       ("optional_gateway/50_call_gateway_tools.py", ["--i-understand-this-bills"]),
                       ("optional_gateway/90_teardown_gateway.py", [])):
        script = load_script(name)
        lines: list[str] = []
        if name == "30_deploy.py":
            kit.BUILD_DIR.mkdir(exist_ok=True)
            kit.PACKAGE_ZIP.write_bytes(b"zip")
            (kit.BUILD_DIR / "package_manifest.json").write_text(json.dumps(
                {"entry_point": ["agentcore_app.py"], "python_runtime": "PYTHON_3_13", "sha256": "x"}))
            script.MANIFEST = kit.BUILD_DIR / "package_manifest.json"
        rc = script.main(argv, aws=world.aws(EAST, lines), out=lines.append)
        assert rc == kit.EXIT_STATE_MISMATCH, (name, lines)
        assert any(line.startswith("STOPPED:") for line in lines), name
        assert kit.STATE_PATH.read_bytes() == before, name
    assert world.left() == [] and not any(op.startswith(("create", "put", "delete", "invoke"))
                                          for _, op in world.calls)


def test_B1_a_damaged_state_is_recovered_by_naming_the_place_and_the_file_stays_where_it_is(kit, world):
    world.deploy(WEST)
    damaged = b'{"region": "us-west-2", "prefix": "kitdemo", "runtime_'
    kit.STATE_PATH.write_bytes(damaged)
    assert teardown(kit, world, EAST, ["--region", WEST])[0] == 2          # both flags, or neither
    rc, lines = teardown(kit, world, EAST, ["--region", WEST, "--prefix", "kitdemo"])
    # Round 4: everything is deleted, and the exit code is 5 (INCOMPLETE), not 0. The file that
    # would say where else the kit was deployed could not be used, so this is no finished teardown.
    assert rc == kit.EXIT_INCOMPLETE and world.left() == [], "\n".join(lines)
    assert any(line.startswith("TEARDOWN INCOMPLETE") and "Exit code 5, not 0" in line for line in lines)
    assert not any("without errors" in line for line in lines)
    assert kit.STATE_PATH.read_bytes() == damaged
    assert any("works by name only" in line and "Region us-west-2" in line for line in lines)
    # the clean check finds nothing and still does not say CLEAN while the file is there
    rc, lines = verify(kit, world, WEST)
    assert rc == kit.EXIT_INCOMPLETE and result_of(lines).startswith("RESULT: INCOMPLETE")
    assert "move the file out of the kit folder yourself" in result_of(lines)
    kit.STATE_PATH.unlink()                                                 # the owner's own act
    rc, lines = verify(kit, world, WEST)
    assert rc == 0 and result_of(lines).startswith("RESULT: CLEAN")


def test_B1_a_file_set_aside_by_the_first_version_keeps_the_verdict_incomplete(kit, world):
    aside = kit.STATE_PATH.with_name(kit.STATE_PATH.name + ".damaged-20261007T080000Z-123")
    aside.write_bytes(b'{"region": "us-west-2", "runtime_')
    rc, lines = verify(kit, world, EAST)
    assert rc == kit.EXIT_INCOMPLETE and aside.name in result_of(lines)
    aside.unlink()
    write_state(kit, {"history": [], "damaged_state_set_aside": ["state.json.damaged-x"]})
    rc, lines = verify(kit, world, EAST)
    assert rc == kit.EXIT_INCOMPLETE and "state.json.damaged-x" in result_of(lines)


def test_B1_a_record_with_resource_ids_but_no_place_is_a_mismatch(kit, world):
    """C09c: the file has runtime_id but not the Region, prefix and account. The first version
    asked for the runtime in the wrong Region, was told "not found", and took that as proof."""
    deployed = world.deploy(WEST)
    record = {k: v for k, v in deployed.items() if k not in ("region", "prefix", "account_id")}
    write_state(kit, record)
    before = kit.STATE_PATH.read_bytes()
    rc, lines = teardown(kit, world, EAST)
    assert rc == kit.EXIT_STATE_MISMATCH and "names resources" in lines[0] and "does not record" in lines[0]
    assert world.runtimes[WEST] and deployed["bucket"] in world.buckets and ROLE in world.roles
    assert kit.STATE_PATH.read_bytes() == before
    rc, lines = verify(kit, world, EAST)
    assert rc != 0 and not result_of(lines).startswith("RESULT: CLEAN")
    assert kit.unusable_reason(kit.State(kit.STATE_PATH)) is not None
    # an account that can be read from an ARN is not "missing" (a file from before round 1)
    write_state(kit, {k: v for k, v in deployed.items() if k != "account_id"})
    assert kit.unusable_reason(kit.State(kit.STATE_PATH)) is None


# ====================================================================== MINOR 14: say when there is no record
def test_m14_the_result_line_says_in_plain_words_when_no_state_file_was_found(kit, world):
    rc, lines = verify(kit, world, EAST)
    assert rc == 0
    result = result_of(lines)
    assert "No state file was found on this machine" in result
    assert "It is not proof for any other Region, prefix or account." in result
    rc, lines = teardown(kit, world, EAST)
    assert rc == 0 and not kit.STATE_PATH.exists()       # a teardown that found nothing writes nothing
    assert any("No deploy was recorded in a usable state file, so this is not proof for any other Region"
               in line for line in lines)


def test_m14_a_teardown_without_a_record_is_remembered_so_the_note_does_not_disappear(kit, world):
    """C06b's second half: the wrong-Region teardown used to write a history entry, and the
    clean check then dropped its "no record" note."""
    world.deploy(EAST)
    assert teardown(kit, world, EAST)[0] == 0            # no state file, right Region: it works by name
    saved = json.loads(kit.STATE_PATH.read_text())
    assert saved["teardowns_without_a_record"][0]["region"] == EAST
    rc, lines = verify(kit, world, EAST)
    assert rc == 0 and "ran without a record of where this kit was deployed" in result_of(lines)
    assert "not proof for any Region, prefix or account not listed here" in result_of(lines)


def test_m14_a_recorded_deploy_torn_down_normally_gets_no_such_note(kit, world):
    write_state(kit, world.deploy(EAST))
    assert teardown(kit, world, EAST)[0] == 0
    rc, lines = verify(kit, world, EAST)
    assert rc == 0 and "No state file" not in result_of(lines) and "without a record" not in result_of(lines)
    # Round 4: the standing words are on every CLEAN line, as in kits A and B.
    assert "The places checked are the ones this machine's state file names" in result_of(lines)
    assert "not proof for any other Region, prefix or account" in result_of(lines)


# ====================================================================== MAJOR 7
@pytest.mark.parametrize("code", ["ValidationException", "AccessDeniedException", "InternalServerException"])
def test_M7_a_recorded_runtime_the_get_call_answers_with_another_error_keeps_its_record(kit, world, code):
    """C13: the runtime is not listed and GetAgentRuntime answers with an error other than "not
    found". Changed in review round 5 (F1): this test was named
    test_M7_teardown_finishes_when_the_get_call_reports_a_missing_runtime_with_another_error and
    asserted exit 0 with the record cleared, because the list call, which did not contain the id,
    decided. The listing is what cannot be trusted for a recorded runtime it does not show, so
    the record is kept and the exit code is 1; the same code could hide a runtime that exists."""
    deployed = world.deploy(EAST)
    del world.runtimes[EAST][deployed["runtime_id"]]
    write_state(kit, deployed)
    world.get_runtime_error = code
    rc, lines = teardown(kit, world, EAST)
    assert rc == 1, "\n".join(lines)
    assert not any("the list call does not contain it, so it does not exist" in line for line in lines)
    assert any(f"could not check runtime {deployed['runtime_id']}: {code}" in line
               and "not proof that it is gone, so .state.json keeps its record" in line for line in lines)
    assert json.loads(kit.STATE_PATH.read_text())["runtime_id"] == deployed["runtime_id"]
    assert lines[-2].startswith("Teardown finished WITH ERRORS")


def test_M7_a_runtime_that_the_list_call_still_shows_is_not_taken_for_gone(kit, world):
    deployed = world.deploy(EAST)
    write_state(kit, deployed)
    world.get_runtime_error = "ValidationException"
    world.denied.add("delete_agent_runtime")
    rc, lines = teardown(kit, world, EAST)
    assert rc == 1 and deployed["bucket"] in world.buckets and ROLE in world.roles
    assert json.loads(kit.STATE_PATH.read_text())["runtime_id"] == deployed["runtime_id"]


# ====================================================================== MINOR 8
def test_m8_teardown_exits_non_zero_when_the_tag_listing_shows_a_kit_resource_it_did_not_delete(kit, world):
    """C25: a deploy under another prefix in the same Region, state lost."""
    world.deploy(EAST, prefix="oldpfx")
    rc, lines = teardown(kit, world, EAST)
    text = "\n".join(lines)
    assert rc == 1 and len([item for item in world.left() if "oldpfx" in item]) == 4
    assert "Teardown finished, BUT 2 resource(s) of this kit remain" in text
    assert "Run: AWS_REGION=us-east-1 KIT_PREFIX=oldpfx python 90_teardown.py" in text
    rc, lines = verify(kit, world, EAST)
    assert rc == 1 and "KIT_PREFIX=oldpfx python 90_teardown.py" in "\n".join(lines)
    assert teardown(kit, world, EAST, prefix="oldpfx")[0] == 0 and world.left() == []


def test_m8_teardown_without_a_record_exits_non_zero_when_the_tag_listing_could_not_be_read(kit, world):
    """My own sequence O5: state lost, a deploy under another prefix, and tag:GetResources denied.
    Nothing is seen by name, the tag listing says nothing, so the run cannot say the kit is gone."""
    world.deploy(EAST, prefix="oldpfx")
    world.denied.add("get_resources")
    rc, lines = teardown(kit, world, EAST)
    text = "\n".join(lines)
    assert rc == 1 and len(world.left()) >= 4, text
    assert "Teardown finished without errors" not in text
    assert "could NOT look for resources of this kit under another name prefix" in text
    assert "exit code 1" in text and not kit.STATE_PATH.exists()


def test_m8_teardown_of_a_recorded_deploy_still_exits_zero_when_the_tag_listing_could_not_be_read(kit, world):
    """C15b: the record says where the kit is, so a failed tag listing is a note and not a failure."""
    write_state(kit, world.deploy(EAST))
    world.denied.add("get_resources")
    rc, lines = teardown(kit, world, EAST)
    assert rc == 0 and world.left() == [], "\n".join(lines)
    assert any(line.startswith("NOTE: ") and "tag lookup failed" in line for line in lines)
    world.denied.clear()
    assert verify(kit, world, EAST)[0] == 0


def test_m8_a_gateway_stuck_in_deleting_is_not_counted_as_gone(kit, world):
    """C14d."""
    deployed = world.deploy(EAST)
    deployed["gateway_id"] = world.add_gateway(EAST)
    write_state(kit, deployed)
    world.stuck_gateways = True
    rc, lines = teardown(kit, world, EAST)
    assert rc == 1 and world.gateways[EAST]
    assert any("is not confirmed gone" in line for line in lines)
    assert json.loads(kit.STATE_PATH.read_text())["gateway_id"] == deployed["gateway_id"]  # record kept
    assert ROLE in world.roles and deployed["bucket"] in world.buckets
    world.stuck_gateways = False
    world.gateways[EAST].clear()
    assert teardown(kit, world, EAST)[0] == 0 and world.left() == []


# ====================================================================== MINOR 9
def test_m9_a_teardown_dry_run_does_not_exit_zero(kit, world):
    write_state(kit, world.deploy(EAST))
    before = world.left()
    script = load_script("90_teardown.py")
    lines: list[str] = []
    rc = script.main(["--dry-run"], aws=kit.Aws(EAST, dry_run=True, out=lines.append), out=lines.append)
    assert rc == kit.EXIT_DRY_RUN_PROVES_NOTHING == 3 and world.left() == before
    assert any("a dry run tears nothing down" in line for line in lines)
    gateway = load_script("optional_gateway/90_teardown_gateway.py")
    assert gateway.main(["--dry-run"], aws=kit.Aws(EAST, dry_run=True, out=lines.append), out=lines.append) == 3


# ====================================================================== MINOR 11
def test_m11_a_denied_xray_call_does_not_decide_the_verdict(kit, world):
    """C15c."""
    write_state(kit, world.deploy(EAST))
    assert teardown(kit, world, EAST)[0] == 0
    world.denied.add("get_trace_segment_destination")
    rc, lines = verify(kit, world, EAST)
    assert rc == 0 and result_of(lines).startswith("RESULT: CLEAN")
    assert any("CloudWatch Transaction Search: could not be read (AccessDeniedException)" in line
               for line in lines)
    world.deploy(EAST)                                   # and it still fails when something is left
    assert verify(kit, world, EAST)[0] == 1


# ====================================================================== MINOR 12
def test_m12_a_versioned_code_bucket_is_emptied_and_deleted(kit, world):
    """C22."""
    deployed = world.deploy(EAST, versioned=True)
    world.buckets[deployed["bucket"]]["versions"].append(
        {"Key": "kitdemo_kitc_fr_agent/deployment_package.zip", "VersionId": "v2", "marker": False})
    write_state(kit, deployed)
    rc, lines = teardown(kit, world, EAST)
    assert rc == 0 and world.left() == [], "\n".join(lines)
    assert any("2 object version(s) and delete marker(s)" in line for line in lines)


def test_m12_an_unversioned_bucket_is_deleted_without_naming_the_null_version(kit, world):
    deployed = world.deploy(EAST)
    write_state(kit, deployed)
    sent = []
    original = world._handlers

    def spy(region):
        handlers = original(region)
        inner = handlers["delete_objects"]

        def delete_objects(**p):
            sent.append(p["Delete"]["Objects"])
            return inner(**p)
        handlers["delete_objects"] = delete_objects
        return handlers

    world._handlers = spy
    assert teardown(kit, world, EAST)[0] == 0 and world.left() == []
    assert sent == [[{"Key": "kitdemo_kitc_fr_agent/deployment_package.zip"}]]


# ====================================================================== the time rows (numbers review, M4)
def test_M4_teardown_prints_its_utc_times_and_the_hours_the_runtime_existed(kit, world, monkeypatch):
    import datetime as dt

    monkeypatch.setattr(kit, "utc_now", lambda: dt.datetime(2026, 10, 7, 12, 30, tzinfo=dt.timezone.utc))
    write_state(kit, world.deploy(EAST))
    rc, lines = teardown(kit, world, EAST)
    text = "\n".join(lines)
    assert rc == 0
    assert "started 2026-10-07T12:30:00Z (UTC)" in text and "Finished 2026-10-07T12:30:00Z (UTC)" in text
    assert "The runtime existed for 3.50 hours: from 2026-10-07T09:00:00Z" in text


def test_M4_the_result_line_of_the_clean_check_carries_its_utc_time_and_exit_code(kit, world, monkeypatch):
    import datetime as dt

    monkeypatch.setattr(kit, "utc_now", lambda: dt.datetime(2026, 10, 7, 12, 31, tzinfo=dt.timezone.utc))
    rc, lines = verify(kit, world, EAST)
    assert lines[-1].startswith("RESULT: CLEAN")
    assert lines[-1].endswith("Checked at 2026-10-07T12:31:00Z (UTC). Exit code 0.")
    world.deploy(EAST)
    rc, lines = verify(kit, world, EAST)
    assert lines[-1].startswith("RESULT: NOT CLEAN") and lines[-1].endswith("Exit code 1.")
