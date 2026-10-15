"""Tests added after the independent review of 2026-10-07 (round 1). One section per finding.

Ten tests for findings 1, 2 and 3 were written before the fixes (nine failed on the reviewed code; the
tenth needs the OpenAI SDK and was skipped on the system Python); two more were added later. Run in a
clean virtual environment against a scratch copy of the code as reviewed (with this file and conftest.py
dropped in), all 12 fail, and 66 of the 68 tests in this file fail; the two that pass there are controls
that must pass before and after.
The scenarios use the plain multi-Region fake in conftest.py (World), not botocore: what is tested here
is which Region and account a script acts in and what it does to the state file, not request shapes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import threading
import types

import pytest

import kitlib
import streamstats
from conftest import (ACCOUNT, KIT_DIR, OTHER_ACCOUNT, OTHER_REGION, REGION, FakeClock, Lines, World, deploy_into,
                      load_script, world_aws)


def config_for(**environ):
    return kitlib.load_config(environ=environ, env_file=KIT_DIR / "does-not-exist.env")


def ns(state_path, **overrides):
    values = dict(state_path=state_path, price_per_hour=None, max_hours=None, no_wait=False,
                  wait_timeout_minutes=45.0, i_understand_this_bills=False, skip_hf_check=True,
                  ignore_deadline=False, endpoint_name=None, keep_logs=False, allow_logs=False,
                  max_tag_lookups=300, minutes=30, log_minutes=None, logs_only=True, metrics_only=False,
                  all_logs=False, max_log_pages=5, mode="plain", prompt="x", max_tokens=5)
    values.update(overrides)
    return argparse.Namespace(**values)


# =====================================================================================================
# Finding 1 (BLOCKER): teardown and the clean check in the wrong Region or account
# =====================================================================================================

def test_f1_teardown_in_another_region_stops_and_leaves_the_record_alone(cfg, state_path, lines):
    """Deployed in us-east-1; a later shell has AWS_REGION=us-east-2. The reviewed code said "already absent",
    emptied the state file and exited 0 while the endpoint kept billing."""
    world = World()
    deploy_into(world, cfg, state_path)
    before = state_path.read_bytes()
    elsewhere = config_for(AWS_REGION=OTHER_REGION)
    clock = FakeClock()
    with pytest.raises(kitlib.KitError) as stop:
        load_script("90_teardown").run(ns(state_path), elsewhere, world_aws(world, OTHER_REGION), lines,
                                       sleep=clock.sleep, clock=clock)
    message = str(stop.value)
    assert REGION in message and OTHER_REGION in message, "the message must name both Regions"
    assert "AWS_REGION" in message and "config.env" in message
    assert state_path.read_bytes() == before, "the state file must not be rewritten"
    assert world.operations("delete_") == [], "nothing may be deleted in the wrong Region"
    assert cfg.endpoint_name in world.place(ACCOUNT, REGION)["endpoints"]
    assert "nothing of this kit was found" not in lines.text


def test_f1_teardown_in_another_account_stops_and_never_prints_a_full_account_id(cfg, state_path, lines, capsys):
    world = World()
    deploy_into(world, cfg, state_path)
    before = state_path.read_bytes()
    clock = FakeClock()
    with pytest.raises(kitlib.KitError) as stop:
        load_script("90_teardown").run(ns(state_path), cfg, world_aws(world, REGION, OTHER_ACCOUNT), lines,
                                       sleep=clock.sleep, clock=clock)
    message = str(stop.value)
    assert "ending 3333" in message and "ending 6666" in message, "both accounts, last four digits only"
    assert ACCOUNT not in message + lines.text and OTHER_ACCOUNT not in message + lines.text
    assert state_path.read_bytes() == before and world.operations("delete_") == []


def test_f1_teardown_with_another_prefix_stops(cfg, state_path, lines):
    world = World()
    deploy_into(world, cfg, state_path)
    before = state_path.read_bytes()
    clock = FakeClock()
    with pytest.raises(kitlib.KitError, match="prefix") as stop:
        load_script("90_teardown").run(ns(state_path), config_for(KIT_PREFIX="other"), world_aws(world), lines,
                                       sleep=clock.sleep, clock=clock)
    assert "kitdemo" in str(stop.value) and "other" in str(stop.value)
    assert state_path.read_bytes() == before and world.operations("delete_") == []


def test_f1_clean_check_in_another_region_is_not_clean(cfg, state_path, lines):
    """The reviewed code printed RESULT: CLEAN, exit 0, with the endpoint alive in the recorded Region."""
    world = World()
    deploy_into(world, cfg, state_path)
    elsewhere = config_for(AWS_REGION=OTHER_REGION)
    code = load_script("99_verify_clean").run(ns(state_path), elsewhere, world_aws(world, OTHER_REGION), lines)
    assert code != 0
    assert "RESULT: CLEAN" not in lines.text
    assert REGION in lines.text and cfg.endpoint_name in lines.text, "it must look where the state file points"


def test_f1_clean_check_is_incomplete_when_the_state_names_an_account_it_did_not_check(cfg, state_path, lines):
    world = World()
    deploy_into(world, cfg, state_path)
    code = load_script("99_verify_clean").run(ns(state_path), cfg, world_aws(world, REGION, OTHER_ACCOUNT), lines)
    assert code != 0 and "RESULT: INCOMPLETE" in lines.text and "RESULT: CLEAN" not in lines.text
    assert "ending 3333" in lines.text and "ending 6666" in lines.text
    assert ACCOUNT not in lines.text and OTHER_ACCOUNT not in lines.text


# =====================================================================================================
# Finding 2 (MAJOR): time to first token included connection setup on some recorded requests
# =====================================================================================================

class PooledSender:
    """Models a keep-alive connection pool. A request that finds no idle connection opens one and pays a
    handshake, which shows up in its time to first token. The first `level` requests of every run_level
    call are held in flight together (a barrier), as they are against a real endpoint."""

    HANDSHAKE_S, FIRST_TOKEN_S = 0.9, 0.1

    def __init__(self):
        self.lock = threading.Lock()
        self.idle = 0
        self.opened = 0
        self.level = 1
        self.sent_in_level = 0
        self.barrier = None

    def start_level(self, concurrency):
        self.level, self.sent_in_level = concurrency, 0
        self.barrier = threading.Barrier(concurrency, timeout=10)

    def send(self, index):
        with self.lock:
            position = self.sent_in_level
            self.sent_in_level += 1
            cold = self.idle == 0
            if cold:
                self.opened += 1
            else:
                self.idle -= 1
        if position < self.level and self.barrier is not None:
            self.barrier.wait()
        with self.lock:
            self.idle += 1
        ttft = self.FIRST_TOKEN_S + (self.HANDSHAKE_S if cold else 0.0)
        return streamstats.RequestResult(ok=True, error="", ttft_s=ttft, total_s=ttft + 0.5, output_tokens=10,
                                         tokens_source="usage", prompt_tokens=5, request_tokens_per_s=10.0,
                                         decode_tokens_per_s=18.0, text_chunks=10, finish_reason="length",
                                         saw_done=True)


class IdentityOnlyAws:
    """Enough of kitlib.Aws for 60_loadtest.run when the sender is a fake: answers the identity question."""

    dry_run = False
    calls_printed = 0
    region = REGION

    def call(self, service, operation, **params):
        assert (service, operation) == ("sts", "get_caller_identity"), (service, operation)
        return {"Account": ACCOUNT, "Arn": f"arn:aws:iam::{ACCOUNT}:user/example", "UserId": "AIDAEXAMPLE"}


def test_f2_no_recorded_request_pays_for_opening_its_connection(cfg, state_path, tmp_path, lines, monkeypatch):
    """Reviewed code: one warm-up request, so level 4 opened 3 new connections inside recorded requests and
    those three set the p95 of 8 (or of 32)."""
    module = load_script("60_loadtest")
    pool = PooledSender()
    real_run_level = module.run_level

    def run_level(send, concurrency, requests, clock=None):
        pool.start_level(concurrency)
        return real_run_level(send, concurrency, requests) if clock is None else real_run_level(send, concurrency, requests, clock)

    monkeypatch.setattr(module, "run_level", run_level)
    args = argparse.Namespace(state_path=state_path, results_dir=tmp_path / "results", concurrency="1,4",
                              requests_per_level=8, max_tokens=50, prompt="p", label="baseline", ignore_eos=False,
                              endpoint_name=None, ignore_deadline=False)
    code = module.run(args, cfg, IdentityOnlyAws(), lines, sender_factory=lambda *a, **k: pool.send)
    assert code == 0
    import csv
    requests_file = next(p for p in (tmp_path / "results").iterdir() if p.name.endswith("_requests.csv"))
    with requests_file.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 16, "8 recorded requests at each of two levels; warm-up requests are not recorded"
    cold = [row for row in rows if float(row["ttft_s"]) > PooledSender.FIRST_TOKEN_S + 0.01]
    assert cold == [], f"{len(cold)} recorded request(s) include a connection handshake in time to first token"
    summary_file = next(p for p in (tmp_path / "results").iterdir() if p.name.endswith("_summary.csv"))
    with summary_file.open(encoding="utf-8") as handle:
        summary = list(csv.DictReader(handle))
    # Round 2: a p95 of 8 requests is no longer given (fewer than 20); the maximum carries the point.
    assert [row["ttft_p95_s"] for row in summary] == ["", ""]
    assert [float(row["ttft_max_s"]) for row in summary] == [pytest.approx(0.1), pytest.approx(0.1)]
    assert pool.opened == 4, "one connection per worker of the widest level, all opened by warm-up requests"
    assert [row["warmup_requests"] for row in summary] == ["1", "4"], "the CSV says how many warm-up requests preceded each level"


class FakeOpenAISDK:
    """Stands in for the two extra packages of the openai mode. Records what the script asks of the SDK."""

    def __init__(self, clock, fail_with=None, token_error=None, chunks=None):
        self.clock, self.fail_with, self.token_error = clock, fail_with, token_error
        self.chunks = chunks
        self.creates = []
        self.token = "sagemaker-api-key-SECRET-TOKEN"
        sdk = self

        class Completions:
            def create(self, **params):
                sdk.creates.append(params)
                if sdk.fail_with is not None:
                    raise sdk.fail_with
                if not params.get("stream"):
                    sdk.clock.now += 5.0  # a slow first request: handshake plus a cold model
                    return types.SimpleNamespace(choices=[], usage=None)
                return iter(sdk.chunks if sdk.chunks is not None else sdk.default_chunks())

        class Client:
            def __init__(self, base_url, api_key):
                sdk.base_url, sdk.api_key = base_url, api_key
                self.chat = types.SimpleNamespace(completions=Completions())

        self.openai = types.ModuleType("openai")
        self.openai.OpenAI = Client
        self.token_generator = types.ModuleType("sagemaker.core.token_generator")

        def generate_token(region, expiry):
            if sdk.token_error is not None:
                raise sdk.token_error
            sdk.token_request = (region, expiry)
            return sdk.token

        self.token_generator.generate_token = generate_token

    @staticmethod
    def delta_chunk(content=None, usage=None, **extra):
        choices = [] if content is None and not extra else [
            types.SimpleNamespace(delta=types.SimpleNamespace(content=content, **extra), finish_reason=None)]
        return types.SimpleNamespace(choices=choices, usage=usage)

    def default_chunks(self):
        return [self.delta_chunk("Hel"), self.delta_chunk("lo"),
                self.delta_chunk(usage=types.SimpleNamespace(completion_tokens=2))]

    def install(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "openai", self.openai)
        for name in ("sagemaker", "sagemaker.core"):
            monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
        monkeypatch.setitem(sys.modules, "sagemaker.core.token_generator", self.token_generator)


def test_f2_openai_mode_times_a_request_on_a_warm_connection(cfg, lines, monkeypatch):
    """Reviewed code: the openai mode built a new client and timed its first request, so its time to first
    token included a handshake that the stream mode's did not."""
    module = load_script("50_invoke")
    clock = FakeClock(step=0.01)
    sdk = FakeOpenAISDK(clock)
    sdk.install(monkeypatch)
    assert module.invoke_openai(cfg, cfg.endpoint_name, "hi", 20, False, lines, clock) is True
    assert len(sdk.creates) == 2, "one warm-up request that is not timed, then the timed request"
    assert not sdk.creates[0].get("stream") and sdk.creates[0]["max_tokens"] == 1
    assert sdk.creates[1]["stream"] is True
    timed = next(line for line in lines if line.startswith("[openai] time to first token"))
    ttft = float(timed.split("time to first token ")[1].split(" s")[0])
    assert ttft < 1.0, f"the warm-up's 5 seconds leaked into the timed request: {timed}"
    assert sdk.token not in lines.text


# =====================================================================================================
# Finding 3 (MAJOR): an HTTP error on the OpenAI path crashed the error handler
# =====================================================================================================

class SDKStatusError(Exception):
    """Shaped like the OpenAI SDK's APIStatusError: .response is an HTTP response object, not a dict."""

    def __init__(self, message, status_code):
        super().__init__(message)
        self.status_code = status_code
        self.response = types.SimpleNamespace(status_code=status_code, text=message)  # no .get()


def test_f3_error_helpers_and_guarded_survive_an_exception_whose_response_is_not_a_dict(capsys):
    exc = SDKStatusError("Error code: 403 - not authorized to perform sagemaker:CallWithBearerToken", 403)
    assert kitlib.error_code(exc) == ""
    assert "403" in kitlib.error_message(exc)
    assert not kitlib.is_not_found(exc)

    def main():
        raise exc

    assert kitlib.guarded(main) == 1, "guarded must report the error, not raise AttributeError from its own handler"
    err = capsys.readouterr().err
    assert "403" in err and "CallWithBearerToken" in err and "99_verify_clean.py" in err


def test_f3_openai_mode_reports_an_http_error_and_the_run_still_prints_its_summary(cfg, state_path, lines, monkeypatch):
    module = load_script("50_invoke")
    clock = FakeClock(step=0.01)
    sdk = FakeOpenAISDK(clock, fail_with=SDKStatusError(
        "Error code: 403 - User is not authorized to perform: sagemaker:CallWithBearerToken", 403))
    sdk.install(monkeypatch)
    world = World()
    deploy_into(world, cfg, state_path)
    code = module.run(ns(state_path, mode="openai"), cfg, world_aws(world), lines, clock=clock)
    assert code == 1
    assert "[openai] FAILED" in lines.text and "403" in lines.text and "CallWithBearerToken" in lines.text
    assert "Invocation modes that worked: 0 of 1" in lines.text
    assert "BILLING:" in lines.text, "the billing banner must still be printed after a failed mode"
    assert sdk.token not in lines.text


def test_f3_real_openai_sdk_error_object_is_handled():
    """With the real SDK installed (it is in requirements.txt), build its own error type and pass it through."""
    import inspect

    openai = pytest.importorskip("openai")
    # The SDK names its HTTP library in the type of the error's response argument; use whichever it is.
    annotation = str(inspect.signature(openai.APIStatusError.__init__).parameters["response"].annotation)
    http = pytest.importorskip(annotation.strip("'\"").split(".")[0])
    response = http.Response(403, request=http.Request("POST", "https://example.invalid/openai/v1/chat/completions"),
                             json={"message": "not authorized"})
    exc = openai.PermissionDeniedError("Error code: 403 - not authorized", response=response, body=None)
    assert not isinstance(exc.response, dict), "the SDK's .response is an HTTP response object"
    assert kitlib.error_code(exc) == "" and "403" in kitlib.error_message(exc)
    assert kitlib.guarded(lambda: (_ for _ in ()).throw(exc)) == 1


# =====================================================================================================
# The shared rule: the state file records Region, prefix and account; every script that reads it
# compares all three and stops on a mismatch; teardown strikes only what it confirmed gone there.
# =====================================================================================================

def script_args(name, state_path, tmp_path):
    if name == "60_loadtest":
        return argparse.Namespace(state_path=state_path, results_dir=tmp_path / "results", concurrency="1",
                                  requests_per_level=2, max_tokens=5, prompt="p", label="x", ignore_eos=False,
                                  endpoint_name=None, ignore_deadline=False)
    return ns(state_path, set="SM_VLLM_MAX_NUM_SEQS=16", i_understand_this_bills=True)


def run_script(name, args, cfg, aws, out):
    module = load_script(name)
    clock = FakeClock()
    if name in ("10_deploy", "70_change_one_setting", "90_teardown"):
        return module.run(args, cfg, aws, out, sleep=clock.sleep, clock=clock)
    if name == "00_check":
        return module.run(args, cfg, aws, out, hf_fetch=lambda model_id: {"gated": False})
    return module.run(args, cfg, aws, out)


STATE_READERS = ["00_check", "10_deploy", "50_invoke", "55_observe", "60_loadtest", "70_change_one_setting", "90_teardown"]
CHANGING_CALLS = ("create_", "delete_", "invoke_")


@pytest.mark.parametrize("name", STATE_READERS)
@pytest.mark.parametrize("what", ["region", "account", "prefix"])
def test_rule_every_script_that_reads_state_stops_on_a_mismatch(name, what, cfg, state_path, tmp_path, lines):
    world = World()
    deploy_into(world, cfg, state_path)
    before = state_path.read_bytes()
    now_cfg, now_aws, recorded, current = {
        "region": (config_for(AWS_REGION=OTHER_REGION, INSTANCE_TYPE="ml.g6.2xlarge"), world_aws(world, OTHER_REGION),
                   REGION, OTHER_REGION),
        "account": (cfg, world_aws(world, REGION, OTHER_ACCOUNT), "ending 3333", "ending 6666"),
        "prefix": (config_for(KIT_PREFIX="other"), world_aws(world), "kitdemo", "other"),
    }[what]
    args = script_args(name, state_path, tmp_path)
    if name == "00_check" or name == "10_deploy":
        args.price_per_hour = 1.0  # so that the price lookup for another Region is not what stops the script
    with pytest.raises(kitlib.KitError) as stop:
        run_script(name, args, now_cfg, now_aws, lines)
    message = str(stop.value)
    assert recorded in message and current in message, f"both values must be named: {message}"
    assert "AWS_REGION" in message and "overrides config.env" in message
    assert ACCOUNT not in message + lines.text and OTHER_ACCOUNT not in message + lines.text
    assert state_path.read_bytes() == before, "the state file must not be rewritten"
    assert [op for op in world.operations() if op.split(":")[1].startswith(CHANGING_CALLS)] == []


@pytest.mark.parametrize("name", STATE_READERS)
def test_rule_matching_state_does_not_stop_the_script_at_the_comparison(name, cfg, state_path, tmp_path, lines):
    """The control for the test above: same scripts, same state, nothing changed. None may stop on a mismatch."""
    world = World()
    deploy_into(world, cfg, state_path)
    args = script_args(name, state_path, tmp_path)
    try:
        run_script(name, args, cfg, world_aws(world), lines)
    except kitlib.KitError as exc:
        assert "Mismatch" not in str(exc), str(exc)
    except Exception:  # noqa: BLE001 - the fake has no runtime, metrics or log clients; getting that far is the point
        pass
    assert "get_caller_identity" in " ".join(world.operations()), "the script must ask who it is signed in as"


def test_rule_a_dry_run_also_stops_on_a_region_or_prefix_mismatch_without_any_call(cfg, state_path, lines):
    world = World()
    deploy_into(world, cfg, state_path)
    aws = kitlib.Aws(OTHER_REGION, dry_run=True, out=lines)
    clock = FakeClock()
    with pytest.raises(kitlib.KitError, match="account not compared: no identity call was made"):
        load_script("90_teardown").run(ns(state_path), config_for(AWS_REGION=OTHER_REGION), aws, lines,
                                       sleep=clock.sleep, clock=clock)
    assert aws.calls_made == 0 and "delete_endpoint" not in lines.text


def test_rule_require_state_matches_unit(cfg):
    state = kitlib.empty_state(cfg, ACCOUNT)
    kitlib.require_state_matches(None, cfg, ACCOUNT)
    kitlib.require_state_matches(state, config_for(AWS_REGION=OTHER_REGION), OTHER_ACCOUNT)  # no live record: nothing to compare
    state["resources"] = [{"type": "model", "name": "m", "arn": None}]
    kitlib.require_state_matches(state, cfg, ACCOUNT)
    kitlib.require_state_matches(state, cfg, None)  # dry run: account not compared
    with pytest.raises(kitlib.KitError, match="Region: the file records us-east-1, this shell uses us-east-2"):
        kitlib.require_state_matches(state, config_for(AWS_REGION=OTHER_REGION), ACCOUNT)
    with pytest.raises(kitlib.KitError, match="account ending 3333, you are signed in to the account ending 6666"):
        kitlib.require_state_matches(state, cfg, OTHER_ACCOUNT)
    with pytest.raises(kitlib.KitError, match="the last four digits match, the full ids do not"):
        kitlib.require_state_matches(state, cfg, OTHER_ACCOUNT[:8] + ACCOUNT[-4:])
    # A file written by the reviewed copy of the kit has no account_id; it is read from a recorded ARN.
    older = {"kit": kitlib.KIT_NAME, "region": REGION, "prefix": "kitdemo", "deploy": None, "history": [],
             "resources": [{"type": "model", "name": "m", "arn": f"arn:aws:sagemaker:{REGION}:{ACCOUNT}:model/m"}]}
    assert kitlib.recorded_scope(older) == {"region": REGION, "prefix": "kitdemo", "account_id": ACCOUNT}
    kitlib.require_state_matches(older, cfg, ACCOUNT)
    with pytest.raises(kitlib.KitError):
        kitlib.require_state_matches(older, cfg, OTHER_ACCOUNT)
    older["resources"][0]["arn"] = None
    with pytest.raises(kitlib.KitError, match="records no account id"):
        kitlib.require_state_matches(older, cfg, ACCOUNT)
    # Top-level values agree with the shell, but one recorded ARN lives elsewhere (a hand-edited file): stop.
    edited = kitlib.empty_state(cfg, ACCOUNT)
    edited["resources"] = [{"type": "endpoint", "name": "e", "arn": f"arn:aws:sagemaker:{OTHER_REGION}:{ACCOUNT}:endpoint/e"}]
    with pytest.raises(kitlib.KitError, match="resource e: its recorded ARN is in Region us-east-2, account ending 3333"):
        kitlib.require_state_matches(edited, cfg, ACCOUNT)


def test_rule_deploy_records_region_prefix_and_account_and_prints_only_four_digits(cfg, state_path, lines):
    world = World()
    clock = FakeClock()
    code = load_script("10_deploy").run(ns(state_path, i_understand_this_bills=True), cfg, world_aws(world), lines,
                                        sleep=clock.sleep, clock=clock)
    assert code == 0
    state = kitlib.load_state(state_path)
    assert (state["region"], state["prefix"], state["account_id"]) == (REGION, "kitdemo", ACCOUNT)
    assert (state["deploy"]["region"], state["deploy"]["prefix"], state["deploy"]["account_id"]) == (REGION, "kitdemo", ACCOUNT)
    assert ACCOUNT not in lines.text and "account ending 3333" in lines.text


def test_rule_teardown_in_the_recorded_place_deletes_strikes_and_keeps_the_place_in_history(cfg, state_path, lines):
    world = World()
    deploy_into(world, cfg, state_path)
    world.place(ACCOUNT, REGION)["logs"].add(cfg.log_group_name)
    clock = FakeClock()
    assert load_script("90_teardown").run(ns(state_path), cfg, world_aws(world), lines, sleep=clock.sleep, clock=clock) == 0
    place = world.place(ACCOUNT, REGION)
    assert not place["endpoints"] and not place["configs"] and not place["models"] and not place["logs"]
    state = kitlib.load_state(state_path)
    assert state["resources"] == [] and state["deploy"] is None
    finished = state["history"][0]
    assert (finished["region"], finished["prefix"], finished["account_id"]) == (REGION, "kitdemo", ACCOUNT)
    assert finished["hours_is_upper_bound"] is False
    assert "nothing of this kit was found in Region us-east-1, account ending 3333, prefix kitdemo" in lines.text
    assert ACCOUNT not in lines.text


def test_rule_teardown_keeps_the_record_of_a_resource_that_is_still_listed(cfg, state_path, lines):
    """DeleteModel is accepted but the model is still listed afterwards: its record must stay."""
    world = World()
    deploy_into(world, cfg, state_path)
    aws = world_aws(world)
    aws.client("sagemaker").delete_model = lambda ModelName: {}  # accepted, nothing removed
    clock = FakeClock()
    assert load_script("90_teardown").run(ns(state_path), cfg, aws, lines, sleep=clock.sleep, clock=clock) == 1
    state = kitlib.load_state(state_path)
    assert [r["type"] for r in state["resources"]] == ["model"], "only the confirmed-gone records were struck"
    assert state["deploy"] is None and len(state["history"]) == 1, "the endpoint is confirmed gone, so the run is closed"
    assert "NOT CLEAN: 1 resource(s) remain" in lines.text and "still records 1 resource(s)" in lines.text


def test_rule_teardown_incomplete_leaves_the_state_file_untouched(cfg, state_path, lines, monkeypatch):
    world = World()
    deploy_into(world, cfg, state_path)
    before = state_path.read_bytes()
    monkeypatch.setattr(kitlib, "delete_stack", lambda *args, **kwargs: False)
    clock = FakeClock()
    assert load_script("90_teardown").run(ns(state_path), cfg, world_aws(world), lines, sleep=clock.sleep, clock=clock) == 1
    assert state_path.read_bytes() == before and "was not changed" in lines.text


def test_rule_clean_check_names_what_it_checked_and_sweeps_places_named_in_history(cfg, state_path, lines):
    world = World()
    state = kitlib.empty_state(cfg, ACCOUNT)
    state["history"] = [{"region": OTHER_REGION, "prefix": "older", "account_id": ACCOUNT, "hours": 1.0,
                         "estimated_usd": 1.2, "usd_per_hour": 1.2}]
    kitlib.save_state(state, state_path)
    module = load_script("99_verify_clean")
    assert module.run(ns(state_path), cfg, world_aws(world), lines) == 0
    result = next(line for line in lines if line.startswith("RESULT:"))
    assert result.startswith("RESULT: CLEAN. Checked account ending 3333, Region us-east-1, us-east-2, prefix kitdemo, older:")
    assert f"{OTHER_REGION}:list_endpoints" in world.operations() and f"{REGION}:list_endpoints" in world.operations()
    assert ACCOUNT not in lines.text

    # A log group left under the older prefix in the older Region is found (log groups carry no tags).
    world.place(ACCOUNT, OTHER_REGION)["logs"].add("/aws/sagemaker/Endpoints/older-kita-endpoint")
    again = Lines()
    assert module.run(ns(state_path), cfg, world_aws(world), again) == 1
    assert "RESULT: NOT CLEAN. Checked account ending 3333, Region us-east-1, us-east-2" in again.text
    assert "older-kita-endpoint" in again.text


def test_rule_clean_check_is_incomplete_when_history_names_another_account(cfg, state_path, lines):
    world = World()
    state = kitlib.empty_state(cfg, ACCOUNT)
    state["history"] = [{"region": REGION, "prefix": "kitdemo", "account_id": OTHER_ACCOUNT, "hours": 1.0}]
    kitlib.save_state(state, state_path)
    assert load_script("99_verify_clean").run(ns(state_path), cfg, world_aws(world), lines) == 1
    assert "RESULT: INCOMPLETE. Checked account ending 3333, Region us-east-1, prefix kitdemo" in lines.text
    assert "account ending 6666" in lines.text and "was NOT checked" in lines.text
    assert OTHER_ACCOUNT not in lines.text and "RESULT: CLEAN" not in lines.text


def test_rule_clean_check_is_incomplete_when_the_state_file_cannot_be_read(cfg, state_path, lines):
    state_path.write_text("{not json", encoding="utf-8")
    assert load_script("99_verify_clean").run(ns(state_path), cfg, world_aws(World()), lines) == 1
    assert "RESULT: INCOMPLETE" in lines.text and "cannot be used" in lines.text and "not valid JSON" in lines.text
    assert state_path.read_text(encoding="utf-8") == "{not json", "the damaged file is left as it is"


def test_rule_dry_run_of_the_clean_check_exits_3_and_says_why(capsys):
    module = load_script("99_verify_clean")
    assert kitlib.guarded(lambda: module.main(["--dry-run"])) == 3
    output = capsys.readouterr().out
    assert "NOTHING WAS CHECKED" in output and "Exit code 3" in output and "never exits 0" in output
    assert "RESULT:" not in output


def test_rule_a_new_deploy_after_a_finished_run_elsewhere_restamps_and_keeps_the_history(cfg, state_path, lines):
    world = World()
    older_cfg = config_for(KIT_PREFIX="older")
    state = kitlib.empty_state(older_cfg, OTHER_ACCOUNT)
    state["history"] = [{"hours": 1.0, "estimated_usd": 1.2, "usd_per_hour": 1.2}]  # an entry without its own place
    kitlib.save_state(state, state_path)
    clock = FakeClock()
    assert load_script("10_deploy").run(ns(state_path, i_understand_this_bills=True), cfg, world_aws(world), lines,
                                        sleep=clock.sleep, clock=clock) == 0
    after = kitlib.load_state(state_path)
    assert (after["region"], after["prefix"], after["account_id"]) == (REGION, "kitdemo", ACCOUNT)
    assert (after["history"][0]["prefix"], after["history"][0]["account_id"]) == ("older", OTHER_ACCOUNT)
    assert {"region": REGION, "prefix": "older", "account_id": OTHER_ACCOUNT} in kitlib.named_scopes(after)


def test_rule_real_boto3_without_credentials_stops_plainly_and_sends_nothing(capsys):
    """99_verify_clean.py through real boto3 with no credentials anywhere. The no_network fixture fails the
    test if a socket is opened; botocore refuses to sign before it would send."""
    module = load_script("99_verify_clean")
    assert kitlib.guarded(lambda: module.main([])) == 2
    captured = capsys.readouterr()
    assert "no usable AWS credentials" in captured.err and "RESULT:" not in captured.out


# =====================================================================================================
# MINOR findings
# =====================================================================================================

def test_f5_change_refuses_when_instance_model_image_or_ami_differ_from_the_deploy(cfg, state_path, lines):
    """Reviewed code: the new endpoint took the instance type from config and the price from the state file."""
    world = World()
    deploy_into(world, cfg, state_path)
    before = state_path.read_bytes()
    edited = config_for(INSTANCE_TYPE="ml.g5.2xlarge", INFERENCE_AMI_VERSION="")
    clock = FakeClock()
    with pytest.raises(kitlib.KitError) as stop:
        load_script("70_change_one_setting").run(
            ns(state_path, set="SM_VLLM_MAX_NUM_SEQS=16", i_understand_this_bills=True), edited, world_aws(world),
            lines, sleep=clock.sleep, clock=clock)
    message = str(stop.value)
    assert "INSTANCE_TYPE: deployed with ml.g6.2xlarge, config now says ml.g5.2xlarge" in message
    assert "INFERENCE_AMI_VERSION" in message and "HF_MODEL_ID" not in message
    assert state_path.read_bytes() == before
    assert [op for op in world.operations() if op.split(":")[1].startswith(CHANGING_CALLS)] == []


def test_f15_change_prints_the_price_with_its_source_page_and_date(cfg, state_path, lines):
    world = World()
    state = deploy_into(world, cfg, state_path)
    state["deploy"]["price_source"] = kitlib.PRICE_SOURCE
    kitlib.save_state(state, state_path)
    clock = FakeClock()
    assert load_script("70_change_one_setting").run(
        ns(state_path, set="SM_VLLM_MAX_NUM_SEQS=16", i_understand_this_bills=True), cfg, world_aws(world), lines,
        sleep=clock.sleep, clock=clock) == 0
    price_line = next(line for line in lines if line.startswith("PRICE:"))
    assert "$1.2220 per hour" in price_line and "pricing.us-east-1.amazonaws.com" in price_line and "read 2026-10-07" in price_line
    after = kitlib.load_state(state_path)
    assert after["deploy"]["price_source"] == kitlib.PRICE_SOURCE and after["deploy"]["instance_type"] == "ml.g6.2xlarge"
    variants = [c["ProductionVariants"][0]["InstanceType"] for c in world.place(ACCOUNT, REGION)["configs"].values()]
    assert variants == ["ml.g6.2xlarge"]


def sse(payload) -> bytes:
    import json
    return b"data: " + (payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")) + b"\n\n"


def content(text=None, reasoning=None, finish=None):
    delta = {}
    if text is not None:
        delta["content"] = text
    if reasoning is not None:
        delta["reasoning"] = reasoning
    return {"object": "chat.completion.chunk", "choices": [{"index": 0, "delta": delta, "finish_reason": finish}]}


USAGE5 = {"object": "chat.completion.chunk", "choices": [],
          "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25}}


def record(parts, end):
    recorder = streamstats.StreamRecorder(0.0)
    for at, data in parts:
        recorder.on_bytes(data, at)
    return recorder.result(end)


def test_f6_a_stream_that_just_stops_is_a_failed_request():
    truncated = record([(1.0, sse(content("A"))), (1.2, sse(content("B")))], end=1.2)
    assert not truncated.ok and "truncated" in truncated.error and truncated.output_tokens == 0
    assert record([(1.0, sse(content("A"))), (1.2, sse(content("B", finish="length")))], end=1.2).ok
    assert record([(1.0, sse(content("A"))), (1.2, sse(content("B"))), (1.2, sse(b"[DONE]"))], end=1.2).ok


def test_f7_decode_rate_does_not_count_tokens_that_arrived_with_the_first_one():
    """Three tokens in the first payload part at t=1, two more at t=2: 2 tokens in 1 second, not 4."""
    result = record([(1.0, sse(content("A")) + sse(content("B")) + sse(content("C"))),
                     (2.0, sse(content("D")) + sse(content("E", finish="length")) + sse(USAGE5) + sse(b"[DONE]"))], end=2.0)
    assert result.ok and result.output_tokens == 5
    assert result.decode_tokens_per_s == pytest.approx(2.0)
    one_at_a_time = record([(1.0, sse(content("A"))), (1.5, sse(content("B"))),
                            (2.0, sse(content("C", finish="stop")) + sse(b"[DONE]"))], end=2.0)
    assert one_at_a_time.decode_tokens_per_s == pytest.approx(2.0), "the usual case is unchanged: (3 - 1) / 1.0"


def test_f8_reasoning_text_is_flagged_on_the_request():
    plain = record([(1.0, sse(content("Hello"))), (1.1, sse(content("!", finish="stop")) + sse(b"[DONE]"))], end=1.1)
    assert plain.reasoning_seen is False
    field_reasoning = record([(0.5, sse(content(reasoning="hmm"))),
                              (2.0, sse(content("Answer", finish="stop")) + sse(b"[DONE]"))], end=2.0)
    assert field_reasoning.reasoning_seen is True and field_reasoning.ttft_s == pytest.approx(0.5)
    think_tag = record([(0.5, sse(content("<think>"))), (0.6, sse(content("hmm"))),
                        (2.0, sse(content("</think>Answer", finish="stop")) + sse(b"[DONE]"))], end=2.0)
    assert think_tag.reasoning_seen is True
    summary = streamstats.summarise_level("x", 1, [plain, field_reasoning, think_tag], 3.0, warmup_requests=1)
    assert summary.reasoning_requests == 2 and summary.warmup_requests == 1
    assert streamstats.request_row("x", 1, 0, think_tag)["reasoning_seen"] is True


def test_f8_loadtest_warns_at_the_warm_up_when_thinking_is_not_off(cfg, state_path, tmp_path, lines):
    module = load_script("60_loadtest")
    thinking = streamstats.RequestResult(ok=True, error="", ttft_s=0.2, total_s=1.0, output_tokens=10,
                                         tokens_source="usage", prompt_tokens=5, request_tokens_per_s=10.0,
                                         decode_tokens_per_s=11.0, text_chunks=10, finish_reason="length",
                                         saw_done=True, reasoning_seen=True)
    args = script_args("60_loadtest", state_path, tmp_path)
    assert module.run(args, cfg, IdentityOnlyAws(), lines, sender_factory=lambda *a, **k: (lambda index: thinking)) == 0
    assert lines.text.count("WARNING: the model sent reasoning text") == 2, "once at the warm-up, once in the summary"
    assert "2 recorded request(s) carried reasoning text" in lines.text


def test_f8_openai_mode_uses_the_same_first_token_definition_as_the_stream_mode(cfg, lines, monkeypatch):
    """Reviewed code: the openai mode timed the first delta.content only; the stream mode timed reasoning too."""
    module = load_script("50_invoke")
    clock = FakeClock(step=1.0)
    chunks = [FakeOpenAISDK.delta_chunk(None, reasoning="let me think"), FakeOpenAISDK.delta_chunk("Answer"),
              FakeOpenAISDK.delta_chunk(usage=types.SimpleNamespace(completion_tokens=4))]
    sdk = FakeOpenAISDK(clock, chunks=chunks)
    sdk.install(monkeypatch)
    written = []
    assert module.invoke_openai(cfg, cfg.endpoint_name, "hi", 20, False, lines, clock, written.append) is True
    assert written[0] == "let me think", "reasoning text is shown and timed, as in the stream mode"
    assert "WARNING: the model sent reasoning text" in lines.text
    assert module.openai_delta_text(types.SimpleNamespace(content="x")) == ("x", False)
    assert module.openai_delta_text(types.SimpleNamespace(content=None, reasoning_content="r")) == ("r", True)


def test_f9_create_endpoint_that_never_answers_leaves_an_unconfirmed_record_and_a_plain_stop(cfg, state_path, lines):
    """AWS created the endpoint; the client saw a read timeout. Reviewed code: no endpoint in the state file,
    no BILLING banner afterwards, and a bare traceback."""
    class ReadTimeoutError(Exception):
        pass

    world = World()
    clock = FakeClock()
    aws = world_aws(world, fail={"create_endpoint_after": ReadTimeoutError("Read timeout on endpoint URL")})
    with pytest.raises(kitlib.KitError, match="MAY exist and MAY be billing") as stop:
        load_script("10_deploy").run(ns(state_path, i_understand_this_bills=True), cfg, aws, lines,
                                     sleep=clock.sleep, clock=clock)
    assert "99_verify_clean.py" in str(stop.value) and "90_teardown.py" in str(stop.value)
    state = kitlib.load_state(state_path)
    assert [r["type"] for r in state["resources"]] == ["model", "endpoint_config", "endpoint"]
    assert state["deploy"]["endpoint_create_confirmed"] is False
    banner = "\n".join(kitlib.billing_lines(state, kitlib.utc_now()))
    assert "BILLING:" in banner and "UNCONFIRMED" in banner
    assert cfg.endpoint_name in world.place(ACCOUNT, REGION)["endpoints"]
    out = Lines()
    assert load_script("90_teardown").run(ns(state_path), cfg, world_aws(world), out, sleep=clock.sleep, clock=clock) == 0
    assert not world.place(ACCOUNT, REGION)["endpoints"] and kitlib.load_state(state_path)["resources"] == []


def test_f9_create_endpoint_rejected_by_aws_takes_the_record_back_out(cfg, state_path, lines):
    from conftest import FakeAwsError
    world = World()
    clock = FakeClock()
    aws = world_aws(world, fail={"create_endpoint": FakeAwsError("ResourceLimitExceeded", "quota is 0", 400)})
    with pytest.raises(FakeAwsError):
        load_script("10_deploy").run(ns(state_path, i_understand_this_bills=True), cfg, aws, lines,
                                     sleep=clock.sleep, clock=clock)
    state = kitlib.load_state(state_path)
    assert [r["type"] for r in state["resources"]] == ["model", "endpoint_config"] and state["deploy"] is None
    assert kitlib.billing_lines(state, kitlib.utc_now()) == []
    assert kitlib.definitely_rejected(FakeAwsError("X", "y", 400)) and not kitlib.definitely_rejected(FakeAwsError("X", "y", 500))
    assert not kitlib.definitely_rejected(TimeoutError("no answer"))


def test_f10_wait_endpoint_gone_does_not_take_an_unrelated_validation_error_for_gone(cfg, lines):
    """Reviewed code returned True (gone) for any ValidationException, with the endpoint still present."""
    from conftest import FakeAwsError
    world = World()
    world.place(ACCOUNT, REGION)["endpoints"][cfg.endpoint_name] = {"status": "Deleting"}
    odd = FakeAwsError("ValidationException", "1 validation error detected: Value at 'endpointName' failed to satisfy constraint")
    clock = FakeClock()
    with pytest.raises(FakeAwsError):
        kitlib.wait_endpoint_gone(world_aws(world, fail={"describe_endpoint": odd}), cfg.endpoint_name, lines,
                                  clock.sleep, clock)
    # Same odd answer, but ListEndpoints no longer returns the endpoint: gone, confirmed by the listing.
    del world.place(ACCOUNT, REGION)["endpoints"][cfg.endpoint_name]
    assert kitlib.wait_endpoint_gone(world_aws(world, fail={"describe_endpoint": odd}), cfg.endpoint_name, lines,
                                     clock.sleep, clock) is True
    assert "ListEndpoints no longer lists it" in lines.text
    assert kitlib.listed_by_name(world_aws(world), "endpoint", cfg.endpoint_name) is False


def test_f10_list_confirmation_request_is_valid_for_the_service_model(cfg, stubs):
    """NameContains on the three List calls, exactly as listed_by_name sends it, passes botocore's validation."""
    from conftest import endpoint_summary, config_summary, model_summary
    name = cfg.endpoint_name
    stubs["sagemaker"].add_response("list_endpoints", {"Endpoints": [endpoint_summary(name + "-2"), endpoint_summary(name)]},
                                    {"MaxResults": 100, "NameContains": name})
    stubs["sagemaker"].add_response("list_endpoint_configs", {"EndpointConfigs": [config_summary("x" + name)]},
                                    {"MaxResults": 100, "NameContains": name})
    stubs["sagemaker"].add_response("list_models", {"Models": [model_summary("other")]},
                                    {"MaxResults": 100, "NameContains": name})
    aws = stubs.aws()
    assert kitlib.listed_by_name(aws, "endpoint", name) is True
    assert kitlib.listed_by_name(aws, "endpoint_config", name) is False, "containing the name is not having the name"
    assert kitlib.listed_by_name(aws, "model", name) is False
    stubs.assert_all_used()


def test_f10_delete_treats_an_unrecognised_validation_error_as_absent_only_when_the_list_agrees(cfg, lines):
    from conftest import FakeAwsError
    odd = FakeAwsError("ValidationException", "Endpoint is not there any more")  # not the wording this kit knows
    world = World()
    clock = FakeClock()
    outcomes = {}
    aws = world_aws(world, fail={"delete_endpoint": odd})
    assert kitlib.delete_stack(aws, [cfg.endpoint_name], [], [], lines, clock.sleep, clock, outcomes=outcomes) is True
    assert outcomes == {f"endpoint:{cfg.endpoint_name}": "absent"}
    world.place(ACCOUNT, REGION)["endpoints"][cfg.endpoint_name] = {"status": "Deleting"}
    with pytest.raises(FakeAwsError):
        kitlib.delete_stack(aws, [cfg.endpoint_name], [], [], lines, clock.sleep, clock)


def test_f12_more_than_fifty_log_groups_are_all_read(cfg):
    world = World()
    for index in range(60):
        world.place(ACCOUNT, REGION)["logs"].add(f"/aws/sagemaker/Endpoints/{cfg.name_stem}x{index:03d}")
    found = kitlib.find_remaining(world_aws(world), cfg)
    assert len(found["log_groups"]) == 60
    assert world.operations("describe_log_groups") == [f"{REGION}:describe_log_groups"] * 2


def test_f12_log_group_paging_request_is_valid_for_the_service_model(cfg, stubs):
    prefix = f"/aws/sagemaker/Endpoints/{cfg.name_stem}"
    root = kitlib.LOG_GROUP_ROOT  # round 2: the whole path is listed, the kit's groups are picked out by name
    for operation, key in (("list_endpoints", "Endpoints"), ("list_endpoint_configs", "EndpointConfigs"), ("list_models", "Models")):
        stubs["sagemaker"].add_response(operation, {key: []}, {"MaxResults": 100})
    stubs["logs"].add_response("describe_log_groups", {"logGroups": [{"logGroupName": prefix + "a"}], "nextToken": "t1"},
                               {"logGroupNamePrefix": root, "limit": 50})
    stubs["logs"].add_response("describe_log_groups", {"logGroups": [{"logGroupName": prefix + "b"}]},
                               {"logGroupNamePrefix": root, "limit": 50, "nextToken": "t1"})
    assert [g["name"] for g in kitlib.find_remaining(stubs.aws(), cfg)["log_groups"]] == [prefix + "a", prefix + "b"]
    stubs.assert_all_used()


def test_f13_hours_are_an_upper_bound_when_the_endpoint_was_already_gone(cfg, state_path, lines):
    """The endpoint was deleted in the console an unknown time ago. Reviewed code printed the hours up to
    "now" as "Hours the endpoint(s) existed"."""
    world = World()
    deploy_into(world, cfg, state_path)
    del world.place(ACCOUNT, REGION)["endpoints"][cfg.endpoint_name]
    clock = FakeClock()
    assert load_script("90_teardown").run(ns(state_path), cfg, world_aws(world), lines, sleep=clock.sleep, clock=clock) == 0
    state = kitlib.load_state(state_path)
    assert state["history"][0]["hours_is_upper_bound"] is True and kitlib.totals_are_upper_bound(state)
    assert "AT MOST 1.00 h" in lines.text and "real end time is unknown" in lines.text
    assert "Hours the endpoint(s) existed, by this machine's clock" not in lines.text


def test_f18_missing_credentials_for_the_bearer_token_are_reported_not_raised(cfg, lines, monkeypatch, capsys):
    module = load_script("50_invoke")
    clock = FakeClock()
    sdk = FakeOpenAISDK(clock, token_error=RuntimeError("No AWS credentials found. Check your environment or credential provider."))
    sdk.install(monkeypatch)
    assert module.invoke_openai(cfg, cfg.endpoint_name, "hi", 20, False, lines, clock) is False
    assert "[openai] FAILED before any request" in lines.text and "No AWS credentials found" in lines.text
    assert sdk.creates == []

    def main():
        raise RuntimeError("something this kit did not expect")

    assert kitlib.guarded(main) == 1
    err = capsys.readouterr().err
    assert "STOP: unexpected RuntimeError: something this kit did not expect" in err and "99_verify_clean.py" in err


def test_f2_invoke_sends_one_untimed_warm_up_before_the_timed_boto3_calls(cfg, state_path, lines):
    import io
    import json

    class Runtime:
        dry_run = False
        calls_printed = 0

        def __init__(self):
            self.bodies = []

        def call(self, service, operation, **params):
            if service == "sts":
                return {"Account": ACCOUNT}
            self.bodies.append((operation, json.loads(params["Body"])))
            if operation == "invoke_endpoint":
                return {"Body": io.BytesIO(json.dumps({"choices": [{"message": {"content": "ok"}}], "usage": {}}).encode())}
            return {"Body": [{"PayloadPart": {"Bytes": sse(content("Hi", finish="stop")) + sse(b"[DONE]")}}]}

    module = load_script("50_invoke")
    for mode, expected in (("plain", ["invoke_endpoint", "invoke_endpoint"]),
                           ("stream", ["invoke_endpoint", "invoke_endpoint_with_response_stream"])):
        aws = Runtime()
        assert module.run(ns(state_path, mode=mode, prompt="real prompt", max_tokens=50), cfg, aws, Lines()) == 0
        assert [operation for operation, _ in aws.bodies] == expected
        assert aws.bodies[0][1]["max_tokens"] == 1 and aws.bodies[1][1]["max_tokens"] == 50


def test_f3_an_aws_error_in_one_boto3_mode_fails_that_mode_only(cfg, state_path, lines):
    """Finding 4's case seen from the script: an identity without sagemaker:InvokeEndpointWithResponseStream.
    The plain mode works, the stream mode says why it failed, and the summary and the banner still print."""
    import io
    import json
    from conftest import FakeAwsError

    class Runtime:
        dry_run = False
        calls_printed = 0

        def call(self, service, operation, **params):
            if service == "sts":
                return {"Account": ACCOUNT}
            if operation == "invoke_endpoint":
                return {"Body": io.BytesIO(json.dumps({"choices": [{"message": {"content": "ok"}}], "usage": {}}).encode())}
            raise FakeAwsError("AccessDeniedException", "not authorized to perform: sagemaker:InvokeEndpointWithResponseStream", 403)

    world = World()
    deploy_into(world, cfg, state_path)
    module = load_script("50_invoke")
    args = ns(state_path, mode="all", prompt="p", max_tokens=5)
    module.invoke_openai = lambda *a, **k: True  # the openai mode is covered by its own tests
    assert module.run(args, cfg, Runtime(), lines) == 1
    assert "[stream] FAILED: AWS returned AccessDeniedException" in lines.text
    assert "sagemaker:InvokeEndpointWithResponseStream" in lines.text
    assert "Invocation modes that worked: 2 of 3 (plain, openai)" in lines.text and "BILLING:" in lines.text
