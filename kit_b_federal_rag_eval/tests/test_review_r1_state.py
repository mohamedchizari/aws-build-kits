"""Round 1 review, BLOCKER 3 and the shared state rule: tests written to fail on the code as reviewed.

The scripts are run as a user runs them, against the stateful fake account in
fakeaws.py. What is checked:

  * .state.json records the account, the Region and the name prefix of the deploy;
  * every script that reads it stops, changing nothing, when any of the three
    differs from the current settings or the current caller identity;
  * teardown never drops the record of a resource it did not delete or see gone;
  * the clean check says which account, Region and prefix it checked, is never
    CLEAN while the state file names somewhere it did not check, treats every
    tagged or "-fedrag-" named resource as a leftover, and its --dry-run does
    not exit 0;
  * a second deploy does not overwrite the record of a first one;
  * no script prints more than the last four digits of the account id.
"""
from __future__ import annotations

import json

import pytest

import fakeaws
from fakeaws import ACCOUNT_A, ACCOUNT_B, BILLS, run_script
from kitlib import config

WEST = {"AWS_REGION": "us-west-2"}
OTHER_PREFIX = {"KIT_PREFIX": "kitnew"}


@pytest.fixture
def world(monkeypatch, tmp_path):
    fakeaws.make_corpus(tmp_path / "build")
    return fakeaws.install(monkeypatch, fakeaws.World())


def deploy_all(env=None) -> str:
    code, out = run_script("30_deploy_kb.py", BILLS, env=env)
    assert code == 0, out
    code, out2 = run_script("40_create_guardrail.py", BILLS, env=env)
    assert code == 0, out2
    return out + out2


def state() -> dict:
    return json.loads(config.state_path().read_text(encoding="utf-8"))


def result_line(out: str) -> str:
    lines = [line for line in out.splitlines() if line.startswith("RESULT:")]
    assert len(lines) == 1, out
    return lines[0]


# --- the record ---------------------------------------------------------------------------------------

def test_the_state_file_records_account_region_and_prefix(world):
    deploy_all()
    saved = state()
    assert (saved["account_id"], saved["region"], saved["prefix"]) == (ACCOUNT_A, "us-east-1", "kitdemo")
    for key in ("bucket", "role_name", "knowledge_base_id", "data_source_id", "guardrail_id"):
        assert saved.get(key), key


def test_a_normal_cycle_ends_clean_and_says_where_it_looked(world):
    deploy_all()
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 0, out
    assert world.nothing_left()
    saved = state()
    assert not any(key in saved for key in ("bucket", "role_name", "knowledge_base_id", "guardrail_id"))
    assert [(h["account_id"], h["region"], h["prefix"]) for h in saved["history"]] == [
        (ACCOUNT_A, "us-east-1", "kitdemo")]

    code, out = run_script("99_verify_clean.py")
    assert code == 0, out
    line = result_line(out)
    assert line.startswith("RESULT: CLEAN")
    assert "********3333" in line and "us-east-1" in line and "'kitdemo'" in line
    assert world.calls("sts", "get_caller_identity")
    assert state()["history"][0].get("verified_clean_at")


def test_the_clean_check_without_any_state_file_still_names_what_it_checked(world):
    code, out = run_script("99_verify_clean.py")
    assert code == 0, out
    line = result_line(out)
    assert line.startswith("RESULT: CLEAN") and "********3333" in line and "us-east-1" in line and "'kitdemo'" in line


# --- BLOCKER 3, scenario D: other account -----------------------------------------------------------------

def test_teardown_under_another_account_stops_and_keeps_everything(world):
    deploy_all()
    before_state, before_world = config.state_path().read_bytes(), world.left()
    world.account = ACCOUNT_B
    calls_before = len(world.log)

    code, out = run_script("90_teardown.py", "--yes")
    assert code == 1
    assert "STOP" in out and "********3333" in out and "********9012" in out
    assert config.state_path().read_bytes() == before_state           # the record was not touched
    assert world.left() == before_world                              # nothing was deleted
    made = [(entry[2], entry[3]) for entry in world.log[calls_before:]]
    assert made == [("sts", "get_caller_identity")]                  # it asked who it is, then stopped

    code, out = run_script("99_verify_clean.py")
    assert code == 4, out
    line = result_line(out)
    assert line.startswith("RESULT: INCOMPLETE") and "CLEAN" not in line.replace("INCOMPLETE", "")
    assert "********3333" in out and "********9012" in line


# --- BLOCKER 3, scenario B: AWS_REGION exported in the shell --------------------------------------------------

def test_teardown_in_another_region_stops_and_says_which_setting_wins(world):
    deploy_all()
    before_state, before_world = config.state_path().read_bytes(), world.left()

    code, out = run_script("90_teardown.py", "--yes", env=WEST)
    assert code == 1
    assert "STOP" in out and "us-east-1" in out and "us-west-2" in out
    assert "AWS_REGION" in out and "overrides config.env" in out
    assert config.state_path().read_bytes() == before_state
    assert world.left() == before_world

    # The clean check in the wrong Region sees the two global things and is NOT CLEAN.
    code, out = run_script("99_verify_clean.py", env=WEST)
    assert code == 1 and result_line(out).startswith("RESULT: NOT CLEAN")

    # The owner deletes those two in the console, as the old output advised. It must still not be CLEAN:
    # the knowledge base, data source and guardrail are alive in us-east-1.
    world.buckets.clear()
    world.roles.clear()
    code, out = run_script("99_verify_clean.py", env=WEST)
    assert code == 4, out
    line = result_line(out)
    assert line.startswith("RESULT: INCOMPLETE") and "us-west-2" in line
    assert "us-east-1" in out
    assert world.left()["knowledge_bases"] and world.left()["guardrails"]


# --- BLOCKER 3, scenario C: KIT_PREFIX changed ------------------------------------------------------------------

def test_teardown_under_another_prefix_stops(world):
    deploy_all()
    before_state, before_world = config.state_path().read_bytes(), world.left()
    code, out = run_script("90_teardown.py", "--yes", env=OTHER_PREFIX)
    assert code == 1
    assert "STOP" in out and "'kitdemo'" in out and "'kitnew'" in out
    assert config.state_path().read_bytes() == before_state and world.left() == before_world


def test_the_clean_check_counts_every_fedrag_resource_whatever_the_prefix(world):
    deploy_all()
    code, out = run_script("99_verify_clean.py", env=OTHER_PREFIX)
    assert code == 1 and result_line(out).startswith("RESULT: NOT CLEAN")
    assert "kitdemo-fedrag-corpus-" in out and "kitdemo-fedrag-kb-role-" in out
    assert "other kit or yours" not in out

    # The owner deletes the knowledge base and the guardrail. The bucket and the role are still kit B's.
    world.kbs.clear()
    world.data_sources.clear()
    world.guardrails.clear()
    code, out = run_script("99_verify_clean.py", env=OTHER_PREFIX)
    assert code == 1 and result_line(out).startswith("RESULT: NOT CLEAN")

    # With the state file lost as well, the names alone still give it away.
    config.state_path().unlink()
    code, out = run_script("99_verify_clean.py", env=OTHER_PREFIX)
    assert code == 1 and result_line(out).startswith("RESULT: NOT CLEAN")
    assert "kitdemo-fedrag-corpus-" in out


def test_the_clean_check_is_incomplete_while_the_state_names_another_prefix(world):
    deploy_all()
    for store in (world.kbs, world.data_sources, world.guardrails, world.buckets, world.roles):
        store.clear()                                    # everything deleted by hand
    code, out = run_script("99_verify_clean.py", env=OTHER_PREFIX)
    assert code == 4 and result_line(out).startswith("RESULT: INCOMPLETE")
    assert "'kitdemo'" in out and "'kitnew'" in out

    # Checked with the recorded settings it is clean, but the record is still there until teardown clears it.
    code, out = run_script("99_verify_clean.py")
    assert code == 0 and result_line(out).startswith("RESULT: CLEAN")
    code, out = run_script("90_teardown.py", "--yes")    # confirms every recorded resource is absent
    assert code == 0, out
    assert "knowledge_base_id" not in state() and len(state()["history"]) == 1


def test_a_tagged_resource_of_any_kind_is_never_clean(world):
    world.extra_tagged.append((ACCOUNT_A, "us-east-1",
                               f"arn:aws:sagemaker:us-east-1:{ACCOUNT_A}:endpoint/kitdemo-gpu-endpoint"))
    code, out = run_script("99_verify_clean.py")
    assert code == 1 and result_line(out).startswith("RESULT: NOT CLEAN")
    assert "endpoint/kitdemo-gpu-endpoint" in out and "project=aws-kits" in out


# --- scenario N: a second deploy must not overwrite the record of the first -------------------------------------

@pytest.mark.parametrize("change", ["region", "prefix", "account"])
def test_a_second_deploy_elsewhere_is_refused_and_the_first_record_survives(world, change):
    deploy_all()
    before_state, before_world = config.state_path().read_bytes(), world.left()
    env = {"region": WEST, "prefix": OTHER_PREFIX, "account": None}[change]
    if change == "account":
        world.account = ACCOUNT_B
    for script in ("30_deploy_kb.py", "40_create_guardrail.py"):
        code, out = run_script(script, BILLS, env=env)
        assert code == 1, out
        assert "STOP" in out and "90_teardown.py" in out
    assert config.state_path().read_bytes() == before_state
    assert world.left() == before_world                              # and nothing new was created


def test_a_second_deploy_in_the_same_place_is_a_re_run(world):
    deploy_all()
    first = state()["knowledge_base_id"]
    deploy_all()
    assert state()["knowledge_base_id"] == first and len(world.kbs) == 1 and len(world.guardrails) == 1


def test_a_deploy_after_a_finished_teardown_starts_a_new_record_and_keeps_the_history(world):
    deploy_all()
    assert run_script("90_teardown.py", "--yes")[0] == 0
    deploy_all(env=WEST)
    saved = state()
    assert saved["region"] == "us-west-2" and saved["knowledge_base_id"]
    assert [h["region"] for h in saved["history"]] == ["us-east-1"]


# --- every other script that reads the state stops too -----------------------------------------------------------

@pytest.mark.parametrize("script,args", [("00_check.py", []), ("50_run_eval.py", [BILLS]),
                                         ("50_run_eval.py", ["--dry-run"]), ("90_teardown.py", ["--dry-run"]),
                                         ("30_deploy_kb.py", ["--dry-run"])])
def test_scripts_that_read_the_state_stop_on_a_region_mismatch(world, tmp_path, script, args):
    deploy_all()
    world.log.clear()                                    # the deploy's own two test queries do not count
    (tmp_path / "build" / "eval").mkdir()
    (tmp_path / "build" / "eval" / "eval_set.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "build" / "eval" / "eval_set_meta.json").write_text('{"label_sets": {}}', encoding="utf-8")
    (tmp_path / "build" / "corpus_manifest.json").write_text('{"mean_document_chars": 900}', encoding="utf-8")
    code, out = run_script(script, *args, env=WEST)
    assert code == 1, out
    assert "STOP" in out and "us-east-1" in out and "us-west-2" in out and "overrides config.env" in out
    assert not world.calls("bedrock-agent-runtime") and not world.calls("bedrock-runtime")


def test_run_eval_stops_under_another_account_before_any_billed_call(world, tmp_path):
    deploy_all()
    (tmp_path / "build" / "eval").mkdir()
    (tmp_path / "build" / "eval" / "eval_set.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "build" / "eval" / "eval_set_meta.json").write_text('{"label_sets": {}}', encoding="utf-8")
    (tmp_path / "build" / "corpus_manifest.json").write_text('{"mean_document_chars": 900}', encoding="utf-8")
    world.account = ACCOUNT_B
    world.log.clear()
    code, out = run_script("50_run_eval.py", BILLS)
    assert code == 1 and "STOP" in out and "********3333" in out and "********9012" in out
    assert not world.calls("bedrock-agent-runtime") and not world.calls("bedrock-runtime")
    assert not (tmp_path / "results").exists()


def test_a_state_file_that_does_not_say_where_it_was_deployed_stops_teardown(world):
    config.save_state({"knowledge_base_id": "KB00000001", "bucket": "kitdemo-fedrag-corpus-x"})
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 1 and "STOP" in out and "does not record" in out
    assert state() == {"knowledge_base_id": "KB00000001", "bucket": "kitdemo-fedrag-corpus-x"}


# --- teardown keeps the record of what it could not delete or confirm absent ---------------------------------------

def test_teardown_keeps_the_record_of_a_bucket_it_could_not_delete(world):
    deploy_all()
    bucket = state()["bucket"]
    world.fail[("s3", "delete_bucket")] = lambda: RuntimeError("AccessDenied: not allowed to delete the bucket")
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 1
    saved = state()
    assert saved["bucket"] == bucket and "history" not in saved
    assert (saved["account_id"], saved["region"], saved["prefix"]) == (ACCOUNT_A, "us-east-1", "kitdemo")
    assert "knowledge_base_id" not in saved and "guardrail_id" not in saved      # those were seen gone
    assert "kept" in out and bucket.replace(ACCOUNT_A, "********3333") in out

    world.fail.clear()
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 0, out
    assert "bucket" not in state() and world.nothing_left()


def test_teardown_keeps_the_record_of_what_it_could_not_confirm_absent(world):
    deploy_all()
    guardrail = state()["guardrail_id"]
    world.fail[("bedrock", "list_guardrails")] = lambda: RuntimeError("AccessDeniedException: cannot list")
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 1
    assert state()["guardrail_id"] == guardrail          # not listed, so not confirmed, so still recorded
    assert world.left()["guardrails"]


def test_teardown_never_prints_that_the_state_file_was_removed(world):
    deploy_all()
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 0 and ".state.json was removed" not in out
    assert config.state_path().is_file()


# --- the clean check ------------------------------------------------------------------------------------------------

def test_the_clean_check_dry_run_does_not_exit_zero_and_says_why(world):
    code, out = run_script("99_verify_clean.py", "--dry-run")
    assert code == 5
    assert "DRY-RUN" in out and "nothing was checked" in out.lower() and "exit code 5" in out.lower()
    assert world.log == []                                            # and it really made no call


def test_the_clean_check_is_incomplete_until_every_place_in_the_history_was_checked(world):
    deploy_all()
    assert run_script("90_teardown.py", "--yes")[0] == 0
    deploy_all(env=WEST)
    assert run_script("90_teardown.py", "--yes", env=WEST)[0] == 0
    assert world.nothing_left() and len(state()["history"]) == 2

    code, out = run_script("99_verify_clean.py", env=WEST)
    assert code == 4 and result_line(out).startswith("RESULT: INCOMPLETE")
    assert "us-east-1" in out and "AWS_REGION=us-east-1" in out
    code, out = run_script("99_verify_clean.py")                     # now the other place
    assert code == 0 and result_line(out).startswith("RESULT: CLEAN")
    code, out = run_script("99_verify_clean.py", env=WEST)           # and both are on record as checked
    assert code == 0, out


def test_the_clean_check_cannot_be_clean_when_sts_fails(world):
    world.fail[("sts", "get_caller_identity")] = lambda: RuntimeError("ExpiredToken: the security token expired")
    code, out = run_script("99_verify_clean.py")
    assert code == 4 and result_line(out).startswith("RESULT: INCOMPLETE")
    assert "account unknown" in result_line(out)


def test_the_clean_check_finds_a_recorded_knowledge_base_that_was_renamed(world):
    deploy_all()
    kb_key = next(iter(world.kbs))
    world.kbs[kb_key]["name"] = "renamed-by-hand"
    world.guardrails.clear(); world.buckets.clear(); world.roles.clear(); world.data_sources.clear()
    code, out = run_script("99_verify_clean.py")
    assert code == 1 and "renamed-by-hand" in out


# --- the account id on screen ------------------------------------------------------------------------------------------

def test_no_script_prints_more_than_the_last_four_digits_of_the_account_id(world, tmp_path):
    outputs = [deploy_all()]
    outputs.append(run_script("00_check.py")[1])
    outputs.append(run_script("99_verify_clean.py")[1])
    outputs.append(run_script("90_teardown.py", "--yes", env=WEST)[1])
    outputs.append(run_script("30_deploy_kb.py", BILLS, env=OTHER_PREFIX)[1])
    world.fail[("s3", "delete_bucket")] = lambda: RuntimeError(
        f"AccessDenied: User: arn:aws:iam::{ACCOUNT_A}:user/kit-tester is not authorized")
    outputs.append(run_script("90_teardown.py", "--yes")[1])
    world.fail.clear()
    outputs.append(run_script("90_teardown.py", "--yes")[1])
    outputs.append(run_script("99_verify_clean.py")[1])
    everything = "\n".join(outputs)
    assert ACCOUNT_A not in everything
    assert "********3333" in everything
    assert ACCOUNT_A in config.state_path().read_text(encoding="utf-8")     # the local state file has it in full


# --- the scenarios the review found correct must stay correct ---------------------------------------------------

def test_an_opensearch_collection_gives_exit_code_3_and_a_warning(world):
    world.collections[(ACCOUNT_A, "us-east-1", "abc123")] = "someone-elses-collection"
    code, out = run_script("99_verify_clean.py")
    assert code == 3 and "OpenSearch Serverless collection" in out and "$11.52 a day" in out
    assert result_line(out).startswith("RESULT: no kit resource")


@pytest.mark.parametrize("service,operation", [
    ("s3", "list_buckets"), ("iam", "list_roles"), ("bedrock-agent", "list_knowledge_bases"),
    ("bedrock", "list_guardrails"), ("s3vectors", "list_vector_buckets"),
    ("resourcegroupstaggingapi", "get_resources"), ("opensearchserverless", "list_collections")])
def test_the_clean_check_is_never_clean_when_a_listing_fails(world, service, operation):
    world.fail[(service, operation)] = lambda: RuntimeError("AccessDeniedException: not allowed")
    code, out = run_script("99_verify_clean.py")
    assert code == 4 and result_line(out).startswith("RESULT: INCOMPLETE") and "COULD NOT CHECK" in out


def test_a_lost_state_file_does_not_hide_anything_from_teardown_or_the_clean_check(world):
    deploy_all()
    config.state_path().unlink()
    code, out = run_script("99_verify_clean.py")
    assert code == 1 and result_line(out).startswith("RESULT: NOT CLEAN")
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 0, out
    assert world.nothing_left() and not config.state_path().exists()
    assert run_script("99_verify_clean.py")[0] == 0


def test_an_s3_vectors_deploy_is_found_and_removed_after_the_state_is_lost_and_the_type_setting_changed(world):
    assert run_script("30_deploy_kb.py", BILLS, env={"KB_TYPE": "s3vectors"})[0] == 0
    assert world.vector_buckets
    config.state_path().unlink()
    code, out = run_script("90_teardown.py", "--yes", env={"KB_TYPE": "managed"})
    assert code == 0, out
    assert world.nothing_left()


def test_a_deploy_that_crashed_half_way_is_recorded_and_can_be_torn_down(world):
    world.fail[("bedrock-agent", "create_data_source")] = lambda: RuntimeError("ValidationException: boom")
    code, out = run_script("30_deploy_kb.py", BILLS)
    assert code == 1 and "FAILED:" in out
    saved = state()
    assert saved["knowledge_base_id"] and saved["bucket"] and saved["account_id"] == ACCOUNT_A
    # Since round 4 the data source's fixed name is on record before the call that creates it. The call
    # failed, so its id is the placeholder; teardown confirms that nothing by that name exists and clears it.
    assert (saved["data_source_id"], saved["data_source_name"]) == ("not-known-yet", "kitdemo-fedrag-s3-source")
    world.fail.clear()
    assert run_script("90_teardown.py", "--yes")[0] == 0
    assert world.nothing_left() and run_script("99_verify_clean.py")[0] == 0


def test_a_crash_right_after_a_create_call_cannot_leave_an_unrecorded_resource(world):
    world.fail[("s3", "put_bucket_tagging")] = lambda: RuntimeError("AccessDenied: tagging not allowed")
    code, out = run_script("30_deploy_kb.py", BILLS)
    assert code == 1
    assert world.left()["buckets"] and state()["bucket"] == world.left()["buckets"][0]   # created AND recorded
    world.fail.clear()
    assert run_script("90_teardown.py", "--yes")[0] == 0
    assert world.nothing_left() and "bucket" not in state()


def test_a_record_of_something_that_was_never_created_is_cleared_by_teardown(world):
    world.fail[("s3", "create_bucket")] = lambda: RuntimeError("AccessDenied: cannot create buckets")
    code, out = run_script("30_deploy_kb.py", BILLS)
    assert code == 1 and state()["bucket"] and world.nothing_left()
    world.fail.clear()
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 0, out
    assert "bucket" not in state() and len(state()["history"]) == 1
    assert run_script("99_verify_clean.py")[0] == 0


def test_a_teardown_that_confirms_nothing_does_not_rewrite_the_state_file(world):
    deploy_all()
    before = config.state_path().read_bytes()
    for operation in (("s3", "list_buckets"), ("iam", "list_roles"), ("bedrock-agent", "list_knowledge_bases"),
                      ("bedrock", "list_guardrails")):
        world.fail[operation] = lambda: RuntimeError("AccessDeniedException: cannot list")
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 1 and "KEPT IN .state.json" in out
    assert config.state_path().read_bytes() == before


def test_the_recorded_guardrail_thresholds_are_the_guardrails_own(world):
    """Not asked for by the review: a guardrail that exists already keeps its thresholds, so the record
    (and the results table that quotes it) must not show the thresholds of the current settings."""
    assert run_script("40_create_guardrail.py", BILLS)[0] == 0
    assert (state()["grounding_threshold"], state()["relevance_threshold"]) == (0.7, 0.7)
    saved = state()
    saved.pop("guardrail_version")                       # as after a lost or hand-edited state file
    config.save_state(saved)
    code, out = run_script("40_create_guardrail.py", BILLS, env={"GROUNDING_THRESHOLD": "0.9"})
    assert code == 0, out
    assert state()["grounding_threshold"] == 0.7 and "not the 0.9 in your settings" in out


def test_the_state_file_is_replaced_in_one_step_and_leaves_no_scratch_file(tmp_path):
    config.save_state({"bucket": "a"})
    config.update_state(role_name="b", bucket=None)
    assert state() == {"role_name": "b"}
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.json"]
