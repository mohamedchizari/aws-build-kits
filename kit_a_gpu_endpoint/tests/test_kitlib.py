"""Offline tests for configuration, naming, money, state, and the create / wait / delete / find helpers.

AWS calls are answered by botocore's Stubber, which validates each request against the service model.
"""

from __future__ import annotations

import datetime as dt
import json
import re

import pytest
from botocore.exceptions import ClientError

import kitlib
from conftest import (ACCOUNT, KIT_DIR, OTHER_ACCOUNT, WHEN, FakeClock, add_empty_inventory, arn, config_summary,
                      describe_endpoint_response, endpoint_summary, model_summary, not_found)

SAGEMAKER_NAME = re.compile(r"^[a-zA-Z0-9](-*[a-zA-Z0-9]){0,62}$")  # pattern from the SageMaker API reference


# ---------------------------------------------------------------- configuration

def test_defaults(cfg):
    assert cfg.region == "us-east-1" and cfg.prefix == "kitdemo"
    assert cfg.instance_type == "ml.g6.2xlarge" and cfg.hf_model_id == "Qwen/Qwen3-4B"
    assert cfg.image_uri == ("763104351884.dkr.ecr.us-east-1.amazonaws.com/"
                             "vllm:0.30.0-gpu-py312-cu130-ubuntu24.04-sagemaker")
    assert cfg.endpoint_name == "kitdemo-kita-endpoint"
    assert cfg.log_group_name == "/aws/sagemaker/Endpoints/kitdemo-kita-endpoint"
    assert cfg.chat_template_kwargs == {"enable_thinking": False}


def test_names_fit_sagemaker_rules_even_with_the_longest_prefix():
    cfg = kitlib.load_config(environ={"KIT_PREFIX": "a" * 20}, env_file=KIT_DIR / "none.env")
    revision = kitlib.revision_from(WHEN)
    for name in (cfg.endpoint_name, cfg.model_name(revision), cfg.endpoint_config_name(revision)):
        assert len(name) <= 63 and SAGEMAKER_NAME.match(name), name
        assert name.startswith(cfg.name_stem)


@pytest.mark.parametrize("prefix", ["", "Kit", "kit_demo", "-kit", "kit-", "a" * 21, "kit demo"])
def test_bad_prefixes_are_refused(prefix):
    with pytest.raises(kitlib.KitError):
        kitlib.load_config(environ={"KIT_PREFIX": prefix}, env_file=KIT_DIR / "none.env")


def test_container_env_and_tags(cfg):
    env = cfg.container_env()
    assert env == {"SM_VLLM_MODEL": "Qwen/Qwen3-4B", "SM_VLLM_MAX_MODEL_LEN": "8192",
                   "SM_VLLM_MAX_NUM_SEQS": "4", "SM_VLLM_TENSOR_PARALLEL_SIZE": "1"}
    assert all(isinstance(value, str) for value in env.values())
    assert {"Key": "project", "Value": "aws-kits"} in cfg.tags()
    assert {"Key": "kit", "Value": "kit-a-gpu-endpoint"} in cfg.tags()


def test_gpu_memory_utilization_is_added_only_when_set():
    cfg = kitlib.load_config(environ={"GPU_MEMORY_UTILIZATION": "0.85"}, env_file=KIT_DIR / "none.env")
    assert cfg.container_env()["SM_VLLM_GPU_MEMORY_UTILIZATION"] == "0.85"


def test_env_file_then_environment_precedence(tmp_path):
    env_file = tmp_path / "config.env"
    env_file.write_text("# comment\nKIT_PREFIX=fromfile\nMAX_NUM_SEQS = 8\nUNKNOWN_KEY=ignored\n"
                        'INSTANCE_TYPE="ml.g6.xlarge"\nCHAT_TEMPLATE_KWARGS_JSON=\n', encoding="utf-8")
    cfg = kitlib.load_config(environ={"KIT_PREFIX": "fromenv"}, env_file=env_file)
    assert cfg.prefix == "fromenv" and cfg.max_num_seqs == 8 and cfg.instance_type == "ml.g6.xlarge"
    assert cfg.chat_template_kwargs is None


@pytest.mark.parametrize("key,value", [
    ("MAX_MODEL_LEN", "lots"), ("MAX_NUM_SEQS", "0"), ("MAX_HOURS", "0"), ("MAX_HOURS", "48"),
    ("STARTUP_HEALTH_CHECK_TIMEOUT_SECONDS", "30"), ("STARTUP_HEALTH_CHECK_TIMEOUT_SECONDS", "4000"),
    ("GPU_MEMORY_UTILIZATION", "1.5"), ("GPU_MEMORY_UTILIZATION", "high"),
    ("CHAT_TEMPLATE_KWARGS_JSON", "{broken"), ("CHAT_TEMPLATE_KWARGS_JSON", "[1]"),
])
def test_bad_settings_are_refused(key, value):
    with pytest.raises(kitlib.KitError):
        kitlib.load_config(environ={key: value}, env_file=KIT_DIR / "none.env")


def test_config_example_env_parses_and_matches_the_defaults():
    values = kitlib.load_env_file(KIT_DIR / "config.example.env")
    assert set(values) == set(kitlib.DEFAULTS), "config.example.env and kitlib.DEFAULTS list different settings"
    assert values == kitlib.DEFAULTS
    kitlib.load_config(environ={}, env_file=KIT_DIR / "config.example.env")


# ---------------------------------------------------------------- money and quota facts

def test_price_table_is_the_one_read_from_the_price_list():
    assert kitlib.price_for("ml.g6.xlarge", "us-east-1")[0] == 1.1267
    assert kitlib.price_for("ml.g6.2xlarge", "us-east-1")[0] == 1.222
    assert kitlib.price_for("ml.g5.xlarge", "us-east-1")[0] == 1.408
    assert kitlib.price_for("ml.g5.2xlarge", "us-east-1")[0] == 1.515
    assert "2026-10-07" in kitlib.price_for("ml.g6.2xlarge", "us-east-1")[1]


def test_no_price_is_invented_for_another_region_or_instance():
    with pytest.raises(kitlib.KitError):
        kitlib.price_for("ml.g6.2xlarge", "us-west-2")
    with pytest.raises(kitlib.KitError):
        kitlib.price_for("ml.p5.48xlarge", "us-east-1")
    price, source = kitlib.price_for("ml.g6.2xlarge", "us-west-2", override=1.5)
    assert price == 1.5 and "typed by you" in source
    with pytest.raises(kitlib.KitError):
        kitlib.price_for("ml.g6.2xlarge", "us-east-1", override=0)


def test_quota_codes_and_request_command():
    assert kitlib.quota_code_for("ml.g6.xlarge") == "L-D470D954"
    assert kitlib.quota_code_for("ml.g6.2xlarge") == "L-98BDE811"
    assert kitlib.quota_code_for("ml.g5.xlarge") == "L-1928E07B"
    assert kitlib.quota_code_for("ml.g5.2xlarge") == "L-9614C779"
    assert kitlib.quota_code_for("ml.m5.large") is None
    for entry in kitlib.INSTANCES.values():
        assert re.fullmatch(r"L-[0-9A-F]{8}", entry["quota_code"]) and entry["default_quota"] == 0
    command = kitlib.quota_request_command("ml.g6.2xlarge", "us-east-1")
    assert "--service-code sagemaker" in command and "--quota-code L-98BDE811" in command
    assert "--desired-value 1" in command and "--region us-east-1" in command


def test_read_quota_applied_value(stubs):
    stubs["service-quotas"].add_response(
        "get_service_quota", {"Quota": {"QuotaCode": "L-98BDE811", "Value": 1.0}},
        {"ServiceCode": "sagemaker", "QuotaCode": "L-98BDE811"})
    quota = kitlib.read_quota(stubs.aws(), "ml.g6.2xlarge")
    assert quota["value"] == 1.0 and quota["code"] == "L-98BDE811" and "applied" in quota["source"]
    stubs.assert_all_used()


def test_read_quota_falls_back_to_the_aws_default(stubs):
    stubs["service-quotas"].add_client_error("get_service_quota", service_error_code="NoSuchResourceException")
    stubs["service-quotas"].add_response(
        "get_aws_default_service_quota", {"Quota": {"QuotaCode": "L-98BDE811", "Value": 0.0}},
        {"ServiceCode": "sagemaker", "QuotaCode": "L-98BDE811"})
    quota = kitlib.read_quota(stubs.aws(), "ml.g6.2xlarge")
    assert quota["value"] == 0.0 and "default" in quota["source"]
    stubs.assert_all_used()


def test_read_quota_other_errors_are_not_swallowed(stubs):
    stubs["service-quotas"].add_client_error("get_service_quota", service_error_code="AccessDeniedException")
    with pytest.raises(ClientError):
        kitlib.read_quota(stubs.aws(), "ml.g6.2xlarge")


def test_read_quota_unknown_instance_type_makes_no_call(stubs):
    quota = kitlib.read_quota(stubs.aws(), "ml.p5.48xlarge")
    assert quota["code"] is None and quota["value"] is None


# ---------------------------------------------------------------- memory arithmetic

def test_memory_arithmetic_for_the_default_model():
    facts = kitlib.MODEL_FACTS["Qwen/Qwen3-4B"]
    est = kitlib.memory_estimate(facts, max_model_len=8192, max_num_seqs=4, gpu_mem_gib=22, gpu_memory_utilization=0.92)
    gib = 2 ** 30
    assert est["weights_gib"] == pytest.approx(4_022_468_096 * 2 / gib)             # 7.49 GiB
    assert est["weights_gib"] == pytest.approx(7.49, abs=0.01)
    assert est["kv_bytes_per_token_lmi"] == 2 * 2 * 36 * 2560 == 368_640
    assert est["kv_bytes_per_token_gqa"] == 2 * 2 * 36 * 8 * 128 == 147_456
    assert est["kv_per_full_sequence_lmi_gib"] == pytest.approx(368_640 * 8192 / gib)  # 2.81 GiB
    assert est["kv_per_full_sequence_gqa_gib"] == pytest.approx(1.125)
    assert est["kv_worst_case_lmi_gib"] == pytest.approx(4 * 368_640 * 8192 / gib)
    assert est["vllm_budget_gib"] == pytest.approx(20.24)
    assert est["kv_pool_before_overhead_gib"] == pytest.approx(20.24 - est["weights_gib"])
    assert est["full_sequences_that_fit_gqa"] == pytest.approx(est["kv_pool_before_overhead_gib"] / 1.125)
    assert est["full_sequences_that_fit_lmi"] < est["full_sequences_that_fit_gqa"]


def test_lmi_formula_reproduces_the_aws_worked_example():
    # AWS LMI page: Llama2-13b, 40 layers, hidden 5120, fp16 -> "0.00082 GB / token", 4096 tokens -> 3.36 GB.
    per_token = 2 * 2 * 40 * 5120
    assert per_token == 819_200
    assert per_token / 1e9 == pytest.approx(0.00082, abs=0.00001)
    assert per_token * 4096 / 1e9 == pytest.approx(3.36, abs=0.01)


# ---------------------------------------------------------------- dry run

def test_dry_run_prints_the_call_and_never_builds_a_client(lines):
    aws = kitlib.Aws("us-east-1", dry_run=True, out=lines)
    result = aws.call("sagemaker", "create_endpoint", EndpointName="x", EndpointConfigName="y",
                      Body=b"abc", When=WHEN)
    assert result is None and aws.calls_printed == 1 and aws.calls_made == 0
    assert "DRY-RUN would call sagemaker.create_endpoint" in lines.text
    assert '"EndpointName": "x"' in lines.text and "<3 bytes>" in lines.text
    with pytest.raises(kitlib.KitError):
        aws.client("sagemaker")


# ---------------------------------------------------------------- state, time, billing lines

def deployed_state(cfg, created=WHEN, hours=3.0, price=1.222, account=ACCOUNT):
    state = kitlib.empty_state(cfg, account)
    state["resources"] = [
        {"type": "model", "name": cfg.model_name("r1"), "arn": arn("model", cfg.model_name("r1")), "created_utc": kitlib.iso(created)},
        {"type": "endpoint_config", "name": cfg.endpoint_config_name("r1"), "arn": None, "created_utc": kitlib.iso(created)},
        {"type": "endpoint", "name": cfg.endpoint_name, "arn": arn("endpoint", cfg.endpoint_name), "created_utc": kitlib.iso(created)},
    ]
    state["deploy"] = {"revision": "r1", "region": cfg.region, "prefix": cfg.prefix, "account_id": account,
                       "price_source": kitlib.PRICE_SOURCE, "endpoint_create_confirmed": True,
                       "instance_type": cfg.instance_type, "usd_per_hour": price,
                       "hf_model_id": cfg.hf_model_id, "image_uri": cfg.image_uri, "env": cfg.container_env(),
                       "inference_ami_version": cfg.inference_ami_version,
                       "create_called_utc": kitlib.iso(created), "in_service_utc": kitlib.iso(created),
                       "deadline_utc": kitlib.iso(created + dt.timedelta(hours=hours))}
    return state


def test_state_round_trip(cfg, state_path):
    assert kitlib.load_state(state_path) is None
    state = deployed_state(cfg)
    kitlib.save_state(state, state_path)
    assert kitlib.load_state(state_path) == state
    assert not state_path.with_name(state_path.name + ".tmp").exists()


def test_corrupt_state_file_is_reported_not_ignored(state_path):
    state_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(kitlib.KitError):
        kitlib.load_state(state_path)


def test_billing_lines_and_deadline(cfg):
    state = deployed_state(cfg, hours=3.0)
    during = kitlib.billing_lines(state, WHEN + dt.timedelta(hours=1, minutes=30))
    text = "\n".join(during)
    assert "1.50 h" in text and "$1.83" in text and "90 minutes from now" in text and "90_teardown.py" in text
    assert not kitlib.past_deadline(state, WHEN + dt.timedelta(hours=2, minutes=59))
    assert kitlib.past_deadline(state, WHEN + dt.timedelta(hours=3, minutes=1))
    late = "\n".join(kitlib.billing_lines(state, WHEN + dt.timedelta(hours=4)))
    assert "PAST YOUR DEADLINE" in late and "60 minutes" in late
    assert kitlib.billing_lines(None, WHEN) == [] and kitlib.billing_lines(kitlib.empty_state(cfg), WHEN) == []
    assert not kitlib.past_deadline(None, WHEN)


def test_close_run_records_hours_and_estimate(cfg):
    state = deployed_state(cfg, price=1.222)
    kitlib.close_run(state, WHEN + dt.timedelta(hours=2, minutes=30))
    assert state["deploy"] is None and state["resources"] == []
    assert state["history"][0]["hours"] == 2.5
    assert state["history"][0]["estimated_usd"] == pytest.approx(3.055)
    assert kitlib.run_totals(state) == (2.5, 3.055)
    assert kitlib.run_totals(None) == (0, 0)


def test_is_not_found_classification():
    def error(code, message):
        return ClientError({"Error": {"Code": code, "Message": message}}, "Op")

    assert kitlib.is_not_found(error("ValidationException", 'Could not find endpoint "x".'))
    assert kitlib.is_not_found(error("ResourceNotFoundException", "The specified log group does not exist."))
    assert not kitlib.is_not_found(error("ValidationException", "1 validation error detected"))
    assert not kitlib.is_not_found(error("AccessDeniedException", "no"))
    assert not kitlib.is_not_found(RuntimeError("x"))


# ---------------------------------------------------------------- create

def expected_variant(cfg, model_name):
    return {"VariantName": "AllTraffic", "ModelName": model_name, "InstanceType": "ml.g6.2xlarge",
            "InitialInstanceCount": 1, "ContainerStartupHealthCheckTimeoutInSeconds": 900,
            "InferenceAmiVersion": "al2023-ami-sagemaker-inference-gpu-4-1"}


def queue_create(stubs, cfg, revision, env, role_arn):
    model, config = cfg.model_name(revision), cfg.endpoint_config_name(revision)
    stubs["sagemaker"].add_response("create_model", {"ModelArn": arn("model", model)}, {
        "ModelName": model, "ExecutionRoleArn": role_arn,
        "PrimaryContainer": {"Image": cfg.image_uri, "Environment": env}, "Tags": cfg.tags()})
    stubs["sagemaker"].add_response("create_endpoint_config", {"EndpointConfigArn": arn("endpoint-config", config)}, {
        "EndpointConfigName": config, "ProductionVariants": [expected_variant(cfg, model)], "Tags": cfg.tags()})
    return model, config


def test_create_stack_sends_the_documented_requests_and_records_state(cfg, stubs, state_path, lines):
    role_arn = "arn:aws:iam::111122223333:role/kitdemo-kita-sagemaker-execution"
    revision = kitlib.revision_from(WHEN)
    model, config = queue_create(stubs, cfg, revision, cfg.container_env(), role_arn)
    stubs["sagemaker"].add_response("create_endpoint", {"EndpointArn": arn("endpoint", cfg.endpoint_name)}, {
        "EndpointName": cfg.endpoint_name, "EndpointConfigName": config, "Tags": cfg.tags()})
    state = kitlib.empty_state(cfg)
    deadline = WHEN + dt.timedelta(hours=3)
    kitlib.create_stack(stubs.aws(), cfg, cfg.container_env(), role_arn, state, state_path, 1.222, deadline, WHEN, lines)
    stubs.assert_all_used()
    saved = kitlib.load_state(state_path)
    assert [r["type"] for r in saved["resources"]] == ["model", "endpoint_config", "endpoint"]
    assert [r["name"] for r in saved["resources"]] == [model, config, cfg.endpoint_name]
    assert all(r["arn"] for r in saved["resources"])
    assert saved["deploy"]["usd_per_hour"] == 1.222 and saved["deploy"]["deadline_utc"] == kitlib.iso(deadline)
    assert saved["deploy"]["env"] == cfg.container_env() and saved["deploy"]["in_service_utc"] is None


def test_create_stack_keeps_what_exists_in_state_when_the_endpoint_call_fails(cfg, stubs, state_path, lines):
    role_arn = "arn:aws:iam::111122223333:role/r"
    model, config = queue_create(stubs, cfg, kitlib.revision_from(WHEN), cfg.container_env(), role_arn)
    stubs["sagemaker"].add_client_error("create_endpoint", service_error_code="ResourceLimitExceeded",
                                        service_message="The account-level service limit is 0 Instances")
    # Round 4 (MAJOR 1): the endpoint is the thing that bills, so a refusal alone no longer takes it out of the
    # state file. ListEndpoints is asked first, and only "not listed" removes the record.
    stubs["sagemaker"].add_response("list_endpoints", {"Endpoints": []},
                                    {"MaxResults": 100, "NameContains": cfg.endpoint_name})
    state = kitlib.empty_state(cfg)
    with pytest.raises(ClientError):
        kitlib.create_stack(stubs.aws(), cfg, cfg.container_env(), role_arn, state, state_path, 1.222,
                            WHEN + dt.timedelta(hours=3), WHEN, lines)
    stubs.assert_all_used()
    saved = kitlib.load_state(state_path)
    assert [r["name"] for r in saved["resources"]] == [model, config]  # teardown can still find and delete these
    assert saved["deploy"] is None


def test_create_stack_omits_the_ami_field_when_it_is_blank(stubs, state_path, lines):
    cfg = kitlib.load_config(environ={"INFERENCE_AMI_VERSION": ""}, env_file=KIT_DIR / "none.env")
    revision = kitlib.revision_from(WHEN)
    model, config = cfg.model_name(revision), cfg.endpoint_config_name(revision)
    variant = expected_variant(cfg, model)
    del variant["InferenceAmiVersion"]
    stubs["sagemaker"].add_response("create_model", {"ModelArn": arn("model", model)})
    stubs["sagemaker"].add_response("create_endpoint_config", {"EndpointConfigArn": arn("endpoint-config", config)},
                                    {"EndpointConfigName": config, "ProductionVariants": [variant], "Tags": cfg.tags()})
    stubs["sagemaker"].add_response("create_endpoint", {"EndpointArn": arn("endpoint", cfg.endpoint_name)})
    kitlib.create_stack(stubs.aws(), cfg, cfg.container_env(), "arn:aws:iam::111122223333:role/r",
                        kitlib.empty_state(cfg), state_path, 1.222, WHEN, WHEN, lines)
    stubs.assert_all_used()


def test_create_stack_dry_run_prints_three_calls_and_writes_nothing(cfg, state_path, lines):
    aws = kitlib.Aws("us-east-1", dry_run=True, out=lines)
    kitlib.create_stack(aws, cfg, cfg.container_env(), "arn:aws:iam::<ACCOUNT_ID>:role/r", kitlib.empty_state(cfg),
                        state_path, 1.222, WHEN, WHEN, lines)
    assert aws.calls_printed == 3 and aws.calls_made == 0
    assert not state_path.exists()
    for operation in ("create_model", "create_endpoint_config", "create_endpoint"):
        assert f"sagemaker.{operation}" in lines.text


# ---------------------------------------------------------------- wait

def test_wait_in_service_polls_until_in_service(cfg, stubs, lines):
    for status in ("Creating", "Creating", "InService"):
        stubs["sagemaker"].add_response("describe_endpoint", describe_endpoint_response(cfg.endpoint_name, status),
                                        {"EndpointName": cfg.endpoint_name})
    clock = FakeClock()
    status, description = kitlib.wait_in_service(stubs.aws(), cfg.endpoint_name, lines, clock.sleep, clock)
    assert status == "InService" and description["EndpointStatus"] == "InService"
    assert clock.now == 1060.0  # two sleeps of 30 s
    stubs.assert_all_used()


def test_wait_in_service_returns_failed_with_the_reason(cfg, stubs, lines):
    stubs["sagemaker"].add_response("describe_endpoint", describe_endpoint_response(
        cfg.endpoint_name, "Failed", "Unable to provision requested ML compute capacity due to InsufficientInstanceCapacity error."))
    clock = FakeClock()
    status, description = kitlib.wait_in_service(stubs.aws(), cfg.endpoint_name, lines, clock.sleep, clock)
    assert status == "Failed" and "InsufficientInstanceCapacity" in description["FailureReason"]


def test_wait_in_service_times_out(cfg, stubs, lines):
    for _ in range(3):
        stubs["sagemaker"].add_response("describe_endpoint", describe_endpoint_response(cfg.endpoint_name, "Creating"))
    clock = FakeClock()
    status, _ = kitlib.wait_in_service(stubs.aws(), cfg.endpoint_name, lines, clock.sleep, clock, timeout_s=60, poll_s=30)
    assert status == "Timeout"
    stubs.assert_all_used()


# ---------------------------------------------------------------- delete

def test_delete_stack_order_and_waiting(cfg, stubs, lines):
    sm = stubs["sagemaker"]
    sm.add_response("delete_endpoint", {}, {"EndpointName": cfg.endpoint_name})
    sm.add_response("describe_endpoint", describe_endpoint_response(cfg.endpoint_name, "Deleting"))
    not_found(stubs, "sagemaker", "describe_endpoint", f'endpoint "{cfg.endpoint_name}"')
    sm.add_response("delete_endpoint_config", {}, {"EndpointConfigName": "cfg-1"})
    sm.add_response("delete_model", {}, {"ModelName": "model-1"})
    clock = FakeClock()
    assert kitlib.delete_stack(stubs.aws(), [cfg.endpoint_name], ["cfg-1"], ["model-1"], lines, clock.sleep, clock) is True
    stubs.assert_all_used()  # the Stubber enforces the order: endpoint, wait, configuration, model


def test_delete_stack_tolerates_resources_that_are_already_gone(cfg, stubs, lines):
    not_found(stubs, "sagemaker", "delete_endpoint", "endpoint")
    not_found(stubs, "sagemaker", "describe_endpoint", "endpoint")
    not_found(stubs, "sagemaker", "delete_endpoint_config", "endpoint configuration")
    not_found(stubs, "sagemaker", "delete_model", "model")
    clock = FakeClock()
    assert kitlib.delete_stack(stubs.aws(), ["e"], ["c"], ["m"], lines, clock.sleep, clock) is True
    assert lines.text.count("already absent") == 3


def test_delete_stack_leaves_config_and_model_alone_while_the_endpoint_is_still_there(cfg, stubs, lines):
    sm = stubs["sagemaker"]
    sm.add_response("delete_endpoint", {})
    for _ in range(3):
        sm.add_response("describe_endpoint", describe_endpoint_response(cfg.endpoint_name, "Deleting"))
    clock = FakeClock()
    aws = stubs.aws()
    original = kitlib.wait_endpoint_gone
    try:
        kitlib.wait_endpoint_gone = lambda a, n, o, s, c: original(a, n, o, s, c, timeout_s=30, poll_s=15)
        assert kitlib.delete_stack(aws, [cfg.endpoint_name], ["cfg-1"], ["model-1"], lines, clock.sleep, clock) is False
    finally:
        kitlib.wait_endpoint_gone = original
    stubs.assert_all_used()  # no delete_endpoint_config or delete_model was attempted
    assert "STILL PRESENT" in lines.text


def test_delete_stack_does_not_hide_an_access_error(cfg, stubs, lines):
    stubs["sagemaker"].add_client_error("delete_endpoint", service_error_code="AccessDeniedException")
    clock = FakeClock()
    with pytest.raises(ClientError):
        kitlib.delete_stack(stubs.aws(), ["e"], ["c"], ["m"], lines, clock.sleep, clock)


# ---------------------------------------------------------------- find

def test_find_remaining_by_name_prefix(cfg, stubs):
    add_empty_inventory(
        stubs, cfg,
        endpoints=[endpoint_summary(cfg.endpoint_name)],
        configs=[config_summary(cfg.endpoint_config_name("r1"))],
        models=[model_summary(cfg.model_name("r1"))],
        log_groups=[cfg.log_group_name])
    found = kitlib.find_remaining(stubs.aws(), cfg)
    assert kitlib.remaining_count(found) == 4 and kitlib.remaining_count(found, count_logs=False) == 3
    assert found["endpoints"][0]["why"] == "name prefix" and found["endpoints"][0]["status"] == "InService"
    assert found["tag_lookups"] == 0 and not found["incomplete"]
    stubs.assert_all_used()


def test_find_remaining_by_tags_when_the_name_does_not_match(cfg, stubs):
    sm = stubs["sagemaker"]
    sm.add_response("list_endpoints", {"Endpoints": [endpoint_summary("renamed-endpoint"), endpoint_summary("someone-elses")]})
    sm.add_response("list_tags", {"Tags": cfg.tags()}, {"ResourceArn": arn("endpoint", "renamed-endpoint")})
    sm.add_response("list_tags", {"Tags": [{"Key": "project", "Value": "aws-kits"}]},
                    {"ResourceArn": arn("endpoint", "someone-elses")})
    sm.add_response("list_endpoint_configs", {"EndpointConfigs": []})
    sm.add_response("list_models", {"Models": [model_summary("other-model")]})
    sm.add_response("list_tags", {"Tags": []}, {"ResourceArn": arn("model", "other-model")})
    stubs["logs"].add_response("describe_log_groups", {"logGroups": []})
    found = kitlib.find_remaining(stubs.aws(), cfg)
    assert [e["name"] for e in found["endpoints"]] == ["renamed-endpoint"] and found["endpoints"][0]["why"] == "tags"
    assert found["other_endpoints"] == 1 and found["models"] == [] and found["tag_lookups"] == 3
    stubs.assert_all_used()


def test_find_remaining_follows_pagination(cfg, stubs):
    sm = stubs["sagemaker"]
    sm.add_response("list_endpoints", {"Endpoints": [endpoint_summary(cfg.name_stem + "one")], "NextToken": "t1"},
                    {"MaxResults": 100})
    sm.add_response("list_endpoints", {"Endpoints": [endpoint_summary(cfg.name_stem + "two")]},
                    {"MaxResults": 100, "NextToken": "t1"})
    sm.add_response("list_endpoint_configs", {"EndpointConfigs": []})
    sm.add_response("list_models", {"Models": []})
    stubs["logs"].add_response("describe_log_groups", {"logGroups": []})
    found = kitlib.find_remaining(stubs.aws(), cfg)
    assert [e["name"] for e in found["endpoints"]] == [cfg.name_stem + "one", cfg.name_stem + "two"]
    stubs.assert_all_used()


def test_find_remaining_says_incomplete_when_the_tag_lookup_limit_is_hit(cfg, stubs):
    sm = stubs["sagemaker"]
    sm.add_response("list_endpoints", {"Endpoints": [endpoint_summary("a"), endpoint_summary("b")]})
    sm.add_response("list_tags", {"Tags": []})
    sm.add_response("list_endpoint_configs", {"EndpointConfigs": []})
    sm.add_response("list_models", {"Models": []})
    stubs["logs"].add_response("describe_log_groups", {"logGroups": []})
    found = kitlib.find_remaining(stubs.aws(), cfg, max_tag_lookups=1)
    assert found["incomplete"] is True and found["tag_lookups"] == 1
    assert any("INCOMPLETE" in line for line in kitlib.describe_remaining(found))
    stubs.assert_all_used()


def test_find_remaining_can_skip_logs(cfg, stubs):
    sm = stubs["sagemaker"]
    sm.add_response("list_endpoints", {"Endpoints": []})
    sm.add_response("list_endpoint_configs", {"EndpointConfigs": []})
    sm.add_response("list_models", {"Models": []})
    found = kitlib.find_remaining(stubs.aws(), cfg, check_logs=False)
    assert kitlib.remaining_count(found) == 0
    stubs.assert_all_used()


def test_json_in_state_is_plain(cfg, state_path):
    kitlib.save_state(kitlib.empty_state(cfg), state_path)
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["kit"] == "kit_a_gpu_endpoint" and data["resources"] == []
