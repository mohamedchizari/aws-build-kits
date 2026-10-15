"""kitlib: configuration, names, the dry-run door and the billing flag. Offline."""
from __future__ import annotations

import argparse

import pytest
from botocore.exceptions import ParamValidationError


def test_default_config_and_names(kit):
    cfg = kit.Config.from_env()
    assert cfg.region == "us-east-1" and cfg.prefix == "kitdemo"
    assert cfg.model_id == "us.amazon.nova-micro-v1:0"
    assert cfg.platform_version == ""  # left out, which AWS documents as V1
    assert cfg.runtime_name == "kitdemo_kitc_fr_agent"
    assert cfg.role_name == "kitdemo-kitc-runtime-role"
    assert cfg.bucket_name("000000000000") == "kitdemo-kitc-code-000000000000-us-east-1"
    assert cfg.usage_log_group == "/aws/vendedlogs/bedrock-agentcore/kitdemo-kitc-usage"
    assert cfg.runtime_log_group_prefix == "/aws/bedrock-agentcore/runtimes/kitdemo_kitc_fr_agent-"
    assert cfg.python_version == "3.13"
    for name in (cfg.role_name, cfg.gateway_name, cfg.gateway_role_name, cfg.delivery_names("usage")[0]):
        assert name.startswith("kitdemo-kitc-")


def test_config_reads_environment(kit, monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.setenv("KIT_PREFIX", "my-kit")
    monkeypatch.setenv("MODEL_ID", "us.amazon.nova-2-lite-v1:0")
    monkeypatch.setenv("PLATFORM_VERSION", "v2")
    monkeypatch.setenv("ENABLE_OTEL", "false")
    cfg = kit.Config.from_env()
    assert (cfg.region, cfg.prefix, cfg.platform_version, cfg.enable_otel) == ("us-west-2", "my-kit", "V2", False)
    assert cfg.runtime_name == "my_kit_kitc_fr_agent"  # runtime names take underscores only
    assert cfg.rates() == ("V2", 0.1276, 0.0169)


@pytest.mark.parametrize(
    "name, value",
    [("KIT_PREFIX", "Kit"), ("KIT_PREFIX", "k"), ("KIT_PREFIX", "kit_demo"), ("KIT_PREFIX", "x" * 17),
     ("KIT_PREFIX", "kit-"), ("AWS_REGION", "virginia"), ("PLATFORM_VERSION", "V3"),
     ("IDLE_TIMEOUT_SECONDS", "30"), ("MAX_LIFETIME_SECONDS", "90"), ("PYTHON_RUNTIME", "PYTHON_3_9")],
)
def test_config_rejects_bad_values(kit, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(kit.ConfigError):
        kit.Config.from_env()


def test_runtime_name_fits_the_service_pattern(kit, monkeypatch):
    import re

    monkeypatch.setenv("KIT_PREFIX", "a" + "b" * 15)
    cfg = kit.Config.from_env()
    assert re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,47}", cfg.runtime_name)
    assert len(cfg.bucket_name("000000000000")) <= 63


def test_rates_follow_the_reported_platform_version(kit):
    cfg = kit.Config.from_env()
    assert cfg.rates() == ("V1", 0.0895, 0.00945)
    assert cfg.rates("V2") == ("V2", 0.1276, 0.0169)
    assert cfg.rates("not reported") == ("V1", 0.0895, 0.00945)
    # review minor 4: a stored "not reported" must not hide a V2 deploy
    assert cfg.rates("not reported", "V2") == ("V2", 0.1276, 0.0169)
    assert cfg.rates(None, "default") == ("V1", 0.0895, 0.00945)


def test_base_model_id(kit):
    assert kit.base_model_id("us.amazon.nova-micro-v1:0") == "amazon.nova-micro-v1:0"
    assert kit.base_model_id("global.anthropic.claude-haiku-4-5-20251001-v1:0") == "anthropic.claude-haiku-4-5-20251001-v1:0"
    assert kit.base_model_id("amazon.nova-micro-v1:0") == "amazon.nova-micro-v1:0"
    assert kit.is_inference_profile_id("us.amazon.nova-micro-v1:0")
    assert not kit.is_inference_profile_id("amazon.nova-micro-v1:0")


def test_dry_run_prints_the_call_and_returns_the_placeholder(kit):
    lines: list[str] = []
    aws = kit.Aws("us-east-1", dry_run=True, out=lines.append,
                  client_factory=lambda service: pytest.fail("dry-run must not build a client"))
    result = aws.call("sts", "get_caller_identity", dry_result={"Account": "000000000000"})
    assert result == {"Account": "000000000000"} and isinstance(result, kit.DryRunResult)
    assert lines == ["DRY-RUN  would call sts.get_caller_identity({})"]
    assert aws.planned == [("sts", "get_caller_identity", {})]


def test_dry_run_still_checks_parameters_against_the_sdk_model(kit):
    aws = kit.Aws("us-east-1", dry_run=True, out=lambda line: None)
    with pytest.raises(ParamValidationError):  # wrong parameter name
        aws.call("bedrock-agentcore-control", "get_agent_runtime", runtimeId="x")
    with pytest.raises(ParamValidationError):  # missing required parameter
        aws.call("bedrock-agentcore", "invoke_agent_runtime", payload=b"{}")
    with pytest.raises(ParamValidationError):  # session id shorter than 33 characters
        aws.call("bedrock-agentcore", "invoke_agent_runtime", agentRuntimeArn="arn", payload=b"{}",
                 runtimeSessionId="too-short")
    with pytest.raises(ValueError):
        aws.call("bedrock-agentcore-control", "no_such_operation")


def test_confirm_billing(kit):
    lines: list[str] = []
    stop = argparse.Namespace(dry_run=False, bills_ok=False)
    assert kit.confirm_billing(stop, ["PRICE LINE"], lines.append) is False
    assert any("PRICE LINE" in line for line in lines)
    assert any("--i-understand-this-bills" in line for line in lines)
    assert kit.confirm_billing(argparse.Namespace(dry_run=True, bills_ok=False), [], lines.append)
    assert kit.confirm_billing(argparse.Namespace(dry_run=False, bills_ok=True), [], lines.append)


def test_state_round_trip_and_dry_run_does_not_write(kit, tmp_path):
    path = tmp_path / "s.json"
    state = kit.State(path)
    state.set(runtime_id="r-1")
    assert kit.State(path).get("runtime_id") == "r-1"
    dry = kit.State(tmp_path / "dry.json", dry_run=True)
    dry.set(runtime_id="r-2")
    assert dry.get("runtime_id") == "r-2" and not (tmp_path / "dry.json").exists()


def test_mask_account(kit):
    assert kit.mask_account("123456789012") == "********9012"


def test_prices_carry_source_and_date(kit):
    text = " ".join(kit.PRICE_LINES_RUNTIME + kit.PRICE_LINES_GATEWAY)
    assert "https://aws.amazon.com/bedrock/agentcore/pricing/" in text and "2026-10-07" in text
    assert kit.RUNTIME_RATES == {"V1": (0.0895, 0.00945), "V2": (0.1276, 0.0169)}
    model = " ".join(kit.PRICE_LINES_MODEL)
    assert "$0.035 per 1M input tokens" in model and "$0.14 per 1M output tokens" in model
    assert "2026-10-07" in model and "https://aws.amazon.com/bedrock/pricing/" in model
    runtime = " ".join(kit.PRICE_LINES_RUNTIME)
    # review minors 1 and 2: the storage charge is stated, and no Region claim the page does not make
    assert "S3 Standard rates" in runtime and "system overhead" in runtime and "standard EC2 rates" in runtime
    assert "commercial AWS Regions" not in runtime and "no standing charge" not in runtime


def test_what_an_unstopped_session_can_cost_is_plain_arithmetic_on_the_list_rates(kit):
    """Rates and the 2 vCPU / 8 GB ceiling were read from AWS pages on 2026-10-07 (kitlib.py)."""
    kit_v1 = kit.session_cost_bounds(120, 900, "V1")
    assert kit_v1["idle"] == pytest.approx(120 / 3600 * 0.5 * 0.00945)             # $0.00016
    assert kit_v1["ceiling"] == pytest.approx(900 / 3600 * (2 * 0.0895 + 8 * 0.00945))  # $0.064
    assert round(kit_v1["ceiling"], 3) == 0.064
    assert round(kit.session_cost_bounds(120, 900, "V2")["ceiling"], 3) == 0.098
    # the service defaults: 900 s idle, 28,800 s lifetime
    assert (kit.SERVICE_DEFAULT_IDLE_S, kit.SERVICE_DEFAULT_LIFETIME_S) == (900, 28800)
    assert round(kit.session_cost_bounds(900, 28800, "V1")["ceiling"], 2) == 2.04
    assert round(kit.session_cost_bounds(900, 28800, "V2")["ceiling"], 2) == 3.12
    assert round(kit.session_cost_bounds(900, 28800, "V1")["idle"], 4) == 0.0012


def test_the_invoke_client_can_be_built_with_no_retry(kit):
    """Review M4: a retried InvokeAgentRuntime would run the agent twice and be timed as one call."""
    aws = kit.Aws("us-east-1")
    once = aws.client("bedrock-agentcore", attempts=1)
    usual = aws.client("bedrock-agentcore")
    assert once is not usual and aws.client("bedrock-agentcore", attempts=1) is once
    assert once.meta.config.retries["total_max_attempts"] == 1
    assert usual.meta.config.retries["total_max_attempts"] == 3


def test_wait_until_times_out(kit):
    with pytest.raises(TimeoutError):
        kit.wait_until(lambda: False, timeout_s=0, interval_s=0, what="never", dry_run=False)
    assert kit.wait_until(lambda: "yes", timeout_s=1, interval_s=0, what="now", dry_run=False) == "yes"
