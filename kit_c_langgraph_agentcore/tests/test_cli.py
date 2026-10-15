"""Every script, started as a real process with no credentials and the network blocked.

Each one must answer --help with exit code 0 and --dry-run with exit code 0
(the clean check and the two teardown scripts: 3, because a dry run of them
proves nothing and deletes nothing, and must not look like a pass), must not
write .state.json, and, if it bills, must refuse to run without
--i-understand-this-bills.

The child processes get a sitecustomize module that makes any network
connection raise, so a script that reached for AWS or any other host in
--dry-run would fail here.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest
from conftest import ROOT

AWS_SCRIPTS = [
    "00_check.py", "30_deploy.py", "40_enable_observability.py", "50_invoke_hosted.py",
    "60_read_usage.py", "90_teardown.py", "99_verify_clean.py",
    "optional_gateway/10_create_gateway.py", "optional_gateway/50_call_gateway_tools.py",
    "optional_gateway/90_teardown_gateway.py",
]
LOCAL_SCRIPTS = ["10_run_local.py", "12_serve_local.py", "20_package.py"]
ALL_SCRIPTS = AWS_SCRIPTS + LOCAL_SCRIPTS
BILLING_SCRIPTS = [
    "10_run_local.py", "12_serve_local.py", "30_deploy.py", "40_enable_observability.py",
    "50_invoke_hosted.py", "optional_gateway/10_create_gateway.py",
    "optional_gateway/50_call_gateway_tools.py",
]

# A dry run of the clean check must not exit 0 (the rule shared by all three kits). Since the
# second review the same holds for the two teardown scripts (round 2, minor 9).
DRY_RUN_EXIT = {"99_verify_clean.py": 3, "90_teardown.py": 3, "optional_gateway/90_teardown_gateway.py": 3}

SITECUSTOMIZE = '''
import socket

def _refuse(self, address, *args, **kwargs):
    raise RuntimeError("network blocked in tests: %r" % (address,))

socket.socket.connect = _refuse
socket.socket.connect_ex = _refuse
'''


@pytest.fixture()
def child_env(tmp_path):
    (tmp_path / "sitecustomize.py").write_text(SITECUSTOMIZE)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("AWS_") and k not in {"KIT_PREFIX", "MODEL_ID", "PLATFORM_VERSION"}}
    env.update({
        "PYTHONPATH": str(tmp_path),
        "PYTHONDONTWRITEBYTECODE": "1",
        "AWS_CONFIG_FILE": str(tmp_path / "no-config"),
        "AWS_SHARED_CREDENTIALS_FILE": str(tmp_path / "no-credentials"),
        "AWS_EC2_METADATA_DISABLED": "true",
    })
    return env


def run(script: str, *args: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ROOT / script), *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)


def test_the_script_list_is_complete():
    on_disk = sorted(p.name for p in ROOT.glob("[0-9][0-9]_*.py"))
    on_disk += sorted("optional_gateway/" + p.name for p in (ROOT / "optional_gateway").glob("[0-9][0-9]_*.py"))
    assert sorted(on_disk) == sorted(ALL_SCRIPTS)


@pytest.mark.parametrize("script", ALL_SCRIPTS)
def test_help_works_without_credentials(script, child_env):
    result = run(script, "--help", env=child_env)
    assert result.returncode == 0, result.stderr
    assert "--dry-run" in result.stdout
    assert ("--i-understand-this-bills" in result.stdout) == (script in BILLING_SCRIPTS)


@pytest.mark.parametrize("script", ALL_SCRIPTS)
def test_dry_run_works_without_credentials_or_network(script, child_env):
    state_file = ROOT / ".state.json"
    existed = state_file.exists()
    before = state_file.read_bytes() if existed else None
    result = run(script, "--dry-run", env=child_env)
    assert result.returncode == DRY_RUN_EXIT.get(script, 0), result.stdout + result.stderr
    assert "DRY-RUN" in result.stdout
    assert "Traceback" not in result.stderr
    assert state_file.exists() == existed
    if existed:
        assert state_file.read_bytes() == before


@pytest.mark.parametrize("script", BILLING_SCRIPTS)
def test_billing_scripts_refuse_without_the_flag(script, child_env):
    result = run(script, env=child_env)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "Stopped. Nothing was created." in result.stdout
    assert "What this step is expected to cost:" in result.stdout


@pytest.mark.parametrize("script", ["00_check.py", "90_teardown.py", "99_verify_clean.py", "60_read_usage.py"])
def test_real_mode_without_credentials_fails_cleanly(script, child_env):
    """No credentials and no network: the script must stop with a message, not a traceback."""
    result = run(script, env=child_env)
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
    assert "RESULT: CLEAN" not in result.stdout and "PREFLIGHT OK" not in result.stdout
    assert "CROSS-CHECKED: runtime cost" not in result.stdout


def test_run_local_with_fake_model_reports_a_blocked_network_honestly(child_env):
    """--fake-model needs no AWS. With the network blocked the tool reports the failure as data."""
    result = run("10_run_local.py", "energy storage", "--fake-model", env=child_env)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "search_federal_register" in result.stdout
    assert "upstream_error" in result.stdout
    assert "Model turns: 0" in result.stdout


def test_the_clean_check_dry_run_says_why_it_is_not_zero(child_env):
    result = run("99_verify_clean.py", "--dry-run", env=child_env)
    assert result.returncode == 3
    assert "proves nothing" in result.stdout and "Exit code 3, not 0" in result.stdout
    assert "RESULT:" not in result.stdout


def test_run_local_with_fake_model_never_shows_unchecked_text(child_env):
    """With the network blocked the only tool call fails, so there is no checked answer to show."""
    result = run("10_run_local.py", "energy storage", "--fake-model", env=child_env)
    assert "No checked answer." in result.stdout
    assert "FAKE MODEL" not in result.stdout  # the fake's own text was withheld, like a real model's
    assert "was withheld" in result.stdout
    shown = run("10_run_local.py", "energy storage", "--fake-model", "--show-withheld", env=child_env)
    assert "Withheld model text. NOT checked" in shown.stdout and "FAKE MODEL" in shown.stdout


# ---------------------------------------------------------------- tests/record_fixtures.py (review minor 13)
def _fixture_bytes():
    return {p.name: p.read_bytes() for p in sorted((ROOT / "tests" / "fixtures").glob("*.json"))}


@pytest.mark.parametrize("args, code, expect", [
    (["--help"], 0, "--record"),
    (["--dry-run"], 0, "DRY-RUN complete: nothing was sent"),
    ([], 2, "Nothing was sent and no fixture was written. Add --record"),
    (["--verbose"], 2, ""),          # an argument it does not know
    (["--dry-run", "--record"], 2, ""),
])
def test_the_fixture_recorder_sends_nothing_without_the_record_flag(child_env, args, code, expect):
    before = _fixture_bytes()
    result = run("tests/record_fixtures.py", *args, env=child_env)
    assert result.returncode == code, result.stdout + result.stderr
    assert expect in result.stdout
    assert "network blocked" not in result.stdout + result.stderr  # it did not even try
    assert _fixture_bytes() == before


def test_the_fixture_recorder_with_record_does_reach_for_the_network(child_env):
    """The other half: --record is the one way to send, and here the network is blocked."""
    before = _fixture_bytes()
    result = run("tests/record_fixtures.py", "--record", env=child_env)
    assert result.returncode != 0
    assert _fixture_bytes() == before
