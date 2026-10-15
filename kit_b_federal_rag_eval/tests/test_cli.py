"""The numbered scripts as a user runs them: --help, --dry-run and the billing gate, with no credentials."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from conftest import KIT_DIR

SCRIPTS = ["00_check.py", "10_build_corpus.py", "20_build_eval_set.py", "30_deploy_kb.py",
           "40_create_guardrail.py", "50_run_eval.py", "90_teardown.py", "99_verify_clean.py"]
BILLING = ["30_deploy_kb.py", "40_create_guardrail.py", "50_run_eval.py"]


def run(script, *args, extra_env=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "AWS_EC2_METADATA_DISABLED": "true",
                # Three independent locks so a test can never touch a real account: no profile
                # files, every service endpoint pointed at a dead local port, and a dead proxy.
                "AWS_CONFIG_FILE": os.devnull, "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
                "AWS_ENDPOINT_URL": "http://127.0.0.1:9",
                # a proxy that cannot exist: any attempt to reach the network fails at once
                "HTTPS_PROXY": "http://127.0.0.1:9", "HTTP_PROXY": "http://127.0.0.1:9", "NO_PROXY": ""})
    env.update(extra_env or {})
    return subprocess.run([sys.executable, str(KIT_DIR / script), *args], capture_output=True, text=True,
                          cwd=KIT_DIR, env=env, timeout=120)


def test_all_eight_scripts_exist():
    assert sorted(p.name for p in KIT_DIR.glob("[0-9][0-9]_*.py")) == SCRIPTS


@pytest.mark.parametrize("script", SCRIPTS)
def test_help_works_without_credentials(script):
    result = run(script, "--help")
    assert result.returncode == 0, result.stderr
    assert "--dry-run" in result.stdout


# A dry run of the clean check proves nothing, so it must not look like a pass (round 1 review, MINOR 12).
# The same holds for a dry run of the teardown, which deletes nothing (round 2 review, MINOR 9).
DRY_RUN_EXIT_CODE = {"99_verify_clean.py": 5, "90_teardown.py": 5}


@pytest.mark.parametrize("script", SCRIPTS)
def test_dry_run_works_without_credentials_and_writes_nothing(script, tmp_path):
    result = run(script, "--dry-run")
    assert result.returncode == DRY_RUN_EXIT_CODE.get(script, 0), result.stdout + result.stderr
    assert "DRY-RUN" in result.stdout
    assert "Traceback" not in result.stderr
    assert list(tmp_path.iterdir()) == []            # no build/, no state file, no results/


@pytest.mark.parametrize("kb_type", ["managed", "s3vectors"])
@pytest.mark.parametrize("script", ["30_deploy_kb.py", "90_teardown.py"])
def test_dry_run_for_both_knowledge_base_types(script, kb_type):
    result = run(script, "--dry-run", extra_env={"KB_TYPE": kb_type})
    assert result.returncode == DRY_RUN_EXIT_CODE.get(script, 0), result.stdout + result.stderr
    assert ("s3vectors." in result.stdout) == (kb_type == "s3vectors" or "list_vector_buckets" in result.stdout)
    assert "opensearch" not in result.stdout.lower() or script == "99_verify_clean.py"


def tiny_eval_build(tmp_path):
    build = tmp_path / "build"
    (build / "eval").mkdir(parents=True)
    (build / "eval" / "eval_set.jsonl").write_text("", encoding="utf-8")
    (build / "eval" / "eval_set_meta.json").write_text(json.dumps({"label_sets": {}}), encoding="utf-8")
    (build / "corpus_manifest.json").write_text(json.dumps({"mean_document_chars": 900}), encoding="utf-8")


@pytest.mark.parametrize("script", BILLING)
def test_billing_scripts_refuse_without_the_flag_and_print_prices_first(script, tmp_path):
    tiny_eval_build(tmp_path)
    result = run(script)
    assert result.returncode == 2
    assert "Refusing to run without --i-understand-this-bills" in result.stderr
    assert "This script spends money. Expected list prices:" in result.stdout
    assert "read 2026-10-07" in result.stdout
    assert "DRY-RUN" not in result.stdout


def test_deploy_dry_run_never_mentions_creating_an_opensearch_collection():
    out = run("30_deploy_kb.py", "--dry-run").stdout
    assert "create_collection" not in out and "opensearchserverless" not in out
    assert "bedrock-agent.create_knowledge_base" in out and '"type": "MANAGED"' in out


def test_check_and_verify_dry_runs_list_opensearch_collections():
    for script in ("00_check.py", "99_verify_clean.py"):
        assert "opensearchserverless.list_collections" in run(script, "--dry-run").stdout


def test_run_eval_dry_run_shows_the_four_calls_and_the_estimate():
    out = run("50_run_eval.py", "--dry-run").stdout
    for needle in ("bedrock-agent-runtime.retrieve", "bedrock-runtime.converse", "bedrock-runtime.apply_guardrail",
                   "ESTIMATED TOTAL for this run: $", "4 characters per token"):
        assert needle in out
    assert out.count("DRY-RUN bedrock-runtime.converse") == 2     # one answer, one judgement


def test_run_eval_needs_a_built_eval_set_and_a_deployed_knowledge_base(tmp_path):
    missing = run("50_run_eval.py", "--i-understand-this-bills")
    assert missing.returncode == 1 and "Run 10_build_corpus.py and 20_build_eval_set.py first" in missing.stderr
    tiny_eval_build(tmp_path)
    result = run("50_run_eval.py", "--i-understand-this-bills")
    assert result.returncode == 1 and "Run 30_deploy_kb.py first" in result.stderr


def test_real_runs_without_credentials_fail_cleanly_and_create_nothing(tmp_path):
    """With no credentials and no route to AWS, a real run must stop with an error, not a traceback."""
    corpus_dir = tmp_path / "build" / "corpus"
    corpus_dir.mkdir(parents=True)
    (corpus_dir / "uc-0001.txt").write_text("x", encoding="utf-8")
    env = {"AWS_ACCESS_KEY_ID": "", "AWS_SECRET_ACCESS_KEY": "", "AWS_CONFIG_FILE": str(tmp_path / "none"),
           "AWS_SHARED_CREDENTIALS_FILE": str(tmp_path / "none"), "AWS_MAX_ATTEMPTS": "1"}
    result = run("30_deploy_kb.py", "--i-understand-this-bills", "--skip-smoke-test", extra_env=env)
    assert result.returncode == 1
    assert "FAILED:" in result.stderr and "Traceback" not in result.stderr
    assert not (tmp_path / "state.json").exists() or json.loads((tmp_path / "state.json").read_text()) == {}


def test_teardown_without_credentials_stops_before_it_asks_or_deletes():
    """Since the round 1 review teardown first asks STS which account it is in, so it can compare it
    with .state.json. Without credentials that fails, and it must stop there."""
    result = subprocess.run([sys.executable, str(KIT_DIR / "90_teardown.py")], input="y\n", capture_output=True,
                            text=True, cwd=KIT_DIR, timeout=60,
                            env={**{k: v for k, v in os.environ.items() if not k.startswith("AWS_")},
                                 "PYTHONDONTWRITEBYTECODE": "1", "AWS_CONFIG_FILE": os.devnull,
                                 "AWS_SHARED_CREDENTIALS_FILE": os.devnull, "AWS_MAX_ATTEMPTS": "1",
                                 "AWS_ENDPOINT_URL": "http://127.0.0.1:9", "AWS_EC2_METADATA_DISABLED": "true"})
    assert result.returncode == 1
    assert "STOP: could not find out which AWS account" in result.stderr
    assert "Nothing was deleted" in result.stderr and "Traceback" not in result.stderr
    assert "Delete all kit B resources" not in result.stdout


def test_teardown_asks_before_deleting(monkeypatch, tmp_path):
    import builtins

    import fakeaws
    world = fakeaws.install(monkeypatch, fakeaws.World())
    fakeaws.make_corpus(tmp_path / "build")
    assert fakeaws.run_script("30_deploy_kb.py", fakeaws.BILLS)[0] == 0
    before = world.left()
    asked = []
    monkeypatch.setattr(builtins, "input", lambda prompt: asked.append(prompt) or "n")
    code, out = fakeaws.run_script("90_teardown.py")
    assert code == 1 and "Nothing was deleted." in out
    assert len(asked) == 1 and "kitdemo-fedrag-*" in asked[0]
    assert world.left() == before
    monkeypatch.setattr(builtins, "input", lambda prompt: "y")
    code, out = fakeaws.run_script("90_teardown.py")
    assert code == 0 and world.nothing_left()
