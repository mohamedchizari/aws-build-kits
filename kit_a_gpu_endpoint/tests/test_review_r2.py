"""Tests added after the second independent review of 2026-10-07 (round 2). One section per finding.

Two readers attacked the kit after its first fixes: one drove the real scripts as processes against a
stateful fake account (the "money" review, sequences A00 to A25), one checked every printed number (the
"numbers" review). Every finding has tests here that were written before its fix. Run against a scratch
copy of the code as reviewed, 43 of the 50 tests in this file fail. The 7 that pass there are the five
whose name ends in "_control", which must pass before and after, and two parametrised cases of
damaged-file detection that the reviewed code already handled. One test was added after the fixes (the
log group of a tagged endpoint with any name; it fails on the reviewed code too), and three were
tightened after deliberate breakages of the fixed code got past them.

The scenarios use the plain multi-Region fake in conftest.py (World). Nothing here touches AWS.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re

import pytest

import kitlib
import streamstats
from conftest import (ACCOUNT, KIT_DIR, OTHER_ACCOUNT, OTHER_REGION, REGION, FakeAwsError, FakeClock, Lines, World,
                      deploy_into, load_script, world_aws)

LOG_ROOT = "/aws/sagemaker/Endpoints/"
STAMP = r"20\d\d-\d\d-\d\dT\d\d:\d\d:\d\dZ"


def config_for(**environ):
    return kitlib.load_config(environ=environ, env_file=KIT_DIR / "does-not-exist.env")


def ns(state_path, **overrides):
    values = dict(state_path=state_path, price_per_hour=None, max_hours=None, no_wait=False,
                  wait_timeout_minutes=45.0, i_understand_this_bills=False, skip_hf_check=True,
                  ignore_deadline=False, endpoint_name=None, keep_logs=False, allow_logs=False,
                  max_tag_lookups=300, region=None, prefix=None, set="SM_VLLM_MAX_NUM_SEQS=8")
    values.update(overrides)
    return argparse.Namespace(**values)


def teardown(state_path, cfg, aws, **overrides):
    out, clock = Lines(), FakeClock()
    code = load_script("90_teardown").run(ns(state_path, **overrides), cfg, aws, out, sleep=clock.sleep, clock=clock)
    return code, out


def verify(state_path, cfg, aws, **overrides):
    out = Lines()
    return load_script("99_verify_clean").run(ns(state_path, **overrides), cfg, aws, out), out


def result_line(out: Lines) -> str:
    found = [line for line in out if line.startswith("RESULT:")]
    assert len(found) == 1, f"expected exactly one RESULT line, got {found}"
    return found[0]


def last_line(out: Lines) -> str:
    return [line for line in out if line.strip()][-1]


def deploy_with_logs(world, cfg, state_path, region=REGION, account=ACCOUNT):
    state = deploy_into(world, cfg, state_path, region=region, account=account)
    world.place(account, region)["logs"].add(cfg.log_group_name)  # SageMaker creates it with the endpoint
    return state


def folder_listing(state_path):
    return sorted(p.name for p in state_path.parent.iterdir())


# =====================================================================================================
# Money review, BLOCKER 2 (sequences A17 and A25): the endpoint was found by tag under another prefix
# and deleted, its log group was left, and the clean check said CLEAN, exit 0.
# =====================================================================================================

def test_r2_b2_teardown_deletes_the_log_group_of_an_endpoint_found_by_tag_under_another_prefix(cfg, state_path):
    world = World()
    old = config_for(KIT_PREFIX="oldpfx")
    deploy_with_logs(world, old, state_path)
    state_path.unlink()                                   # the state file is lost; the shell uses the default prefix
    code, out = teardown(state_path, cfg, world_aws(world))
    here = world.place(ACCOUNT, REGION)
    assert not here["endpoints"] and not here["configs"] and not here["models"], "found by tag, as before"
    assert old.log_group_name not in here["logs"], "the log group of the endpoint that was deleted must go too"
    assert code == 0
    code, out = verify(state_path, cfg, world_aws(world))
    assert code == 0 and not here["logs"]


def test_r2_b2_clean_check_reports_a_log_group_left_under_another_prefix(cfg, state_path):
    """What the reviewer's sequence ended on: only the log group is left, and nothing with the current prefix."""
    world = World()
    world.place(ACCOUNT, REGION)["logs"].add(LOG_ROOT + "oldpfx-kita-endpoint")
    code, out = verify(state_path, cfg, world_aws(world))
    assert code == 1 and result_line(out).startswith("RESULT: NOT CLEAN")
    assert LOG_ROOT + "oldpfx-kita-endpoint" in out.text
    assert "CLEAN ONLY" not in out.text and "RESULT: CLEAN" not in out.text


def test_r2_b2_teardown_removes_what_the_clean_check_reports_so_the_two_do_not_point_at_each_other(cfg, state_path):
    world = World()
    world.place(ACCOUNT, REGION)["logs"].add(LOG_ROOT + "oldpfx-kita-endpoint")
    code, out = teardown(state_path, cfg, world_aws(world))
    assert code == 0 and not world.place(ACCOUNT, REGION)["logs"]
    assert verify(state_path, cfg, world_aws(world))[0] == 0


def test_r2_b2_log_group_of_a_tagged_endpoint_is_found_whatever_the_endpoint_is_called(cfg, state_path):
    """An endpoint that carries the kit's tags is the kit's, whatever its name. So is its log group."""
    world = World()
    here = world.place(ACCOUNT, REGION)
    here["endpoints"]["renamed-by-hand"] = {"status": "InService"}
    here["tags"][f"arn:aws:sagemaker:{REGION}:{ACCOUNT}:endpoint/renamed-by-hand"] = cfg.tags()
    here["logs"].add(LOG_ROOT + "renamed-by-hand")
    code, out = verify(state_path, cfg, world_aws(world))
    assert code == 1 and LOG_ROOT + "renamed-by-hand" in out.text and "4 resource" not in out.text
    assert "2 resource(s) remain" in result_line(out), "the endpoint and its log group"
    code, out = teardown(state_path, cfg, world_aws(world))
    assert code == 0 and not here["endpoints"] and not here["logs"]


def test_r2_b2_log_groups_that_are_not_this_kits_are_left_alone_control(cfg, state_path):
    world = World()
    strangers = {LOG_ROOT + "somebody-elses", LOG_ROOT + "kitadmin-endpoint", "/aws/lambda/oldpfx-kita-endpoint"}
    world.place(ACCOUNT, REGION)["logs"].update(strangers)
    code, out = teardown(state_path, cfg, world_aws(world))
    assert code == 0 and world.place(ACCOUNT, REGION)["logs"] == strangers
    assert world.operations("delete_log_group") == []
    assert verify(state_path, cfg, world_aws(world))[0] == 0


# =====================================================================================================
# Money review, BLOCKER 3 (sequence A09a): the live record has no account id and no ARN; signed in to
# another account the clean check said CLEAN, exit 0, with the endpoint billing in the first account.
# =====================================================================================================

def strip_account(state_path):
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state.pop("account_id")
    state["deploy"].pop("account_id", None)
    for resource in state["resources"]:
        resource["arn"] = None
    state_path.write_text(json.dumps(state), encoding="utf-8")


def test_r2_b3_clean_check_is_incomplete_when_the_live_record_has_no_account_id(cfg, state_path):
    world = World()
    deploy_with_logs(world, cfg, state_path)
    strip_account(state_path)
    code, out = verify(state_path, cfg, world_aws(world, REGION, OTHER_ACCOUNT))
    assert code == 1 and result_line(out).startswith("RESULT: INCOMPLETE")
    assert "no account id" in out.text and "ending 6666" in out.text
    assert "RESULT: CLEAN" not in out.text
    assert ACCOUNT not in out.text and OTHER_ACCOUNT not in out.text, "never a full account id"
    assert cfg.endpoint_name in world.place(ACCOUNT, REGION)["endpoints"], "the endpoint is still there, in the first account"


def test_r2_b3_same_file_in_the_right_account_still_reports_what_remains_control(cfg, state_path):
    world = World()
    deploy_with_logs(world, cfg, state_path)
    strip_account(state_path)
    code, out = verify(state_path, cfg, world_aws(world))
    assert code == 1 and result_line(out).startswith("RESULT: NOT CLEAN") and cfg.endpoint_name in out.text


# =====================================================================================================
# Money review, MAJOR 4 (sequences A07 and A08): a damaged state file stopped teardown for good while
# the endpoint billed; teardown said "run 99_verify_clean.py" and that script said "run 90_teardown.py".
# =====================================================================================================

def damage(state_path, how="emptied"):
    text = state_path.read_text(encoding="utf-8")
    state_path.write_text("" if how == "emptied" else text[:len(text) // 2], encoding="utf-8")
    return state_path.read_bytes()


def test_r2_m4_teardown_with_a_damaged_state_file_stops_and_says_exactly_how_to_go_on(cfg, state_path):
    world = World()
    there = config_for(AWS_REGION=OTHER_REGION)
    deploy_with_logs(world, there, state_path, region=OTHER_REGION)
    before, listing = damage(state_path), folder_listing(state_path)
    with pytest.raises(kitlib.KitError) as stop:
        teardown(state_path, cfg, world_aws(world))
    message = str(stop.value)
    assert "python 90_teardown.py --region <the Region you deployed in> --prefix <your KIT_PREFIX>" in message, \
        "the way out must be in the message"
    assert "python 99_verify_clean.py --region <same> --prefix <same>" in message
    assert "by hand" in message and "whats_running.py" in message
    assert state_path.read_bytes() == before and folder_listing(state_path) == listing
    assert world.operations("delete_") == []


def test_r2_m4_an_exported_region_is_not_the_explicit_route(cfg, state_path):
    """AWS_REGION in the shell is the hazard this guard exists for, so it does not unlock anything."""
    world = World()
    there = config_for(AWS_REGION=OTHER_REGION)
    deploy_with_logs(world, there, state_path, region=OTHER_REGION)
    before = damage(state_path)
    for flags in ({}, {"region": OTHER_REGION}, {"prefix": "kitdemo"}):
        with pytest.raises(kitlib.KitError, match="--region"):
            teardown(state_path, there, world_aws(world, OTHER_REGION), **flags)
    assert state_path.read_bytes() == before and world.operations("delete_") == []
    assert there.endpoint_name in world.place(ACCOUNT, OTHER_REGION)["endpoints"]


@pytest.mark.parametrize("how", ["emptied", "truncated"])
def test_r2_m4_teardown_with_explicit_region_and_prefix_proceeds_and_leaves_the_damaged_file(how, cfg, state_path):
    world = World()
    there = config_for(AWS_REGION=OTHER_REGION)
    deploy_with_logs(world, there, state_path, region=OTHER_REGION)
    before, listing = damage(state_path, how), folder_listing(state_path)
    code, out = teardown(state_path, there, world_aws(world, OTHER_REGION), region=OTHER_REGION, prefix="kitdemo")
    place = world.place(ACCOUNT, OTHER_REGION)
    assert not place["endpoints"] and not place["configs"] and not place["models"] and not place["logs"]
    assert state_path.read_bytes() == before, "a damaged state file is never rewritten"
    assert folder_listing(state_path) == listing, "and never renamed, set aside or deleted"
    assert code == 1, "with a damaged state file teardown cannot confirm the place, so it never exits 0"
    final = last_line(out)
    assert final.startswith("TEARDOWN NOT CONFIRMED") and state_path.name in final and "damaged" in final
    assert "by hand" in out.text and "99_verify_clean.py" in out.text


def test_r2_m4_clean_check_stays_incomplete_until_the_owner_removes_the_damaged_file_by_hand(cfg, state_path):
    world = World()
    there = config_for(AWS_REGION=OTHER_REGION)
    deploy_with_logs(world, there, state_path, region=OTHER_REGION)
    before = damage(state_path)
    teardown(state_path, there, world_aws(world, OTHER_REGION), region=OTHER_REGION, prefix="kitdemo")
    code, out = verify(state_path, there, world_aws(world, OTHER_REGION), region=OTHER_REGION, prefix="kitdemo")
    assert code == 1 and result_line(out).startswith("RESULT: INCOMPLETE")
    assert "by hand" in out.text and "--region" in out.text, "it must say how to end the INCOMPLETE"
    assert "Run python 90_teardown.py" not in result_line(out)
    assert state_path.read_bytes() == before
    state_path.unlink()                                   # the owner removes it by hand
    code, out = verify(state_path, there, world_aws(world, OTHER_REGION), region=OTHER_REGION, prefix="kitdemo")
    assert code == 0 and "NO USABLE STATE FILE" in result_line(out)


@pytest.mark.parametrize("content", ["", "{", "[]", '"text"', "null", "{}", '{"resources": "none"}',
                                     '{"resources": [], "deploy": 5}', '{"resources": [7]}'])
def test_r2_m4_a_file_that_is_not_a_state_object_counts_as_damaged(content, state_path):
    state_path.write_text(content, encoding="utf-8")
    with pytest.raises(kitlib.KitError):
        kitlib.load_state(state_path)


def test_r2_m4_no_script_and_no_helper_overwrites_a_damaged_state_file(cfg, state_path, tmp_path):
    world = World()
    state_path.write_text("{ not json", encoding="utf-8")
    before = state_path.read_bytes()
    with pytest.raises(kitlib.KitError, match="[Rr]efus"):
        kitlib.save_state(kitlib.empty_state(cfg, ACCOUNT), state_path)
    assert state_path.read_bytes() == before
    clock = FakeClock()
    for name, extra in (("10_deploy", {"i_understand_this_bills": True}),
                        ("70_change_one_setting", {"i_understand_this_bills": True})):
        with pytest.raises(kitlib.KitError):
            load_script(name).run(ns(state_path, **extra), cfg, world_aws(world), Lines(), sleep=clock.sleep, clock=clock)
        assert state_path.read_bytes() == before, f"{name} changed a damaged state file"
    assert world.operations("create_") == [], "nothing may be created while the state file is unusable"
    assert folder_listing(state_path) == [state_path.name]


def test_r2_m4_a_truncated_state_file_still_gives_its_region_as_a_hint(cfg, state_path):
    """Sequence A08: the Region is still readable in what is left of the file. The clean check looks there
    too (it is read-only), and the stop message of teardown names it."""
    world = World()
    there = config_for(AWS_REGION=OTHER_REGION)
    clock = FakeClock()
    assert load_script("10_deploy").run(ns(state_path, i_understand_this_bills=True, price_per_hour=1.0), there,
                                        world_aws(world, OTHER_REGION), Lines(), sleep=clock.sleep, clock=clock) == 0
    damage(state_path, "truncated")
    with pytest.raises(kitlib.KitError) as stop:
        teardown(state_path, cfg, world_aws(world))
    assert OTHER_REGION in str(stop.value) and "hint" in str(stop.value)
    code, out = verify(state_path, cfg, world_aws(world))
    assert code == 1 and result_line(out).startswith("RESULT: NOT CLEAN")
    assert OTHER_REGION in result_line(out) and there.endpoint_name in out.text
    assert "ALSO INCOMPLETE" in out.text and "by hand" in out.text


def test_r2_m4_region_and_prefix_flags_are_parsed_by_teardown_and_the_clean_check(capsys):
    for name in ("90_teardown", "99_verify_clean"):
        code = load_script(name).main(["--dry-run", "--region", "us-west-2", "--prefix", "abc"])
        output = capsys.readouterr().out
        assert code == 3
        assert "us-west-2" in output and "prefix abc" in output and "kitdemo" not in output
    with pytest.raises(kitlib.KitError, match="--region"):
        load_script("90_teardown").main(["--dry-run", "--region", "Not A Region"])
    with pytest.raises(kitlib.KitError, match="KIT_PREFIX|--prefix"):
        load_script("90_teardown").main(["--dry-run", "--prefix", "Bad_Prefix"])


def test_r2_m4_flags_do_not_get_past_a_readable_state_file_that_names_another_place_control(cfg, state_path):
    """The explicit route is for an unusable state file. A readable one still decides."""
    world = World()
    deploy_with_logs(world, cfg, state_path)
    before = state_path.read_bytes()
    elsewhere = config_for(AWS_REGION=OTHER_REGION)
    with pytest.raises(kitlib.KitError, match="Mismatch"):
        teardown(state_path, elsewhere, world_aws(world, OTHER_REGION), region=OTHER_REGION, prefix="kitdemo")
    assert state_path.read_bytes() == before and world.operations("delete_") == []


# =====================================================================================================
# Money review, MINOR 9 (sequence A24): 90_teardown.py --dry-run exited 0 with the endpoint billing.
# =====================================================================================================

def test_r2_n9_dry_run_of_teardown_exits_3_and_says_why(capsys):
    code = load_script("90_teardown").main(["--dry-run"])
    output = capsys.readouterr().out
    assert code == 3 == load_script("99_verify_clean").main(["--dry-run"])
    capsys.readouterr()
    assert "Exit code 3" in output and "never exits 0" in output and "Nothing was deleted" in output


# =====================================================================================================
# Money review, MINOR 13 (sequence A19): nothing was written before CreateModel, so a deploy that died
# right after it left a model nobody knew about, in a Region nobody had recorded.
# =====================================================================================================

class Killed(BaseException):
    """Stands in for kill -9: not an Exception, so no handler in the kit sees it."""


def aws_that_dies_after(world, operation, region=REGION):
    aws = world_aws(world, region)
    real = aws.call

    def call(service, name, **params):
        result = real(service, name, **params)
        if name == operation:
            raise Killed()
        return result

    aws.call = call
    return aws


def test_r2_n13_the_state_file_names_the_place_and_the_model_before_create_model_returns(cfg, state_path):
    world = World()
    there = config_for(AWS_REGION=OTHER_REGION)
    clock = FakeClock()
    with pytest.raises(Killed):
        load_script("10_deploy").run(ns(state_path, i_understand_this_bills=True, price_per_hour=1.0), there,
                                     aws_that_dies_after(world, "create_model", OTHER_REGION), Lines(),
                                     sleep=clock.sleep, clock=clock)
    models = list(world.place(ACCOUNT, OTHER_REGION)["models"])
    assert len(models) == 1, "AWS made the model before the process died"
    state = kitlib.load_state(state_path)
    assert state is not None, "the state file must exist before the first create call"
    assert (state["region"], state["prefix"], state["account_id"]) == (OTHER_REGION, "kitdemo", ACCOUNT)
    assert [(r["type"], r["name"]) for r in state["resources"]] == [("model", models[0])]
    # A fresh shell with the default Region: teardown stops instead of saying "nothing found" ...
    with pytest.raises(kitlib.KitError, match="Mismatch"):
        teardown(state_path, cfg, world_aws(world))
    # ... and the clean check looks where the file points.
    code, out = verify(state_path, cfg, world_aws(world))
    assert code == 1 and models[0] in out.text and OTHER_REGION in result_line(out)
    # In the right place teardown removes the model and the record.
    code, out = teardown(state_path, there, world_aws(world, OTHER_REGION))
    assert code == 0 and not world.place(ACCOUNT, OTHER_REGION)["models"]
    assert kitlib.load_state(state_path)["resources"] == []


def test_r2_n13_a_create_model_without_a_clear_answer_keeps_its_record(cfg, state_path):
    class ReadTimeoutError(Exception):
        pass

    world = World()
    aws = world_aws(world)
    real = aws.call

    def call(service, name, **params):
        result = real(service, name, **params)
        if name == "create_model":
            raise ReadTimeoutError("Read timeout on endpoint URL")
        return result

    aws.call = call
    clock = FakeClock()
    with pytest.raises(kitlib.KitError, match="MAY exist"):
        load_script("10_deploy").run(ns(state_path, i_understand_this_bills=True), cfg, aws, Lines(),
                                     sleep=clock.sleep, clock=clock)
    state = kitlib.load_state(state_path)
    assert [r["type"] for r in state["resources"]] == ["model"] and state["deploy"] is None
    assert world.operations("create_") == [f"{REGION}:create_model"], "nothing further was created"


def test_r2_n13_a_refused_create_model_leaves_no_live_record_control(cfg, state_path):
    world = World()
    aws = world_aws(world, fail={"create_model": FakeAwsError("AccessDeniedException", "not authorized", 400)})
    clock = FakeClock()
    with pytest.raises(FakeAwsError):
        load_script("10_deploy").run(ns(state_path, i_understand_this_bills=True), cfg, aws, Lines(),
                                     sleep=clock.sleep, clock=clock)
    assert not kitlib.has_live_record(kitlib.load_state(state_path)), "a refused first call must not block the next deploy"


# =====================================================================================================
# Money review, MINOR 14 and the lost-state limit (sequences A05b, A06b, A09b, tail of A07): with no
# state file the clean check cannot know where a deploy went. The RESULT line never said so.
# =====================================================================================================

def test_r2_n14_result_line_says_in_plain_words_that_no_usable_state_file_was_found(cfg, state_path):
    """Deployed elsewhere, state file lost, default shell: this is the limit. It must be impossible to miss."""
    world = World()
    there = config_for(AWS_REGION=OTHER_REGION)
    deploy_with_logs(world, there, state_path, region=OTHER_REGION)
    state_path.unlink()
    code, out = verify(state_path, cfg, world_aws(world))
    line = result_line(out)
    assert code == 0, "nothing was found where it looked; the statement, not the code, carries the limit"
    assert "NO USABLE STATE FILE WAS FOUND" in line
    assert "account ending 3333" in line and f"Region {REGION}" in line and "prefix kitdemo" in line
    assert "NOT proof for any other Region" in line
    assert not line.startswith("RESULT: CLEAN."), "it must not read like the ordinary clean line"
    assert line.startswith("RESULT: CLEAN ONLY WHERE CHECKED")


def test_r2_n14_teardown_says_the_same_in_its_last_line_when_there_is_no_state_file(cfg, state_path):
    world = World()
    there = config_for(AWS_REGION=OTHER_REGION)
    deploy_with_logs(world, there, state_path, region=OTHER_REGION)
    state_path.unlink()
    code, out = teardown(state_path, cfg, world_aws(world))
    final = last_line(out)
    assert code == 0
    assert "NO USABLE STATE FILE WAS FOUND" in final and "NOT proof for any other Region" in final
    assert f"Region {REGION}" in final and "account ending 3333" in final and "prefix kitdemo" in final


def test_r2_n14_with_a_state_file_the_clean_line_still_says_what_was_not_checked(cfg, state_path):
    """Sequences A05b and A09b: a readable state file that knows nothing of an earlier deploy. The line cannot
    say "no state file" there; it says what was checked and that this is no proof for anywhere else."""
    world = World()
    deploy_with_logs(world, cfg, state_path)
    assert teardown(state_path, cfg, world_aws(world))[0] == 0
    code, out = verify(state_path, cfg, world_aws(world))
    line = result_line(out)
    assert code == 0 and line.startswith("RESULT: CLEAN. ")
    assert "NO USABLE STATE FILE" not in line
    assert "NOT proof for any other Region" in line and "Only" in line


def test_r2_n14_not_clean_and_incomplete_lines_also_say_when_there_is_no_state_file(cfg, state_path):
    world = World()
    world.place(ACCOUNT, REGION)["models"][cfg.model_name("x")] = {}
    code, out = verify(state_path, cfg, world_aws(world))
    assert code == 1 and result_line(out).startswith("RESULT: NOT CLEAN")
    assert "NO USABLE STATE FILE WAS FOUND" in result_line(out)
    state_path.write_text("", encoding="utf-8")
    code, out = verify(state_path, cfg, world_aws(World()))
    assert code == 1 and result_line(out).startswith("RESULT: INCOMPLETE")
    assert "NO USABLE STATE FILE" in result_line(out) and "NOT proof for any other Region" in result_line(out)


def test_r2_keep_logs_is_said_in_the_last_line_of_teardown_and_in_the_result_line(cfg, state_path):
    """Sequence A23: the owner asked to keep the logs. Both scripts exit 0 with a log group left, so both
    must say that logs were kept, in the line people copy."""
    world = World()
    deploy_with_logs(world, cfg, state_path)
    code, out = teardown(state_path, cfg, world_aws(world), keep_logs=True)
    assert code == 0 and cfg.log_group_name in world.place(ACCOUNT, REGION)["logs"]
    assert "LOGS KEPT" in last_line(out) and cfg.log_group_name in last_line(out)
    code, out = verify(state_path, cfg, world_aws(world))
    assert code == 1, "without --allow-logs a kept log group is NOT CLEAN"
    code, out = verify(state_path, cfg, world_aws(world), allow_logs=True)
    line = result_line(out)
    assert code == 0 and "LOGS KEPT" in line and "1 CloudWatch log group" in line and cfg.log_group_name in line
    assert not line.startswith("RESULT: CLEAN. ")


def test_r2_allow_logs_with_no_log_group_left_is_the_ordinary_clean_line_control(cfg, state_path):
    world = World()
    deploy_with_logs(world, cfg, state_path)
    assert teardown(state_path, cfg, world_aws(world))[0] == 0
    code, out = verify(state_path, cfg, world_aws(world), allow_logs=True)
    assert code == 0 and "LOGS KEPT" not in result_line(out)


# =====================================================================================================
# Numbers review, M3: teardown printed the sum of every finished run in .state.json as "the hours".
# =====================================================================================================

def old_upper_bound_run(cfg):
    return {"create_called_utc": "2026-09-30T10:00:00Z", "deleted_confirmed_utc": "2026-09-30T19:00:00Z",
            "hours": 9.0, "estimated_usd": 10.998, "hours_is_upper_bound": True, "usd_per_hour": 1.222,
            "region": REGION, "prefix": cfg.prefix, "account_id": ACCOUNT}


def test_r2_m3_teardown_prints_this_run_on_its_own_line_then_the_total_with_count_and_dates(cfg, state_path):
    """The reviewer's input: a 9 h run that ended "already absent" a week ago, plus 2 h today. Reviewed code
    printed "AT MOST 11.00 h ... at most $13.44" and nothing else."""
    world = World()
    state = deploy_with_logs(world, cfg, state_path)
    state["history"].append(old_upper_bound_run(cfg))
    state["deploy"]["create_called_utc"] = kitlib.iso(kitlib.utc_now() - dt.timedelta(hours=2))
    kitlib.save_state(state, state_path)
    code, out = teardown(state_path, cfg, world_aws(world))
    assert code == 0
    this_run = [line for line in out if line.startswith("This run:")]
    assert len(this_run) == 1, out.text
    assert "2.00 h" in this_run[0] and "$2.44" in this_run[0]
    assert "AT MOST" not in this_run[0], "today's run has a known end; it must not inherit AT MOST from an old run"
    assert re.search(STAMP, this_run[0]), "the run's own start and end times are printed"
    total = [line for line in out if line.startswith("All 2 finished runs")]
    assert len(total) == 1, out.text
    assert "AT MOST 11.00 h" in total[0] and "$13.44" in total[0]
    assert "2026-09-30T10:00:00Z" in total[0], "the total says which dates it covers"
    assert "1 of the 2" in total[0], "and how many of its runs have an unknown end"


def test_r2_m3_a_single_run_is_not_presented_as_a_total(cfg, state_path):
    world = World()
    deploy_with_logs(world, cfg, state_path)
    code, out = teardown(state_path, cfg, world_aws(world))
    assert code == 0
    assert len([line for line in out if line.startswith("This run:")]) == 1 and "1.00 h" in out.text
    assert "only finished run" in out.text and "All " not in out.text


def test_r2_m3_run_report_lines_unit(cfg):
    state = kitlib.empty_state(cfg, ACCOUNT)
    assert kitlib.run_report_lines(state, ".state.json", closed_now=False) == []
    state["history"] = [old_upper_bound_run(cfg),
                        {"create_called_utc": "2026-10-07T10:00:00Z", "deleted_confirmed_utc": "2026-10-07T12:00:00Z",
                         "hours": 2.0, "estimated_usd": 2.444, "hours_is_upper_bound": False, "usd_per_hour": 1.222}]
    lines = kitlib.run_report_lines(state, ".state.json", closed_now=True)
    assert lines[0].startswith("This run:") and "2.00 h" in lines[0] and "2026-10-07T12:00:00Z" in lines[0]
    assert any(line.startswith("All 2 finished runs") for line in lines)
    per_run = [line for line in lines if line.lstrip().startswith("run ")]
    assert len(per_run) == 2 and "AT MOST 9.00 h" in per_run[0] and "AT MOST" not in per_run[1]
    earlier = kitlib.run_report_lines(state, ".state.json", closed_now=False)
    assert not any(line.startswith("This run:") for line in earlier), "nothing was closed, so there is no 'this run'"
    assert kitlib.run_totals(state) == (11.0, 13.442)


# =====================================================================================================
# Numbers review, M4: rows of RESULTS_TEMPLATE.md that no script printed (hand-timed).
# =====================================================================================================

def test_r2_m4n_teardown_prints_when_the_endpoint_was_gone_and_when_it_finished(cfg, state_path):
    world = World()
    deploy_with_logs(world, cfg, state_path)
    code, out = teardown(state_path, cfg, world_aws(world))
    recorded = kitlib.load_state(state_path)["history"][0]["deleted_confirmed_utc"]
    assert code == 0
    assert f"Endpoint(s) confirmed gone at {recorded} (UTC" in out.text, "the stored end time is printed on its own line"
    assert re.match(rf"Teardown done at {STAMP} \(UTC\)", last_line(out)), last_line(out)


def ticking_utc(monkeypatch, start, step_seconds):
    moment = [start]

    def now():
        moment[0] = moment[0] + dt.timedelta(seconds=step_seconds)
        return moment[0]

    monkeypatch.setattr(kitlib, "utc_now", now)


def test_r2_m4n_change_one_setting_prints_the_minutes_of_downtime_with_utc_stamps(cfg, state_path, monkeypatch):
    world = World()
    deploy_with_logs(world, cfg, state_path)
    ticking_utc(monkeypatch, kitlib.utc_now(), 20)
    out, clock = Lines(), FakeClock()
    code = load_script("70_change_one_setting").run(ns(state_path, i_understand_this_bills=True), cfg,
                                                    world_aws(world), out, sleep=clock.sleep, clock=clock)
    assert code == 0
    downtime = [line for line in out if line.startswith("Downtime:")]
    assert len(downtime) == 1, out.text
    match = re.match(rf"Downtime: (\d+\.\d) minutes, from the DeleteEndpoint call at ({STAMP}) to InService seen at ({STAMP}) \(UTC",
                     downtime[0])
    assert match, downtime[0]
    span = (kitlib.parse_iso(match.group(3)) - kitlib.parse_iso(match.group(2))).total_seconds() / 60.0
    assert float(match.group(1)) == pytest.approx(span, abs=0.06) and span > 0
    assert any(line.startswith("The endpoint it replaced:") and " h" in line for line in out), \
        "the run that step 70 closes gets its own line too"


def test_r2_m4n_deploy_prints_utc_stamps_for_the_create_call_and_for_in_service(cfg, state_path, monkeypatch):
    world = World()
    out, clock = Lines(), FakeClock()
    ticking_utc(monkeypatch, kitlib.utc_now(), 20)
    assert load_script("10_deploy").run(ns(state_path, i_understand_this_bills=True), cfg, world_aws(world), out,
                                        sleep=clock.sleep, clock=clock) == 0
    state = kitlib.load_state(state_path)
    line = next(line for line in out if line.startswith("InService after"))
    match = re.match(rf"InService after (\d+\.\d) minutes \(CreateEndpoint call at ({STAMP}), InService seen at ({STAMP}), UTC", line)
    assert match, line
    assert (match.group(2), match.group(3)) == (state["deploy"]["create_called_utc"], state["deploy"]["in_service_utc"])
    assert match.group(2) != match.group(3)
    span = (kitlib.parse_iso(match.group(3)) - kitlib.parse_iso(match.group(2))).total_seconds() / 60.0
    assert float(match.group(1)) == pytest.approx(span, abs=0.06)
    assert f"CreateEndpoint was called at {match.group(2)} (UTC)" in out.text


# =====================================================================================================
# Numbers review, M5: "over ___ requests of ___ output tokens" could only be filled with max_tokens.
# =====================================================================================================

def result(tokens, ttft=0.2, chunks=None):
    return streamstats.RequestResult(ok=True, error="", ttft_s=ttft, total_s=2.0, output_tokens=tokens,
                                     tokens_source="usage", prompt_tokens=5, request_tokens_per_s=tokens / 2.0,
                                     decode_tokens_per_s=50.0, text_chunks=tokens if chunks is None else chunks,
                                     finish_reason="stop", saw_done=True)


def test_r2_m5_summary_has_output_tokens_per_request_for_each_level():
    failed = streamstats.RequestResult(ok=False, error="x", ttft_s=None, total_s=1.0, output_tokens=0,
                                       tokens_source="none", prompt_tokens=None, request_tokens_per_s=None,
                                       decode_tokens_per_s=None, text_chunks=0, finish_reason="", saw_done=False)
    summary = streamstats.summarise_level("x", 4, [result(100), result(150), result(200), failed], wall_s=4.0)
    assert summary.output_tokens_total == 450 and summary.ok == 3
    assert summary.output_tokens_per_request_mean == pytest.approx(150.0)
    assert (summary.output_tokens_min, summary.output_tokens_max) == (100, 200)
    row = streamstats.summary_row(summary)
    assert row["output_tokens_per_request_mean"] == "150.0000" and row["output_tokens_max"] == 200
    table = streamstats.format_summary_table([summary])
    assert "out tok/req" in table and "150.0" in table


def test_r2_m5_loadtest_prints_tokens_per_request_for_each_level(cfg, state_path, tmp_path):
    from test_review_r1 import IdentityOnlyAws
    module = load_script("60_loadtest")
    sizes = iter([200] * 2 + [120, 200, 160] * 40)
    args = argparse.Namespace(state_path=state_path, results_dir=tmp_path / "results", concurrency="1,2",
                              requests_per_level=3, max_tokens=200, prompt="p", label="baseline", ignore_eos=False,
                              endpoint_name=None, ignore_deadline=False)
    out = Lines()
    assert module.run(args, cfg, IdentityOnlyAws(), out, sender_factory=lambda *a, **k: lambda index: result(next(sizes))) == 0
    per_level = [line for line in out if "output tokens per request" in line]
    assert len(per_level) == 2, out.text
    assert all("up to 200" in line and "mean" in line and "min" in line and "max" in line for line in per_level)
    summary_file = next(p for p in (tmp_path / "results").iterdir() if p.name.endswith("_summary.csv"))
    with summary_file.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert all(float(row["output_tokens_per_request_mean"]) > 0 for row in rows)


# =====================================================================================================
# Numbers review, MINOR: decode tokens per second divided a usage token count by chunk timing.
# =====================================================================================================

def sse(payload) -> bytes:
    return ("data: " + (payload if isinstance(payload, str) else json.dumps(payload)) + "\n\n").encode()


def text_chunk(text):
    return sse({"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}]})


def closing(usage_tokens):
    return (sse({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
            + sse({"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": usage_tokens}}) + sse("[DONE]"))


def play(parts, end):
    recorder = streamstats.StreamRecorder(0.0)
    for moment, data in parts:
        recorder.on_bytes(data, moment)
    return recorder.result(end)


def test_r2_decode_rate_counts_chunks_so_a_higher_usage_count_cannot_inflate_it():
    """The reviewer's two inputs. Reviewed code: 12.22 for a true 10.0, and 22.5 for a true 20.0."""
    ten_chunks = [(1.0 + 0.1 * i, text_chunk("a")) for i in range(10)]
    measured = play(ten_chunks + [(1.95, closing(12))], 2.0)
    assert measured.ok and measured.output_tokens == 12 and measured.text_chunks == 10
    assert measured.decode_tokens_per_s == pytest.approx(10.0), "9 chunks in 0.9 s after the first"
    two_per_chunk = [(1.0 + 0.1 * i, text_chunk("ab")) for i in range(5)]
    batched = play(two_per_chunk + [(1.45, closing(10))], 1.5)
    assert batched.decode_tokens_per_s == pytest.approx(10.0), "a chunk rate: never above the true token rate of 20"
    assert batched.decode_tokens_per_s <= 20.0
    agreeing = play(ten_chunks + [(1.95, closing(10))], 2.0)
    assert agreeing.decode_tokens_per_s == pytest.approx(10.0), "unchanged when usage and chunks agree"


def test_r2_decode_rate_mismatch_is_counted_and_announced(cfg, state_path, tmp_path):
    summary = streamstats.summarise_level("x", 1, [result(10), result(12, chunks=10), result(10, chunks=5)], wall_s=3.0)
    assert summary.token_chunk_mismatch_requests == 2
    assert streamstats.summary_row(summary)["token_chunk_mismatch_requests"] == 2
    from test_review_r1 import IdentityOnlyAws
    module = load_script("60_loadtest")
    args = argparse.Namespace(state_path=state_path, results_dir=tmp_path / "results", concurrency="1",
                              requests_per_level=2, max_tokens=50, prompt="p", label="baseline", ignore_eos=False,
                              endpoint_name=None, ignore_deadline=False)
    out = Lines()
    assert module.run(args, cfg, IdentityOnlyAws(), out, sender_factory=lambda *a, **k: lambda index: result(12, chunks=10)) == 0
    note = [line for line in out if line.startswith("NOTE: decode")]
    assert len(note) == 1 and "chunks" in note[0] and "2 of 2" in note[0]


# =====================================================================================================
# Numbers review, MINOR: "TTFT p95" was printed for any n; at n = 4 it is 3.85 of a maximum of 4.
# =====================================================================================================

def test_r2_p95_is_not_given_for_fewer_than_twenty_requests():
    few = streamstats.summarise_level("x", 1, [result(10, ttft=float(i)) for i in range(1, 5)], wall_s=4.0)
    assert few.ttft_p95_s is None and few.ttft_p50_s == pytest.approx(2.5) and few.ttft_max_s == 4.0
    assert streamstats.summary_row(few)["ttft_p95_s"] == ""
    row = streamstats.format_summary_table([few]).splitlines()[2].split()
    assert row[3] == "-", f"the p95 column must show '-' for 4 requests: {row}"
    nineteen = streamstats.summarise_level("x", 1, [result(10, ttft=float(i)) for i in range(1, 20)], wall_s=4.0)
    twenty = streamstats.summarise_level("x", 1, [result(10, ttft=float(i)) for i in range(1, 21)], wall_s=4.0)
    assert nineteen.ttft_p95_s is None
    assert twenty.ttft_p95_s == pytest.approx(19.05)
    assert streamstats.MIN_REQUESTS_FOR_P95 == 20


def test_r2_p95_note_is_printed_by_the_load_test_when_a_level_is_too_small(cfg, state_path, tmp_path):
    from test_review_r1 import IdentityOnlyAws
    module = load_script("60_loadtest")
    args = argparse.Namespace(state_path=state_path, results_dir=tmp_path / "results", concurrency="1",
                              requests_per_level=4, max_tokens=50, prompt="p", label="baseline", ignore_eos=False,
                              endpoint_name=None, ignore_deadline=False)
    out = Lines()
    assert module.run(args, cfg, IdentityOnlyAws(), out, sender_factory=lambda *a, **k: lambda index: result(10)) == 0
    assert any("p95" in line and "fewer than 20" in line for line in out), out.text


# =====================================================================================================
# The written record: README sections 5 to 8 and RESULTS_TEMPLATE.md say what the code now does.
# =====================================================================================================

README = (KIT_DIR / "README.md").read_text(encoding="utf-8")
TEMPLATE = (KIT_DIR / "RESULTS_TEMPLATE.md").read_text(encoding="utf-8")


def section(number: int) -> str:
    headings = ["", "1. What this is", "2. Problems first", "3. Before you start", "4. Run it",
                "5. Tear it down and prove it", "6. What to record",
                "7. What you can truthfully say afterwards, and what you cannot", "8. What was and was not tested",
                "9. Sources"]
    return README.split(f"## {headings[number]}")[1].split(f"## {headings[number + 1]}")[0]


def test_r2_docs_section_5_says_how_to_recover_from_a_lost_or_damaged_state_file():
    text = section(5)
    assert "If the state file is lost or damaged" in text
    assert "python 90_teardown.py --region <the Region you deployed in> --prefix <your KIT_PREFIX>" in text
    assert "NO USABLE STATE FILE WAS FOUND" in text and "NOT proof for any other Region" in text
    assert "by hand" in text and "INCOMPLETE" in text
    assert "whats_running.py" in text
    assert "| 3 |" in text and "90_teardown.py --dry-run" in text, "the exit-code table covers the teardown dry run"
    assert "LOGS KEPT" in text
    assert "so it works even if the state file is lost" not in text, "that sentence promised more than the kit can do"


def test_r2_docs_sections_6_and_7_and_the_template_match_what_the_scripts_print():
    assert "up to ___ output tokens" in section(7) and "requests of ___ output tokens" not in section(7)
    assert "This run:" in section(6) and "output tokens per request" in section(6)
    assert "Downtime:" in section(6)
    for needle in ("This run:", "All N finished runs", "Downtime:", "Teardown done at", "Output tokens per request",
                   "NO USABLE STATE FILE", "LOGS KEPT", "fewer than 20"):
        assert needle in TEMPLATE, f"RESULTS_TEMPLATE.md does not mention {needle!r}"


def test_r2_docs_section_8_carries_the_round_2_line_and_its_table():
    text = section(8)
    match = re.search(r"Reviewed independently a second time on 2026-10-07 \(round 2\): (\d+) findings for this kit, "
                      r"(\d+) fixed, (\d+) left open \(listed below\)", text)
    assert match, "the dated round 2 line is missing or reworded"
    found, fixed, left_open = (int(group) for group in match.groups())
    assert found == 11 and fixed + left_open == found
    assert re.search(r"Reviewed independently on 2026-10-07 \(round 1\): 18 findings, 18 fixed, 0 left open", text)
    for label in ("BLOCKER 2", "BLOCKER 3", "MAJOR 4", "MINOR 9", "MINOR 13", "MINOR 14", "M3", "M4", "M5"):
        assert label in text, f"round 2 finding {label} is not in the section 8 table"
    assert "tests/test_review_r2.py" in text
