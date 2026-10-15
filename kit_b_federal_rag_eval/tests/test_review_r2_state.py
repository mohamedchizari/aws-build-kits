"""Round 2 review (money), written to fail on the code as it stood after round 1.

MAJOR 5   a damaged .state.json made every script die with a traceback.
MAJOR 6   when the knowledge base listing failed, teardown deleted the role and the bucket anyway.
MINOR 8   teardown exited 0 after its own listing had shown a "-fedrag-" bucket or role that
          belongs to another Region or prefix.
MINOR 9   teardown --dry-run exited 0.
MINOR 13  the guardrail was created before anything was written to .state.json.
MINOR 14  the RESULT line did not say when there was no usable state file.

The rules these tests pin:
  * no script ever deletes or overwrites a state file it cannot read;
  * with a damaged file every script stops with instructions; teardown goes on only when the
    place is named on the command line (--region and --prefix), and leaves the file where it is;
  * the clean check is never CLEAN while a damaged file is present;
  * teardown exits non-zero whenever its own listing still shows a kit-named or kit-tagged
    resource, and its --dry-run never exits 0;
  * with no usable state file the RESULT line says so and says it is no proof for another Region.
"""
from __future__ import annotations

import json

import pytest

import fakeaws
from fakeaws import ACCOUNT_A, BILLS, run_script
from kitlib import config
from kitlib import state as state_mod

WEST = {"AWS_REGION": "us-west-2"}


@pytest.fixture
def world(monkeypatch, tmp_path):
    fakeaws.make_corpus(tmp_path / "build")
    return fakeaws.install(monkeypatch, fakeaws.World())


def deploy(env=None, guardrail=True) -> None:
    code, out = run_script("30_deploy_kb.py", BILLS, env=env)
    assert code == 0, out
    if guardrail:
        code, out = run_script("40_create_guardrail.py", BILLS, env=env)
        assert code == 0, out


def result_line(out: str) -> str:
    lines = [line for line in out.splitlines() if line.startswith("RESULT:")]
    assert len(lines) == 1, out
    return lines[0]


def damage(how: str) -> bytes:
    path = config.state_path()
    text = path.read_text(encoding="utf-8")
    if how == "emptied":
        path.write_text("", encoding="utf-8")
    elif how == "truncated":
        path.write_text(text[:len(text) // 2], encoding="utf-8")
    elif how == "not an object":
        path.write_text('["a list", "not a record"]\n', encoding="utf-8")
    elif how == "binary":
        path.write_bytes(b"\xff\xfe\x00garbage")
    return path.read_bytes()


def write_eval_build(tmp_path) -> None:
    (tmp_path / "build" / "eval").mkdir(exist_ok=True)
    (tmp_path / "build" / "eval" / "eval_set.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "build" / "eval" / "eval_set_meta.json").write_text('{"label_sets": {}}', encoding="utf-8")
    (tmp_path / "build" / "corpus_manifest.json").write_text('{"mean_document_chars": 900}', encoding="utf-8")


# --- MAJOR 5 -----------------------------------------------------------------------------------------------

DAMAGE = ["emptied", "truncated", "not an object", "binary"]
STATE_READERS = [("00_check.py", []), ("00_check.py", ["--dry-run"]), ("30_deploy_kb.py", [BILLS]),
                 ("30_deploy_kb.py", ["--dry-run"]), ("40_create_guardrail.py", [BILLS]),
                 ("40_create_guardrail.py", ["--dry-run"]), ("50_run_eval.py", [BILLS]),
                 ("50_run_eval.py", ["--dry-run"]), ("90_teardown.py", ["--yes"]), ("90_teardown.py", ["--dry-run"]),
                 ("99_verify_clean.py", []), ("99_verify_clean.py", ["--dry-run"])]


@pytest.mark.parametrize("how", DAMAGE)
@pytest.mark.parametrize("script,args", STATE_READERS)
def test_a_damaged_state_file_stops_every_script_with_instructions_and_is_left_alone(world, tmp_path, how,
                                                                                    script, args):
    deploy(env=WEST)
    write_eval_build(tmp_path)
    before_bytes, before_world = damage(how), world.left()
    world.log.clear()

    code, out = run_script(script, *args)                  # a plain shell: default Region, no flags
    assert code != 0, out
    assert "Traceback" not in out and "JSONDecodeError" not in out
    assert "cannot be read" in out and "No script deletes or overwrites it" in out
    assert "--region" in out and "--prefix" in out and "99_verify_clean.py" in out
    assert config.state_path().read_bytes() == before_bytes            # not deleted, not rewritten
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("state")) == ["state.json"]
    assert world.left() == before_world                                # nothing was created or deleted
    assert not [c for c in world.log if c[3].startswith(("create_", "delete_", "put_", "start_"))]


def test_the_message_repeats_what_can_still_be_read_in_a_truncated_file(world):
    deploy(env=WEST, guardrail=False)
    damage("truncated")
    code, out = run_script("90_teardown.py", "--yes")
    assert code != 0
    assert "us-west-2" in out and "'kitdemo'" in out
    assert "python 90_teardown.py --region us-west-2 --prefix kitdemo" in out
    assert ACCOUNT_A not in out


@pytest.mark.parametrize("how", ["emptied", "truncated"])
def test_teardown_goes_on_when_the_place_is_named_on_the_command_line_and_leaves_the_file(world, how):
    deploy(env=WEST)
    before_bytes = damage(how)

    # naming only one of the two is not enough
    for args in (["--region", "us-west-2"], ["--prefix", "kitdemo"]):
        code, out = run_script("90_teardown.py", "--yes", *args)
        assert code != 0 and "cannot be read" in out and world.left()["knowledge_bases"]

    code, out = run_script("90_teardown.py", "--yes", "--region", "us-west-2", "--prefix", "kitdemo")
    assert world.nothing_left(), out
    assert config.state_path().read_bytes() == before_bytes
    line = result_line(out)
    assert "us-west-2" in line and "damaged" in line and "not proof" in line
    assert code != 0                       # the record is unreadable, so "everything recorded is gone" cannot be said
    assert "move it out of this folder yourself" in out


@pytest.mark.parametrize("how", DAMAGE)
def test_the_clean_check_is_never_clean_while_a_damaged_file_is_present(world, how):
    deploy(env=WEST)
    before_bytes = damage(how)
    for env in (None, WEST):                                # resources still there
        code, out = run_script("99_verify_clean.py", env=env)
        assert code == 1 and result_line(out).startswith("RESULT: NOT CLEAN"), out
    assert run_script("90_teardown.py", "--yes", "--region", "us-west-2", "--prefix", "kitdemo")[0] != 0
    assert world.nothing_left()
    for env in (None, WEST):                                # account empty, file still damaged
        code, out = run_script("99_verify_clean.py", env=env)
        assert code == 4, out
        line = result_line(out)
        assert line.startswith("RESULT: INCOMPLETE") and "cannot be read" in line
        assert "CLEAN" not in line.replace("INCOMPLETE", "")
    assert config.state_path().read_bytes() == before_bytes

    # the owner moves the file away by hand; only then can the place that is checked be CLEAN
    config.state_path().rename(config.state_path().with_name("kept-by-hand.json"))
    code, out = run_script("99_verify_clean.py", env=WEST)
    assert code == 0 and result_line(out).startswith("RESULT: CLEAN")


def test_explicit_flags_with_a_readable_state_file_are_still_compared_with_it(world):
    deploy()
    before = config.state_path().read_bytes()
    code, out = run_script("90_teardown.py", "--yes", "--region", "us-west-2", "--prefix", "kitdemo")
    assert code == 1 and "STOP" in out and "us-east-1" in out and "us-west-2" in out
    assert config.state_path().read_bytes() == before and world.left()["knowledge_bases"]
    code, out = run_script("90_teardown.py", "--yes", "--region", "us-east-1", "--prefix", "kitdemo")
    assert code == 0 and world.nothing_left()


def test_save_and_update_refuse_to_touch_a_damaged_file(tmp_path):
    config.state_path().write_text('{"bucket": "kitdemo-fedrag-corpus-x", "reg', encoding="utf-8")
    before = config.state_path().read_bytes()
    with pytest.raises(state_mod.StopHere):
        config.load_state()
    with pytest.raises(state_mod.StopHere):
        config.save_state({"bucket": "other"})
    with pytest.raises(state_mod.StopHere):
        config.update_state(role_name="r")
    assert config.state_path().read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["state.json"]
    assert config.state_file_status() == "damaged"
    config.state_path().unlink()
    assert config.state_file_status() == "absent" and config.load_state() == {}
    config.save_state({})
    assert config.state_file_status() == "empty"
    config.save_state({"bucket": "b"})
    assert config.state_file_status() == "ok"


# --- MAJOR 6 -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("with_state", [True, False])
def test_a_failed_knowledge_base_listing_keeps_the_role_and_the_bucket(world, with_state):
    deploy()
    if not with_state:
        config.state_path().unlink()
    before = world.left()
    world.fail[("bedrock-agent", "list_knowledge_bases")] = lambda: RuntimeError(
        "AccessDeniedException: not allowed to list knowledge bases")
    world.log.clear()
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 1, out
    assert world.left()["knowledge_bases"] == before["knowledge_bases"]
    assert world.left()["roles"] == before["roles"] and world.left()["buckets"] == before["buckets"]
    assert not world.calls("iam", "delete_role") and not world.calls("s3", "delete_bucket")
    assert "skipped the vector store, role and bucket" in out
    assert result_line(out).startswith("RESULT: NOT FINISHED")

    world.fail.clear()
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 0 and world.nothing_left(), out


def test_a_failed_data_source_listing_keeps_the_role_and_the_bucket(world):
    deploy(guardrail=False)
    world.fail[("bedrock-agent", "list_data_sources")] = lambda: RuntimeError("ThrottlingException: slow down")
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 1, out
    assert world.left()["knowledge_bases"] and world.left()["roles"] and world.left()["buckets"]


# --- MINOR 8 -----------------------------------------------------------------------------------------------

def test_teardown_exits_non_zero_when_its_listing_shows_a_bucket_and_role_of_another_region(world):
    """The reader's B06b: deployed in us-west-2, state file lost, teardown in a plain shell."""
    deploy(env=WEST, guardrail=False)
    config.state_path().unlink()
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 1, out
    assert "kitdemo-fedrag-corpus-********3333-us-west-2" in out and "kitdemo-fedrag-kb-role-us-west-2" in out
    assert "AWS_REGION=us-west-2" in out
    line = result_line(out)
    assert line.startswith("RESULT: NOT FINISHED") and "2 kit B resource(s)" in line
    assert "every delete call succeeded" not in out
    assert world.left()["knowledge_bases"]                      # nothing of the other Region was touched


def test_teardown_exits_non_zero_when_its_listing_shows_resources_under_another_prefix(world):
    """The reader's B25: deployed with KIT_PREFIX=oldpfx, state file lost, teardown with the default prefix."""
    deploy(env={"KIT_PREFIX": "oldpfx"}, guardrail=False)
    config.state_path().unlink()
    before = world.left()
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 1, out
    assert "oldpfx-fedrag-kb" in out and "KIT_PREFIX=oldpfx" in out
    assert result_line(out).startswith("RESULT: NOT FINISHED")
    assert world.left() == before


def test_teardown_exits_non_zero_when_a_tagged_guardrail_without_the_kit_name_is_left(world):
    """Tagged project=aws-kits, of a kind kit B creates, but not named "-fedrag-": found by its tag only."""
    world.guardrails[(ACCOUNT_A, "us-east-1", "handmade01")] = {"name": "made-by-hand", "versions": 0}
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 1, out
    assert "guardrail/handmade01" in out and "found by its tag" in out
    assert result_line(out).startswith("RESULT: NOT FINISHED") and "1 kit B resource(s)" in result_line(out)
    assert world.left()["guardrails"]                                 # it was reported, not deleted


def test_a_tagged_arn_the_services_own_listing_no_longer_holds_does_not_fail_the_teardown(world):
    """The tagging API may go on returning a resource for a while after it was deleted."""
    deploy()
    world.extra_tagged.append((ACCOUNT_A, "us-east-1", f"arn:aws:bedrock:us-east-1:{ACCOUNT_A}:knowledge-base/GONE000001"))
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 0, out
    assert "knowledge-base/GONE000001" in out and "counted as deleted" in out
    code, out = run_script("99_verify_clean.py")                      # the clean check still counts every tag
    assert code == 1 and "knowledge-base/GONE000001" in out


def test_a_tagged_resource_of_a_kind_kit_b_never_creates_does_not_fail_the_teardown(world):
    world.extra_tagged.append((ACCOUNT_A, "us-east-1",
                               f"arn:aws:sagemaker:us-east-1:{ACCOUNT_A}:endpoint/kitdemo-gpu-endpoint"))
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 0, out
    assert "endpoint/kitdemo-gpu-endpoint" in out and "another kit" in out


def test_teardown_exits_non_zero_when_it_cannot_list_what_is_left(world):
    deploy(guardrail=False)
    config.state_path().unlink()
    world.fail[("resourcegroupstaggingapi", "get_resources")] = lambda: RuntimeError("AccessDeniedException: no")
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 1 and "could not list" in out.lower()


def test_a_teardown_after_an_older_state_copy_was_put_back_does_not_exit_zero(world):
    """The reader's B09b: the state file is a copy from before the current deploy."""
    deploy(guardrail=False)
    assert run_script("90_teardown.py", "--yes")[0] == 0
    assert run_script("99_verify_clean.py")[0] == 0
    old_copy = config.state_path().read_bytes()
    deploy(env=WEST, guardrail=False)
    config.state_path().write_bytes(old_copy)
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 1 and "us-west-2" in out, out
    code, out = run_script("99_verify_clean.py")
    assert code == 1 and result_line(out).startswith("RESULT: NOT CLEAN")


# --- MINOR 9 -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("deployed", [True, False])
def test_teardown_dry_run_never_exits_zero(world, deployed):
    if deployed:
        deploy()
    before = world.left()
    world.log.clear()
    code, out = run_script("90_teardown.py", "--dry-run")
    assert code == 5, out
    assert "NOTHING WAS DELETED" in result_line(out) and "exit code 5" in out.lower()
    assert world.left() == before and world.log == []


# --- MINOR 13 ----------------------------------------------------------------------------------------------

def test_the_guardrail_is_on_record_before_the_call_that_creates_it(world):
    seen = {}

    original = fakeaws.FakeClient._bedrock__create_guardrail

    def create_then_die(self, **params):
        result = original(self, **params)
        seen["state_at_create"] = json.loads(config.state_path().read_text(encoding="utf-8"))
        raise RuntimeError("the process died right after the guardrail was created")

    fakeaws.FakeClient._bedrock__create_guardrail = create_then_die
    try:
        code, out = run_script("40_create_guardrail.py", BILLS, env=WEST)
    finally:
        fakeaws.FakeClient._bedrock__create_guardrail = original
    assert code == 1
    assert world.left()["guardrails"]                                     # it exists in us-west-2
    recorded = seen["state_at_create"]
    assert (recorded["account_id"], recorded["region"], recorded["prefix"]) == (ACCOUNT_A, "us-west-2", "kitdemo")
    assert state_mod.has_record(recorded) and recorded["guardrail_name"] == "kitdemo-fedrag-grounding"

    # a plain shell afterwards: teardown stops, the clean check is not a pass, and the right place cleans up
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 1 and "STOP" in out and "us-west-2" in out
    code, out = run_script("99_verify_clean.py")
    assert code == 4 and result_line(out).startswith("RESULT: INCOMPLETE")
    code, out = run_script("90_teardown.py", "--yes", env=WEST)
    assert code == 0 and world.nothing_left(), out


def test_a_guardrail_that_is_only_on_record_as_pending_is_not_used_by_the_evaluation(world, tmp_path):
    deploy(guardrail=False)
    write_eval_build(tmp_path)
    config.update_state(guardrail_id=state_mod.PENDING, guardrail_name="kitdemo-fedrag-grounding")
    code, out = run_script("50_run_eval.py", BILLS)
    assert code == 1 and "Run 40_create_guardrail.py" in out
    assert not world.calls("bedrock-runtime")
    code, out = run_script("40_create_guardrail.py", BILLS)               # running it again finishes the job
    assert code == 0, out
    saved = json.loads(config.state_path().read_text(encoding="utf-8"))
    assert saved["guardrail_id"] != state_mod.PENDING and saved["guardrail_version"] == "1"


# --- MINOR 14 ----------------------------------------------------------------------------------------------

def test_with_no_state_file_the_clean_result_says_so_and_says_it_is_no_proof_elsewhere(world):
    code, out = run_script("99_verify_clean.py")
    assert code == 0, out
    line = result_line(out)
    assert line.startswith("RESULT: CLEAN")
    assert "NO STATE FILE" in line and "not proof for any other Region" in line


def test_with_an_empty_state_file_the_clean_result_says_the_same(world):
    config.save_state({})
    code, out = run_script("99_verify_clean.py")
    assert code == 0, out
    line = result_line(out)
    assert "records no deploy" in line and "not proof for any other Region" in line


def test_with_a_state_file_that_names_the_place_the_clean_result_does_not_carry_the_warning(world):
    deploy()
    assert run_script("90_teardown.py", "--yes")[0] == 0
    code, out = run_script("99_verify_clean.py")
    assert code == 0, out
    line = result_line(out)
    assert "NO STATE FILE" not in line and "records no deploy" not in line
    assert "the place .state.json names" in line


def test_with_no_state_file_the_teardown_result_says_so_too(world):
    deploy(guardrail=False)
    config.state_path().unlink()
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 0 and world.nothing_left(), out
    line = result_line(out)
    assert "NO STATE FILE" in line and "not proof for any other Region" in line
    assert not config.state_path().exists()


def test_the_wrong_region_with_no_state_file_and_only_a_guardrail_is_the_stated_limit(world):
    """What is left of the lost-state limit: nothing global gives the other Region away. The check
    says CLEAN for the Region it looked in, and the RESULT line carries the warning."""
    code, out = run_script("40_create_guardrail.py", BILLS, env=WEST)
    assert code == 0, out
    config.state_path().unlink()
    code, out = run_script("99_verify_clean.py")
    assert code == 0
    assert "NO STATE FILE" in result_line(out) and world.left()["guardrails"]
