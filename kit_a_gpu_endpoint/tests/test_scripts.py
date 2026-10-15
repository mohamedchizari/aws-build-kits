"""Offline tests for the numbered scripts: --help, --dry-run without credentials, the billing guard,
and each script's main path against stubbed AWS clients or plain fakes."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import threading

import pytest
from botocore.exceptions import ClientError

import kitlib
import streamstats
from conftest import (ACCOUNT, SCRIPT_NAMES, WHEN, FakeClock, Lines, add_empty_inventory, arn, config_summary,
                      describe_endpoint_response, endpoint_summary, load_script, model_summary, not_found,
                      queue_identity)
from test_kitlib import deployed_state, expected_variant
from test_streamstats import DONE, chunk, part

ROLE_ARN = "arn:aws:iam::111122223333:role/kitdemo-kita-sagemaker-execution"
TRUST = {"Version": "2012-10-17", "Statement": [
    {"Effect": "Allow", "Principal": {"Service": "sagemaker.amazonaws.com"}, "Action": "sts:AssumeRole"}]}

DRY_RUN_ARGS = {name: ["--dry-run"] for name in SCRIPT_NAMES}
DRY_RUN_ARGS["70_change_one_setting"] = ["--dry-run", "--set", "SM_VLLM_MAX_NUM_SEQS=16"]


def role_response(trust=TRUST):
    return {"Role": {"Path": "/", "RoleName": "kitdemo-kita-sagemaker-execution", "RoleId": "AROAEXAMPLEEXAMPLE1",
                     "Arn": ROLE_ARN, "CreateDate": WHEN, "AssumeRolePolicyDocument": json.dumps(trust)}}


def ns(state_path, **overrides):
    values = dict(state_path=state_path, price_per_hour=None, max_hours=None, no_wait=False,
                  wait_timeout_minutes=45.0, i_understand_this_bills=False, skip_hf_check=False,
                  ignore_deadline=False, endpoint_name=None, keep_logs=False, allow_logs=False,
                  max_tag_lookups=300)
    values.update(overrides)
    return argparse.Namespace(**values)


# ---------------------------------------------------------------- every script: --help and --dry-run

@pytest.mark.parametrize("name", SCRIPT_NAMES)
def test_help_works_without_credentials(name, capsys):
    module = load_script(name)
    with pytest.raises(SystemExit) as exit_info:
        module.main(["--help"])
    assert exit_info.value.code == 0
    assert "--dry-run" in capsys.readouterr().out


@pytest.mark.parametrize("name", SCRIPT_NAMES)
def test_dry_run_makes_no_aws_call_and_needs_no_credentials(name, capsys, monkeypatch, tmp_path):
    import boto3

    def forbidden(*args, **kwargs):
        raise AssertionError("a dry run built a boto3 client")

    monkeypatch.setattr(boto3, "client", forbidden)
    monkeypatch.setattr(boto3, "Session", forbidden)
    module = load_script(name)
    # For teardown and the proof script exit code 0 means "nothing remains", so their dry runs exit 3
    # (teardown since review round 2). Every other script exits 0.
    expected = 3 if name in ("90_teardown", "99_verify_clean") else 0
    assert kitlib.guarded(lambda: module.main(DRY_RUN_ARGS[name])) == expected
    output = capsys.readouterr().out
    assert "DRY" in output and "0 made" in output
    assert "would call sts.get_caller_identity" in output, "the identity call is part of what a real run does"
    assert not kitlib.STATE_FILE.exists(), "a dry run wrote the state file"
    assert not kitlib.RESULTS_DIR.exists(), "a dry run wrote results"


def test_dry_run_of_deploy_prints_the_price_and_all_three_create_calls(capsys):
    module = load_script("10_deploy")
    assert module.main(["--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "$1.2220 per hour" in output and "2026-10-07" in output
    for operation in ("service-quotas.get_service_quota", "iam.get_role", "sagemaker.create_model",
                      "sagemaker.create_endpoint_config", "sagemaker.create_endpoint", "sagemaker.describe_endpoint"):
        assert f"DRY-RUN would call {operation}" in output
    assert "al2023-ami-sagemaker-inference-gpu-4-1" in output and '"SM_VLLM_MODEL": "Qwen/Qwen3-4B"' in output


def test_dry_run_of_teardown_prints_deletes_in_the_safe_order(capsys):
    module = load_script("90_teardown")
    assert module.main(["--dry-run"]) == 3
    output = capsys.readouterr().out
    positions = [output.index(f"would call {op}") for op in (
        "sagemaker.delete_endpoint with", "sagemaker.describe_endpoint", "sagemaker.delete_endpoint_config",
        "sagemaker.delete_model", "logs.delete_log_group")]
    assert positions == sorted(positions)


# ---------------------------------------------------------------- 00_check

def queue_check_calls(stubs, cfg, quota=1.0, role=True, trust=TRUST):
    stubs["sts"].add_response("get_caller_identity", {
        "UserId": "AIDAEXAMPLE", "Account": "111122223333", "Arn": "arn:aws:iam::111122223333:user/example"})
    stubs["service-quotas"].add_response("get_service_quota", {"Quota": {"Value": quota}},
                                         {"ServiceCode": "sagemaker", "QuotaCode": "L-98BDE811"})
    if role:
        stubs["iam"].add_response("get_role", role_response(trust), {"RoleName": cfg.role_name})
    else:
        stubs["iam"].add_client_error("get_role", service_error_code="NoSuchEntity")
    add_empty_inventory(stubs, cfg)


def open_model(model_id):
    return {"id": model_id, "gated": False, "private": False, "cardData": {"license": "apache-2.0"}}


def test_check_passes_when_everything_is_ready(cfg, stubs, state_path, lines):
    module = load_script("00_check")
    queue_check_calls(stubs, cfg)
    assert module.run(ns(state_path), cfg, stubs.aws(), lines, hf_fetch=open_model) == 0
    stubs.assert_all_used()
    assert "0 FAIL" in lines.text and "Account ending 3333" in lines.text
    assert "111122223333" not in lines.text, "the full account id must not be printed"
    assert "is open on Hugging Face" in lines.text and "7.49 GiB" in lines.text


def test_check_fails_on_zero_quota_and_prints_the_request_command_without_filing_it(cfg, stubs, state_path, lines):
    module = load_script("00_check")
    queue_check_calls(stubs, cfg, quota=0.0)
    assert module.run(ns(state_path), cfg, stubs.aws(), lines, hf_fetch=open_model) == 1
    stubs.assert_all_used()  # no request_service_quota_increase was queued, so none was made
    assert "FAIL  Quota 'ml.g6.2xlarge for endpoint usage' (L-98BDE811) is 0" in lines.text
    assert "aws service-quotas request-service-quota-increase" in lines.text


def test_check_fails_when_the_role_is_missing_or_has_the_wrong_trust(cfg, stubs, state_path, lines):
    module = load_script("00_check")
    queue_check_calls(stubs, cfg, role=False)
    assert module.run(ns(state_path), cfg, stubs.aws(), lines, hf_fetch=open_model) == 1
    assert "does not exist" in lines.text

    second = Lines()
    from conftest import Stubs
    stubs2 = Stubs()
    wrong = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Principal": {"Service": "ec2.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
    queue_check_calls(stubs2, cfg, trust=wrong)
    assert module.run(ns(state_path), cfg, stubs2.aws(), second, hf_fetch=open_model) == 1
    assert "does not allow sagemaker.amazonaws.com" in second.text


def test_check_fails_on_a_gated_model(cfg, stubs, state_path, lines):
    module = load_script("00_check")
    queue_check_calls(stubs, cfg)
    gated = lambda model_id: {"id": model_id, "gated": "manual", "private": False}  # noqa: E731
    assert module.run(ns(state_path), cfg, stubs.aws(), lines, hf_fetch=gated) == 1
    assert "gated or private" in lines.text


def test_check_warns_about_leftovers(cfg, stubs, state_path, lines):
    module = load_script("00_check")
    stubs["sts"].add_response("get_caller_identity", {"UserId": "x", "Account": "111122223333",
                                                      "Arn": "arn:aws:iam::111122223333:root"})
    stubs["service-quotas"].add_response("get_service_quota", {"Quota": {"Value": 1.0}})
    stubs["iam"].add_response("get_role", role_response())
    add_empty_inventory(stubs, cfg, endpoints=[endpoint_summary(cfg.endpoint_name)])
    assert module.run(ns(state_path, skip_hf_check=True), cfg, stubs.aws(), lines) == 0
    assert "1 resource(s) from this kit already exist" in lines.text and "root user" in lines.text


def test_trust_policy_reader_accepts_dict_string_and_url_encoded_forms():
    module = load_script("00_check")
    import urllib.parse
    assert module.trust_allows_sagemaker(TRUST)
    assert module.trust_allows_sagemaker(json.dumps(TRUST))
    assert module.trust_allows_sagemaker(urllib.parse.quote(json.dumps(TRUST)))
    multi = {"Statement": {"Effect": "Allow", "Principal": {"Service": ["ec2.amazonaws.com", "sagemaker.amazonaws.com"]}}}
    assert module.trust_allows_sagemaker(multi)
    assert not module.trust_allows_sagemaker({"Statement": [{"Effect": "Deny", "Principal": {"Service": "sagemaker.amazonaws.com"}}]})
    assert not module.trust_allows_sagemaker("not json") and not module.trust_allows_sagemaker(None)


# ---------------------------------------------------------------- 10_deploy

def queue_deploy(stubs, cfg, statuses=("Creating", "InService"), reason=None, quota=1.0):
    queue_identity(stubs)
    stubs["service-quotas"].add_response("get_service_quota", {"Quota": {"Value": quota}})
    stubs["iam"].add_response("get_role", role_response(), {"RoleName": cfg.role_name})
    sm = stubs["sagemaker"]
    sm.add_response("create_model", {"ModelArn": arn("model", "m")})
    sm.add_response("create_endpoint_config", {"EndpointConfigArn": arn("endpoint-config", "c")})
    sm.add_response("create_endpoint", {"EndpointArn": arn("endpoint", cfg.endpoint_name)})
    for status in statuses:
        sm.add_response("describe_endpoint", describe_endpoint_response(
            cfg.endpoint_name, status, reason if status == "Failed" else None), {"EndpointName": cfg.endpoint_name})


def test_deploy_refuses_without_the_billing_flag_and_calls_nothing(cfg, stubs, state_path, lines):
    module = load_script("10_deploy")
    aws = stubs.aws()
    with pytest.raises(kitlib.KitError, match="--i-understand-this-bills"):
        module.run(ns(state_path), cfg, aws, lines)
    assert aws.calls_made == 0 and not state_path.exists()
    assert "PRICE: $1.2220 per hour" in lines.text, "the price must be shown even when the script refuses"


def test_deploy_main_refuses_without_the_flag(capsys):
    module = load_script("10_deploy")
    assert kitlib.guarded(lambda: module.main([])) == 2
    assert "--i-understand-this-bills" in capsys.readouterr().err


def test_deploy_happy_path(cfg, stubs, state_path, lines):
    module = load_script("10_deploy")
    queue_deploy(stubs, cfg)
    clock = FakeClock()
    result = module.run(ns(state_path, i_understand_this_bills=True, max_hours=2.0), cfg, stubs.aws(), lines,
                        sleep=clock.sleep, clock=clock)
    assert result == 0
    stubs.assert_all_used()
    state = kitlib.load_state(state_path)
    assert [r["type"] for r in state["resources"]] == ["model", "endpoint_config", "endpoint"]
    assert (state["region"], state["prefix"], state["account_id"]) == ("us-east-1", "kitdemo", ACCOUNT)
    deploy = state["deploy"]
    assert (deploy["region"], deploy["prefix"], deploy["account_id"]) == ("us-east-1", "kitdemo", ACCOUNT)
    assert deploy["endpoint_create_confirmed"] is True and "2026-10-07" in deploy["price_source"]
    assert ACCOUNT not in lines.text and "account ending 3333" in lines.text
    assert deploy["in_service_utc"] and deploy["usd_per_hour"] == 1.222
    assert deploy["aws_creation_time_utc"] == "2026-10-07T12:00:00Z"
    window = kitlib.parse_iso(deploy["deadline_utc"]) - kitlib.parse_iso(deploy["create_called_utc"])
    assert abs(window.total_seconds() - 7200) <= 2
    assert "THE ENDPOINT NOW EXISTS" in lines.text and "InService after" in lines.text and "BILLING:" in lines.text


def test_deploy_sends_the_variant_with_ami_health_timeout_and_one_instance(cfg, stubs, state_path, lines):
    module = load_script("10_deploy")
    queue_identity(stubs)
    stubs["service-quotas"].add_response("get_service_quota", {"Quota": {"Value": 1.0}})
    stubs["iam"].add_response("get_role", role_response())
    seen = {}

    def capture(params, **kwargs):
        seen[kwargs["event_name"].split(".")[-1]] = params

    client = stubs.clients["sagemaker"]
    client.meta.events.register("provide-client-params.sagemaker.*", capture)
    sm = stubs["sagemaker"]
    sm.add_response("create_model", {"ModelArn": arn("model", "m")})
    sm.add_response("create_endpoint_config", {"EndpointConfigArn": arn("endpoint-config", "c")})
    sm.add_response("create_endpoint", {"EndpointArn": arn("endpoint", cfg.endpoint_name)})
    assert module.run(ns(state_path, i_understand_this_bills=True, no_wait=True), cfg, stubs.aws(), lines) == 0
    model_name = seen["CreateModel"]["ModelName"]
    assert seen["CreateModel"]["ExecutionRoleArn"] == ROLE_ARN
    assert seen["CreateModel"]["PrimaryContainer"] == {"Image": cfg.image_uri, "Environment": cfg.container_env()}
    assert seen["CreateEndpointConfig"]["ProductionVariants"] == [expected_variant(cfg, model_name)]
    assert seen["CreateEndpoint"]["EndpointConfigName"] == seen["CreateEndpointConfig"]["EndpointConfigName"]
    for operation in ("CreateModel", "CreateEndpointConfig", "CreateEndpoint"):
        assert seen[operation]["Tags"] == cfg.tags()


def test_deploy_stops_before_creating_anything_when_quota_is_zero(cfg, stubs, state_path, lines):
    module = load_script("10_deploy")
    queue_identity(stubs)
    stubs["service-quotas"].add_response("get_service_quota", {"Quota": {"Value": 0.0}})
    with pytest.raises(kitlib.KitError, match="Quota"):
        module.run(ns(state_path, i_understand_this_bills=True), cfg, stubs.aws(), lines)
    stubs.assert_all_used()
    assert not state_path.exists()


def test_deploy_refuses_a_second_endpoint(cfg, stubs, state_path, lines):
    module = load_script("10_deploy")
    kitlib.save_state(deployed_state(cfg), state_path)
    queue_identity(stubs)
    aws = stubs.aws()
    with pytest.raises(kitlib.KitError, match="one endpoint at a time"):
        module.run(ns(state_path, i_understand_this_bills=True), cfg, aws, lines)
    assert aws.calls_made == 1, "only the identity question was asked; nothing was created"
    stubs.assert_all_used()


def test_deploy_reports_failure_and_tells_the_owner_to_tear_down(cfg, stubs, state_path, lines):
    module = load_script("10_deploy")
    queue_deploy(stubs, cfg, statuses=("Creating", "Failed"),
                 reason="The primary container did not pass the ping health check.")
    clock = FakeClock()
    result = module.run(ns(state_path, i_understand_this_bills=True), cfg, stubs.aws(), lines,
                        sleep=clock.sleep, clock=clock)
    assert result == 1
    assert "did not pass the ping health check" in lines.text and "90_teardown.py" in lines.text
    assert kitlib.state_resources(kitlib.load_state(state_path), "endpoint"), "a failed endpoint stays in state so teardown deletes it"


def test_deploy_refuses_a_region_with_no_price(stubs, state_path, lines):
    module = load_script("10_deploy")
    cfg = kitlib.load_config(environ={"AWS_REGION": "eu-west-1"}, env_file=state_path.parent / "none.env")
    with pytest.raises(kitlib.KitError, match="only read prices for us-east-1"):
        module.run(ns(state_path, i_understand_this_bills=True), cfg, stubs.aws(), lines)


# ---------------------------------------------------------------- fakes for the runtime calls

class FakeRuntimeAws:
    """Stands in for kitlib.Aws for sagemaker-runtime calls. Records calls, returns canned bodies."""

    dry_run = False
    calls_printed = 0

    def __init__(self, stream_factory=None, plain=None, fail_with=None, account=ACCOUNT):
        self.stream_factory = stream_factory
        self.plain = plain
        self.fail_with = fail_with
        self.account = account
        self.identity_calls = 0
        self.calls = []
        self._lock = threading.Lock()
        self.in_flight = 0
        self.max_in_flight = 0

    def call(self, service, operation, **params):
        if service == "sts":  # the identity question; kept out of .calls, which lists the runtime requests
            self.identity_calls += 1
            return {"UserId": "AIDAEXAMPLE", "Account": self.account, "Arn": f"arn:aws:iam::{self.account}:user/example"}
        with self._lock:
            self.calls.append((service, operation, params))
        if self.fail_with is not None:
            raise self.fail_with
        if operation == "invoke_endpoint":
            return {"Body": io.BytesIO(json.dumps(self.plain).encode("utf-8"))}
        return {"Body": self._tracked(self.stream_factory())}

    def _tracked(self, events):
        with self._lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            yield from events
        finally:
            with self._lock:
                self.in_flight -= 1


def token_stream(tokens=5):
    def factory():
        events = [part(chunk(role="assistant", content=""))]
        events += [part(chunk(content=f"t{i} ")) for i in range(tokens)]
        events.append(part(chunk(usage={"prompt_tokens": 12, "completion_tokens": tokens, "total_tokens": 12 + tokens},
                                 choices=False) + DONE))
        return events
    return factory


# ---------------------------------------------------------------- 50_invoke

def test_invoke_request_body_shapes(cfg):
    module = load_script("50_invoke")
    plain = module.chat_body(cfg, "hi", 50, stream=False)
    assert plain == {"model": "Qwen/Qwen3-4B", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 50,
                     "temperature": 0.7, "chat_template_kwargs": {"enable_thinking": False}}
    streamed = module.chat_body(cfg, "hi", 50, stream=True)
    assert streamed["stream"] is True and streamed["stream_options"] == {"include_usage": True}


def test_invoke_plain_and_stream(cfg, state_path, lines):
    module = load_script("50_invoke")
    plain = {"choices": [{"message": {"role": "assistant", "content": "Because the instance is reserved."}}],
             "usage": {"prompt_tokens": 20, "completion_tokens": 7, "total_tokens": 27}}
    aws = FakeRuntimeAws(stream_factory=token_stream(4), plain=plain)
    written = []
    clock = FakeClock(step=0.25)
    assert module.invoke_plain(aws, cfg, cfg.endpoint_name, "why?", 50, lines, clock) is True
    assert module.invoke_stream(aws, cfg, cfg.endpoint_name, "why?", 50, lines, clock, written.append) is True
    assert "Because the instance is reserved." in lines.text and "completion_tokens=7" in lines.text
    assert "time to first token" in lines.text and "4 output tokens (counted from: usage)" in lines.text
    assert "".join(written).strip() == "t0 t1 t2 t3"
    (_, op1, params1), (_, op2, params2) = aws.calls
    assert op1 == "invoke_endpoint" and op2 == "invoke_endpoint_with_response_stream"
    for params in (params1, params2):
        assert params["EndpointName"] == cfg.endpoint_name and params["ContentType"] == "application/json"
        assert json.loads(params["Body"])["messages"][0]["content"] == "why?"
    assert json.loads(params2["Body"])["stream"] is True


def test_invoke_runtime_requests_are_valid_for_the_service_model(cfg, stubs):
    """The two runtime requests, exactly as the scripts build them, pass botocore's validation."""
    module = load_script("50_invoke")
    body = json.dumps(module.chat_body(cfg, "hi", 10, stream=False)).encode("utf-8")
    expected = {"EndpointName": cfg.endpoint_name, "ContentType": "application/json", "Body": body}
    stubs["sagemaker-runtime"].add_response("invoke_endpoint", {"Body": io.BytesIO(b"{}")}, expected)
    stubs.aws().call("sagemaker-runtime", "invoke_endpoint", **expected)
    stubs["sagemaker-runtime"].add_response("invoke_endpoint_with_response_stream", {"Body": {}}, expected)
    stubs.aws().call("sagemaker-runtime", "invoke_endpoint_with_response_stream", **expected)
    stubs.assert_all_used()


def test_invoke_reports_an_unexpected_plain_response(cfg, lines):
    module = load_script("50_invoke")
    aws = FakeRuntimeAws(plain={"message": "no choices here"})
    assert module.invoke_plain(aws, cfg, cfg.endpoint_name, "x", 5, lines, FakeClock()) is False
    assert "Unexpected response shape" in lines.text


def test_invoke_refuses_past_the_deadline(cfg, state_path, lines):
    module = load_script("50_invoke")
    kitlib.save_state(deployed_state(cfg, created=kitlib.utc_now() - dt.timedelta(hours=5), hours=3.0), state_path)
    args = ns(state_path, mode="plain", prompt="x", max_tokens=5)
    aws = FakeRuntimeAws(plain={})
    with pytest.raises(kitlib.KitError, match="past the teardown time"):
        module.run(args, cfg, aws, lines)
    assert aws.calls == [] and "PAST YOUR DEADLINE" in lines.text
    assert aws.identity_calls == 1


def test_invoke_openai_dry_run_prints_the_url_and_no_token(cfg, lines):
    module = load_script("50_invoke")
    assert module.invoke_openai(cfg, cfg.endpoint_name, "x", 5, True, lines, FakeClock()) is True
    assert "https://runtime.sagemaker.us-east-1.amazonaws.com/endpoints/kitdemo-kita-endpoint/openai/v1/chat/completions" in lines.text
    assert "sagemaker-api-key" not in lines.text


# ---------------------------------------------------------------- 60_loadtest

def loadtest_args(state_path, results_dir, **overrides):
    values = dict(state_path=state_path, results_dir=results_dir, concurrency="1,4", requests_per_level=8,
                  max_tokens=50, prompt="p", label="baseline", ignore_eos=False, endpoint_name=None,
                  ignore_deadline=False)
    values.update(overrides)
    return argparse.Namespace(**values)


def test_parse_levels():
    module = load_script("60_loadtest")
    assert module.parse_levels("1,4,16") == [1, 4, 16] and module.parse_levels(" 2 , 8 ") == [2, 8]
    for bad in ("", "0", "1,x", "65", "-1"):
        with pytest.raises(kitlib.KitError):
            module.parse_levels(bad)


def test_loadtest_request_body(cfg):
    module = load_script("60_loadtest")
    body = module.request_body(cfg, "p", 200, ignore_eos=True)
    assert body["stream"] is True and body["stream_options"] == {"include_usage": True}
    assert body["max_tokens"] == 200 and body["ignore_eos"] is True and body["model"] == "Qwen/Qwen3-4B"
    assert "ignore_eos" not in module.request_body(cfg, "p", 200, ignore_eos=False)


def test_run_level_sends_exactly_n_requests_and_never_exceeds_the_concurrency():
    module = load_script("60_loadtest")
    lock = threading.Lock()
    state = {"now": 0, "peak": 0, "sent": []}
    gate = threading.Barrier(4, timeout=5)

    def send(index):
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
            state["sent"].append(index)
        if index < 4:
            gate.wait()  # the first four requests are in flight together, proving real concurrency
        with lock:
            state["now"] -= 1
        return streamstats.RequestResult(ok=True, error="", ttft_s=0.1, total_s=1.0, output_tokens=10,
                                         tokens_source="usage", prompt_tokens=1, request_tokens_per_s=10.0,
                                         decode_tokens_per_s=11.0, text_chunks=10, finish_reason="length", saw_done=True)

    results, wall = module.run_level(send, concurrency=4, requests=20)
    assert len(results) == 20 and sorted(state["sent"]) == list(range(20))
    assert state["peak"] == 4 and wall >= 0


def test_sender_measures_a_stream_and_turns_errors_into_failed_results(cfg):
    module = load_script("60_loadtest")
    aws = FakeRuntimeAws(stream_factory=token_stream(6))
    clock = FakeClock(step=0.1)
    result = module.make_sender(aws, cfg.endpoint_name, {"x": 1}, clock)(0)
    assert result.ok and result.output_tokens == 6 and result.tokens_source == "usage" and result.ttft_s > 0

    throttled = FakeRuntimeAws(fail_with=ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}}, "InvokeEndpointWithResponseStream"))
    failed = module.make_sender(throttled, cfg.endpoint_name, {"x": 1}, clock)(0)
    assert not failed.ok and failed.error == "ThrottlingException: Rate exceeded" and failed.output_tokens == 0


def test_loadtest_end_to_end_writes_both_csv_files(cfg, state_path, tmp_path, lines):
    module = load_script("60_loadtest")
    kitlib.save_state(deployed_state(cfg, created=kitlib.utc_now(), hours=3.0), state_path)
    aws = FakeRuntimeAws(stream_factory=token_stream(5))
    results_dir = tmp_path / "results"
    assert module.run(loadtest_args(state_path, results_dir), cfg, aws, lines) == 0
    assert len(aws.calls) == 1 + (1 + 8) + (4 + 8), "one warm-up, then per level: one warm-up per worker plus eight recorded"
    assert aws.max_in_flight <= 4
    files = sorted(p.name for p in results_dir.iterdir())
    assert len(files) == 2 and files[0].endswith("_requests.csv") and files[1].endswith("_summary.csv")
    with (results_dir / files[0]).open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 16 and list(rows[0].keys()) == streamstats.REQUEST_COLUMNS
    assert {row["concurrency"] for row in rows} == {"1", "4"} and all(row["ok"] == "True" for row in rows)
    assert all(row["output_tokens"] == "5" and row["tokens_source"] == "usage" for row in rows)
    with (results_dir / files[1]).open(encoding="utf-8") as handle:
        summary = list(csv.DictReader(handle))
    assert [row["concurrency"] for row in summary] == ["1", "4"]
    assert all(row["requests"] == "8" and row["errors"] == "0" and row["output_tokens_total"] == "40" for row in summary)
    assert [row["warmup_requests"] for row in summary] == ["1", "4"] and all(row["reasoning_requests"] == "0" for row in summary)
    assert all(float(row["aggregate_tokens_per_s"]) > 0 for row in summary)
    assert "TTFT p50 s" in lines.text and "BILLING:" in lines.text


def test_loadtest_counts_failed_requests_and_exits_non_zero(cfg, state_path, tmp_path, lines):
    module = load_script("60_loadtest")
    counter = {"n": 0}

    def flaky():
        counter["n"] += 1
        if counter["n"] % 3 == 0:
            return [part(chunk(content="a")), {"ModelStreamError": {"ErrorCode": "X", "Message": "died"}}]
        return token_stream(3)()

    aws = FakeRuntimeAws(stream_factory=flaky)
    results_dir = tmp_path / "results"
    assert module.run(loadtest_args(state_path, results_dir, concurrency="1", requests_per_level=6), cfg, aws, lines) == 1
    summary_file = next(p for p in results_dir.iterdir() if p.name.endswith("_summary.csv"))
    with summary_file.open(encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert row["requests"] == "6" and row["errors"] == "2" and row["ok"] == "4" and row["output_tokens_total"] == "12"
    assert "First error: ModelStreamError" in lines.text


def test_loadtest_sends_nothing_more_when_the_warm_up_fails(cfg, state_path, tmp_path, lines):
    module = load_script("60_loadtest")
    aws = FakeRuntimeAws(fail_with=ClientError({"Error": {"Code": "ValidationError", "Message": "Endpoint not found"}}, "Op"))
    with pytest.raises(kitlib.KitError, match="warm-up request failed"):
        module.run(loadtest_args(state_path, tmp_path / "results"), cfg, aws, lines)
    assert len(aws.calls) == 1 and not (tmp_path / "results").exists()


def test_loadtest_refuses_past_the_deadline_and_bad_labels(cfg, state_path, tmp_path, lines):
    module = load_script("60_loadtest")
    with pytest.raises(kitlib.KitError, match="--label"):
        module.run(loadtest_args(state_path, tmp_path / "r", label="../etc"), cfg, FakeRuntimeAws(), lines)
    kitlib.save_state(deployed_state(cfg, created=kitlib.utc_now() - dt.timedelta(hours=5), hours=3.0), state_path)
    aws = FakeRuntimeAws(stream_factory=token_stream(2))
    with pytest.raises(kitlib.KitError, match="past the teardown time"):
        module.run(loadtest_args(state_path, tmp_path / "r"), cfg, aws, lines)
    assert aws.calls == []


# ---------------------------------------------------------------- 70_change_one_setting

def test_parse_setting_accepts_only_the_three_settings_with_sane_values():
    module = load_script("70_change_one_setting")
    assert module.parse_setting("SM_VLLM_MAX_NUM_SEQS=16") == ("SM_VLLM_MAX_NUM_SEQS", "16")
    assert module.parse_setting("SM_VLLM_GPU_MEMORY_UTILIZATION=0.8") == ("SM_VLLM_GPU_MEMORY_UTILIZATION", "0.8")
    assert module.parse_setting(" SM_VLLM_MAX_MODEL_LEN = 4096 ") == ("SM_VLLM_MAX_MODEL_LEN", "4096")
    for bad in ("SM_VLLM_MODEL=other/model", "SM_VLLM_MAX_NUM_SEQS", "SM_VLLM_MAX_NUM_SEQS=", "SM_VLLM_MAX_NUM_SEQS=0",
                "SM_VLLM_MAX_NUM_SEQS=many", "SM_VLLM_GPU_MEMORY_UTILIZATION=1.2", "SM_VLLM_MAX_MODEL_LEN=100",
                "HF_TOKEN=x"):
        with pytest.raises(kitlib.KitError):
            module.parse_setting(bad)


def test_change_one_setting_recreates_with_exactly_one_difference(cfg, stubs, state_path, lines):
    module = load_script("70_change_one_setting")
    before = deployed_state(cfg, created=kitlib.utc_now() - dt.timedelta(hours=1), hours=3.0)
    kitlib.save_state(before, state_path)
    old_model, old_config = cfg.model_name("r1"), cfg.endpoint_config_name("r1")
    seen = {}
    stubs.clients["sagemaker"].meta.events.register(
        "provide-client-params.sagemaker.*", lambda params, **kw: seen.setdefault(kw["event_name"].split(".")[-1], params))
    queue_identity(stubs)
    stubs["iam"].add_response("get_role", role_response())
    sm = stubs["sagemaker"]
    sm.add_response("delete_endpoint", {}, {"EndpointName": cfg.endpoint_name})
    not_found(stubs, "sagemaker", "describe_endpoint", "endpoint")
    sm.add_response("delete_endpoint_config", {}, {"EndpointConfigName": old_config})
    sm.add_response("delete_model", {}, {"ModelName": old_model})
    sm.add_response("create_model", {"ModelArn": arn("model", "new")})
    sm.add_response("create_endpoint_config", {"EndpointConfigArn": arn("endpoint-config", "new")})
    sm.add_response("create_endpoint", {"EndpointArn": arn("endpoint", cfg.endpoint_name)})
    sm.add_response("describe_endpoint", describe_endpoint_response(cfg.endpoint_name, "InService"))
    clock = FakeClock()
    args = ns(state_path, set="SM_VLLM_MAX_NUM_SEQS=16", i_understand_this_bills=True)
    assert module.run(args, cfg, stubs.aws(), lines, sleep=clock.sleep, clock=clock) == 0
    stubs.assert_all_used()

    new_env = seen["CreateModel"]["PrimaryContainer"]["Environment"]
    old_env = before["deploy"]["env"]
    assert {k for k in new_env if new_env[k] != old_env.get(k)} == {"SM_VLLM_MAX_NUM_SEQS"}
    assert new_env["SM_VLLM_MAX_NUM_SEQS"] == "16" and set(new_env) == set(old_env)

    after = kitlib.load_state(state_path)
    assert after["deploy"]["env"]["SM_VLLM_MAX_NUM_SEQS"] == "16"
    assert after["deploy"]["deadline_utc"] == before["deploy"]["deadline_utc"], "the deadline is not extended"
    assert len(after["history"]) == 1 and after["history"][0]["hours"] == pytest.approx(1.0, abs=0.01)
    assert after["changes"][0]["setting"] == "SM_VLLM_MAX_NUM_SEQS" and after["changes"][0]["to"] == "16"
    assert len(after["resources"]) == 3


def test_change_refuses_without_flag_without_deploy_and_without_a_real_change(cfg, stubs, state_path, lines):
    module = load_script("70_change_one_setting")
    with pytest.raises(kitlib.KitError, match="No deployed endpoint"):
        module.run(ns(state_path, set="SM_VLLM_MAX_NUM_SEQS=16", i_understand_this_bills=True), cfg, stubs.aws(), lines)
    kitlib.save_state(deployed_state(cfg, created=kitlib.utc_now(), hours=3.0), state_path)
    aws = stubs.aws()
    with pytest.raises(kitlib.KitError, match="--i-understand-this-bills"):
        module.run(ns(state_path, set="SM_VLLM_MAX_NUM_SEQS=16"), cfg, aws, lines)
    assert "PRICE: the new endpoint costs $1.2220 per hour" in lines.text, "the price is shown even when the script refuses"
    assert "read 2026-10-07" in lines.text
    with pytest.raises(kitlib.KitError, match="already 4"):
        module.run(ns(state_path, set="SM_VLLM_MAX_NUM_SEQS=4", i_understand_this_bills=True), cfg, aws, lines)
    assert aws.calls_made == 0, "a refusal asks AWS nothing, not even who you are"


def test_change_creates_nothing_when_the_old_endpoint_will_not_go_away(cfg, stubs, state_path, lines, monkeypatch):
    module = load_script("70_change_one_setting")
    kitlib.save_state(deployed_state(cfg, created=kitlib.utc_now(), hours=3.0), state_path)
    monkeypatch.setattr(kitlib, "delete_stack", lambda *args, **kwargs: False)
    queue_identity(stubs)
    stubs["iam"].add_response("get_role", role_response())
    with pytest.raises(kitlib.KitError, match="still there"):
        module.run(ns(state_path, set="SM_VLLM_MAX_NUM_SEQS=16", i_understand_this_bills=True), cfg, stubs.aws(), lines)
    stubs.assert_all_used()  # no create call was queued, so none was made
    assert kitlib.state_resources(kitlib.load_state(state_path), "endpoint")


# ---------------------------------------------------------------- 90_teardown and 99_verify_clean

def queue_teardown(stubs, cfg, model, config):
    sm = stubs["sagemaker"]
    queue_identity(stubs)
    add_empty_inventory(stubs, cfg, endpoints=[endpoint_summary(cfg.endpoint_name)],
                        configs=[config_summary(config)], models=[model_summary(model)],
                        log_groups=[cfg.log_group_name])
    sm.add_response("delete_endpoint", {}, {"EndpointName": cfg.endpoint_name})
    sm.add_response("describe_endpoint", describe_endpoint_response(cfg.endpoint_name, "Deleting"))
    not_found(stubs, "sagemaker", "describe_endpoint", "endpoint")
    sm.add_response("delete_endpoint_config", {}, {"EndpointConfigName": config})
    sm.add_response("delete_model", {}, {"ModelName": model})
    stubs["logs"].add_response("delete_log_group", {}, {"logGroupName": cfg.log_group_name})
    add_empty_inventory(stubs, cfg)


def test_teardown_deletes_all_three_and_the_log_group_then_verifies(cfg, stubs, state_path, lines):
    module = load_script("90_teardown")
    kitlib.save_state(deployed_state(cfg, created=kitlib.utc_now() - dt.timedelta(hours=2), price=1.222), state_path)
    queue_teardown(stubs, cfg, cfg.model_name("r1"), cfg.endpoint_config_name("r1"))
    clock = FakeClock()
    assert module.run(ns(state_path), cfg, stubs.aws(), lines, sleep=clock.sleep, clock=clock) == 0
    stubs.assert_all_used()
    state = kitlib.load_state(state_path)
    assert state["resources"] == [] and state["deploy"] is None
    assert state["history"][0]["hours"] == pytest.approx(2.0, abs=0.01)
    assert "2.00 h" in lines.text and "$2.44" in lines.text and "nothing of this kit was found" in lines.text


def test_teardown_works_without_a_state_file(cfg, stubs, state_path, lines):
    module = load_script("90_teardown")
    assert not state_path.exists()
    queue_teardown(stubs, cfg, cfg.model_name("lost"), cfg.endpoint_config_name("lost"))
    clock = FakeClock()
    assert module.run(ns(state_path), cfg, stubs.aws(), lines, sleep=clock.sleep, clock=clock) == 0
    stubs.assert_all_used()


def test_teardown_reports_incomplete_when_the_endpoint_stays(cfg, stubs, state_path, lines, monkeypatch):
    module = load_script("90_teardown")
    kitlib.save_state(deployed_state(cfg, created=kitlib.utc_now()), state_path)
    queue_identity(stubs)
    add_empty_inventory(stubs, cfg, endpoints=[endpoint_summary(cfg.endpoint_name, "Deleting")])
    monkeypatch.setattr(kitlib, "delete_stack", lambda *args, **kwargs: False)
    clock = FakeClock()
    assert module.run(ns(state_path), cfg, stubs.aws(), lines, sleep=clock.sleep, clock=clock) == 1
    assert "TEARDOWN INCOMPLETE" in lines.text
    assert kitlib.state_resources(kitlib.load_state(state_path), "endpoint"), "state still records the endpoint"


def test_teardown_exits_non_zero_when_something_is_still_listed_afterwards(cfg, stubs, state_path, lines):
    module = load_script("90_teardown")
    sm = stubs["sagemaker"]
    queue_identity(stubs)
    add_empty_inventory(stubs, cfg, models=[model_summary(cfg.model_name("x"))])
    sm.add_response("delete_model", {}, {"ModelName": cfg.model_name("x")})
    add_empty_inventory(stubs, cfg, models=[model_summary(cfg.model_name("x"))])  # still listed
    clock = FakeClock()
    assert module.run(ns(state_path), cfg, stubs.aws(), lines, sleep=clock.sleep, clock=clock) == 1
    assert "NOT CLEAN: 1 resource(s) remain" in lines.text


def test_teardown_keep_logs_leaves_the_log_group_and_does_not_count_it(cfg, stubs, state_path, lines):
    module = load_script("90_teardown")
    queue_identity(stubs)
    add_empty_inventory(stubs, cfg, log_groups=[cfg.log_group_name])
    add_empty_inventory(stubs, cfg, log_groups=[cfg.log_group_name])
    clock = FakeClock()
    assert module.run(ns(state_path, keep_logs=True), cfg, stubs.aws(), lines, sleep=clock.sleep, clock=clock) == 0
    stubs.assert_all_used()  # no delete_log_group was queued, so none was made


def test_verify_clean_exit_codes(cfg, state_path):
    module = load_script("99_verify_clean")
    from conftest import Stubs

    def verify(inventory, **overrides):
        stubs = Stubs()
        queue_identity(stubs)
        add_empty_inventory(stubs, cfg, **inventory)
        out = Lines()
        code = module.run(ns(state_path, **overrides), cfg, stubs.aws(), out)
        stubs.assert_all_used()
        return code, out.text

    code, text = verify({})
    # There is no state file in this test, and since review round 2 the RESULT line says so.
    assert code == 0 and "RESULT: CLEAN ONLY WHERE CHECKED. NO USABLE STATE FILE WAS FOUND" in text
    assert "Only account ending 3333, Region us-east-1, prefix kitdemo were checked: 0 endpoints" in text
    assert ACCOUNT not in text, "the full account id must not be printed"
    code, text = verify({"endpoints": [endpoint_summary(cfg.endpoint_name)]})
    assert code == 1 and "hourly charge is still running" in text and cfg.endpoint_name in text
    code, text = verify({"configs": [config_summary(cfg.endpoint_config_name("r"))]})
    assert code == 1 and "hourly charge has stopped" in text
    code, text = verify({"models": [model_summary(cfg.model_name("r"))]})
    assert code == 1
    code, text = verify({"log_groups": [cfg.log_group_name]})
    assert code == 1 and "CloudWatch log groups: 1" in text
    code, text = verify({"log_groups": [cfg.log_group_name]}, allow_logs=True)
    assert code == 0 and "LOGS KEPT: 1 CloudWatch log group(s)" in text and cfg.log_group_name in text


def test_verify_clean_finds_a_tagged_endpoint_with_a_different_name_and_ignores_strangers(cfg, stubs, state_path, lines):
    module = load_script("99_verify_clean")
    sm = stubs["sagemaker"]
    queue_identity(stubs)
    sm.add_response("list_endpoints", {"Endpoints": [endpoint_summary("old-prefix-kita-endpoint"), endpoint_summary("unrelated")]})
    sm.add_response("list_tags", {"Tags": cfg.tags()})
    sm.add_response("list_tags", {"Tags": []})
    sm.add_response("list_endpoint_configs", {"EndpointConfigs": []})
    sm.add_response("list_models", {"Models": []})
    stubs["logs"].add_response("describe_log_groups", {"logGroups": []})
    assert module.run(ns(state_path), cfg, stubs.aws(), lines) == 1
    assert "old-prefix-kita-endpoint (matched by tags" in lines.text
    assert "not this kit's (not counted): 1" in lines.text


def test_verify_clean_does_not_trust_the_state_file(cfg, stubs, state_path, lines):
    module = load_script("99_verify_clean")
    kitlib.save_state(kitlib.empty_state(cfg, ACCOUNT), state_path)  # state says: nothing exists
    queue_identity(stubs)
    add_empty_inventory(stubs, cfg, endpoints=[endpoint_summary(cfg.endpoint_name)])  # AWS says: one endpoint
    assert module.run(ns(state_path), cfg, stubs.aws(), lines) == 1

    from conftest import Stubs
    stubs2, out2 = Stubs(), Lines()
    kitlib.save_state(deployed_state(cfg), state_path)  # state says: three resources
    queue_identity(stubs2)
    add_empty_inventory(stubs2, cfg)                     # AWS says: nothing
    assert module.run(ns(state_path), cfg, stubs2.aws(), out2) == 0
    assert "stale" in out2.text


def test_verify_clean_incomplete_is_not_clean(cfg, stubs, state_path, lines):
    module = load_script("99_verify_clean")
    sm = stubs["sagemaker"]
    queue_identity(stubs)
    sm.add_response("list_endpoints", {"Endpoints": [endpoint_summary("a"), endpoint_summary("b")]})
    sm.add_response("list_tags", {"Tags": []})
    sm.add_response("list_endpoint_configs", {"EndpointConfigs": []})
    sm.add_response("list_models", {"Models": []})
    stubs["logs"].add_response("describe_log_groups", {"logGroups": []})
    assert module.run(ns(state_path, max_tag_lookups=1), cfg, stubs.aws(), lines) == 1
    assert "RESULT: INCOMPLETE" in lines.text


# ---------------------------------------------------------------- 55_observe

def test_observe_reads_status_metrics_and_filtered_logs(cfg, stubs, state_path, lines):
    module = load_script("55_observe")
    queue_identity(stubs)
    stubs["sagemaker"].add_response("describe_endpoint", describe_endpoint_response(cfg.endpoint_name, "InService"))
    for index in range(len(module.INSTANCE_METRICS) + len(module.INVOCATION_METRICS)):
        point = {"Timestamp": WHEN, "Average": 91.5, "Sum": 12.0, "Unit": "Percent"}
        stubs["cloudwatch"].add_response("get_metric_statistics", {"Label": "x", "Datapoints": [point]})
    stubs["logs"].add_response("filter_log_events", {"events": [
        {"message": "INFO Maximum concurrency for 8,192 tokens per request: 10.93x"},
        {"message": "INFO 127.0.0.1 - POST /invocations 200 OK"},
        {"message": "INFO Available KV cache memory: 12.3 GiB"}]})
    args = ns(state_path, minutes=30, log_minutes=None, logs_only=False, metrics_only=False, all_logs=False, max_log_pages=5)
    assert module.run(args, cfg, stubs.aws(), lines) == 0
    stubs.assert_all_used()
    assert "status InService" in lines.text and "GPUMemoryUtilization" in lines.text and "latest 91.5" in lines.text
    assert "Maximum concurrency for 8,192" in lines.text and "Available KV cache memory" in lines.text
    assert "POST /invocations" not in lines.text and "2 line(s) shown of 3 scanned" in lines.text


def test_observe_survives_a_missing_endpoint_and_log_group(cfg, stubs, state_path, lines):
    module = load_script("55_observe")
    queue_identity(stubs)
    not_found(stubs, "sagemaker", "describe_endpoint", "endpoint")
    stubs["logs"].add_client_error("filter_log_events", service_error_code="ResourceNotFoundException")
    args = ns(state_path, minutes=30, log_minutes=None, logs_only=True, metrics_only=False, all_logs=False, max_log_pages=5)
    assert module.run(args, cfg, stubs.aws(), lines) == 0
    assert "does not exist" in lines.text and "No log group yet" in lines.text


def test_metric_summary_wording():
    module = load_script("55_observe")
    assert "no data yet" in module.summarise_datapoints([], "Average")
    points = [{"Timestamp": WHEN + dt.timedelta(minutes=i), "Average": v, "Sum": v} for i, v in enumerate([10.0, 90.0, 50.0])]
    assert module.summarise_datapoints(points, "Average") == "latest 50.0, min 10.0, max 90.0 over 3 minute(s)"
    assert module.summarise_datapoints(points, "Sum") == "total 150 over 3 minute(s), latest minute 50"
