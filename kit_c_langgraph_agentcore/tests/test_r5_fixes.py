"""Review round 5, 2026-10-08: the findings of the independent reader of the round 4 code (F1 to
F18). Each test failed on the code as it was read (the frozen round 4 tree) and states what is
correct. REVIEW_NOTES_r5.md has the findings one by one, with the reader's case before and after.

F1   teardown and the clean check said clean while a recorded runtime still existed, when
     GetAgentRuntime was refused and the listing did not show it (the listing decided);
F2   a docket id built from parts the run returned ("FAA-2026-0491" for FAA-2025-0491) passed;
F3   60_read_usage.py said to wait for RESULT: CROSS-CHECKED when it could never come;
F4   a search total restated as a count of documents passed after a sentence called it matches;
F5   a quotation spliced with "..." from two documents passed;
F6   "were matched by" (the passive) and "among" anywhere in the sentence excused a count;
F7   a curly apostrophe, a zero-width space or a no-break space hid a line shaped like the kit's;
F8   an argument name the model made up could write lines into the code-built block;
F9   terminal control characters in the model's text reached the screen;
F10  a runtime in DELETE_FAILED was "could not be asked for by id" instead of NOT CLEAN;
F11  the mixed-layouts reason said "running totals" when none were seen;
F12  the LOWER BOUND caveat on tokens was printed only when a price was known;
F13  only 90 and 99 masked account ids; 60 --show-logs printed one in full;
F14 to F18  sentences of README.md and START_HERE.md that the code did not bear out.

Offline: scripted models, canned Federal Register answers, the fake account of test_r2_money.
"""
from __future__ import annotations

import datetime as dt
import json
import re

import pytest
from conftest import ACCOUNT, ROOT, RUNTIME_ARN, RUNTIME_ID, FakeClientError, load_script, make_fake_aws
from langchain_core.messages import AIMessage

from agent import graph as g
from test_r2_money import EAST, World, result_of, teardown, verify, write_state
from test_r2_usage import S1, S2, inc, metrics, run as usage_run
from test_r4_answer_check import (AIRBUS, BOEING, HEAD, LOOKED, URL, S, after_lookup, after_search, api_doc,
                                  ask, found)
from test_r4_money import IDENTITY, SessionWorld, _with_session

README = (ROOT / "README.md").read_text(encoding="utf-8")
START = (ROOT / "START_HERE.md").read_text(encoding="utf-8")
FLAT_README = " ".join(README.split())
FLAT_START = " ".join(START.split())


# ====================================================================== F1 and F10
class HiddenRuntimeWorld(World):
    """The recorded runtime exists, but the listing by name does not show it. deny_get makes
    GetAgentRuntime answer AccessDenied; status, when given, is what it answers instead."""

    def __init__(self, kit, deny_get=False, status=None):
        super().__init__(kit)
        self.deny_get = deny_get
        self.status = status

    def _handlers(self, region):
        handlers = super()._handlers(region)
        world = self

        def get_agent_runtime(**p):
            if world.deny_get:
                return FakeClientError("AccessDeniedException")
            if world.status:
                return {"status": world.status, "failureReason": "delete failed"}
            item = world.runtimes.get(region, {}).get(p["agentRuntimeId"])
            return {"status": item["status"]} if item else FakeClientError("ResourceNotFoundException")
        handlers["list_agent_runtimes"] = lambda **p: {"agentRuntimes": []}
        handlers["get_agent_runtime"] = get_agent_runtime
        return handlers


def _hidden(kit, world):
    """A deploy of which only the runtime is left, and the listing does not show it."""
    record = world.deploy(EAST)
    for store in (world.buckets, world.roles, world.tags):
        store.clear()
    world.log_groups.clear()
    world.identities.clear()
    write_state(kit, record)
    return record


def test_F1_teardown_keeps_the_record_of_a_runtime_the_get_call_is_refused_for(kit):
    world = HiddenRuntimeWorld(kit, deny_get=True)
    record = _hidden(kit, world)
    rc, lines = teardown(kit, world, EAST)
    assert rc == 1, "\n".join(lines)
    assert world.runtimes[EAST]                                   # it still exists, and the exit code says so
    assert json.loads(kit.STATE_PATH.read_text())["runtime_id"] == record["runtime_id"]
    assert not any("so it does not exist" in line or "confirmed absent" in line for line in lines)
    assert any(f"could not check runtime {record['runtime_id']}: AccessDeniedException" in line
               and "not proof that it is gone" in line for line in lines)
    assert lines[-2].startswith("Teardown finished WITH ERRORS")
    # and the clean check after it does not say CLEAN either
    rc, lines = verify(kit, world, EAST)
    assert rc == 1 and result_of(lines).startswith("RESULT: NOT VERIFIED"), "\n".join(lines)
    assert "could not be asked for by id (AccessDeniedException)" in result_of(lines)


def test_F1_the_clean_check_is_not_verified_when_the_get_call_is_refused(kit):
    world = HiddenRuntimeWorld(kit, deny_get=True)
    _hidden(kit, world)
    rc, lines = verify(kit, world, EAST)
    assert rc == 1 and result_of(lines).startswith("RESULT: NOT VERIFIED"), "\n".join(lines)


def test_F1_unchanged_a_runtime_that_answers_not_found_is_confirmed_absent(kit):
    world = HiddenRuntimeWorld(kit)
    record = _hidden(kit, world)
    del world.runtimes[EAST][record["runtime_id"]]
    rc, lines = teardown(kit, world, EAST)
    assert rc == 0 and any("confirmed absent" in line for line in lines), "\n".join(lines)
    rc, lines = verify(kit, world, EAST)
    assert rc == 0 and result_of(lines).startswith("RESULT: CLEAN")


def test_F10_a_runtime_in_delete_failed_is_not_clean_and_is_not_called_unaskable(kit):
    world = HiddenRuntimeWorld(kit, status="DELETE_FAILED")
    record = _hidden(kit, world)
    rc, lines = verify(kit, world, EAST)
    line = result_of(lines)
    assert rc == 1 and line.startswith("RESULT: NOT CLEAN: 1 item(s) left"), "\n".join(lines)
    assert "could not be asked for by id" not in "\n".join(lines)
    assert any(record["runtime_id"] in line and "still exists (DELETE_FAILED" in line for line in lines)
    # the teardown says the same, not "could not check"
    rc, lines = teardown(kit, world, EAST)
    assert rc == 1 and any("is recorded in .state.json and still exists: runtime delete failed" in line
                           for line in lines), "\n".join(lines)


# ====================================================================== F2
def test_F2_a_docket_id_with_its_year_swapped_is_warned():
    out = after_lookup(f"{LOOKED} The docket is FAA-2026-0491.", docket_ids=["Docket No. FAA-2025-0491"])
    assert "2026-0491" in out["unverified_numbers"], out["warnings"]
    assert out["warnings"]
    out = after_lookup(f"{LOOKED} The docket is FAA-2026-2730.", docket_ids=["Docket No. FAA-2025-2730"])
    assert "2026-2730" in out["unverified_numbers"], out["warnings"]


def test_F2_unchanged_without_the_agency_letters_a_swapped_docket_number_is_still_warned():
    """Written without "FAA-", 2026-0491 has the form of a document number, and the document
    number rule warns it as before."""
    out = after_lookup(f"{LOOKED} Its docket number is 2026-0491.", docket_ids=["Docket No. FAA-2025-0491"])
    assert "unverified_references" in out["grounding_reasons"] and "2026-0491" in out["warnings"][0], out["warnings"]


def test_F2_unchanged_the_returned_docket_id_ranges_and_model_numbers_pass():
    assert after_lookup(f"{LOOKED} The docket is FAA-2025-0491.",
                        docket_ids=["Docket No. FAA-2025-0491"])["warnings"] == []
    # a model number after letters does not start with a year: still compared part by part
    doc = dict(api_doc(BOEING), abstract="The FAA is adopting a new AD for certain De Havilland Model "
                                         "DHC-8-102, -103, and -106 airplanes.")
    out = ask([S(), AIMessage(content=f"{HEAD} It covers Model DHC-8-103 airplanes.")],
              [(200, {"count": 2, "results": [doc, api_doc(AIRBUS)]})])
    assert out["warnings"] == [], out["warnings"]


# ====================================================================== F4
def test_F4_a_total_restated_as_a_count_of_documents_is_warned_after_a_sentence_of_matches():
    out = after_search("31 documents matched the search for airworthiness directives. 31 final rules on "
                       f"airworthiness directives were published by the FAA this year. {HEAD}", total=31)
    assert out["warnings"] and any("31 final rules" in w for w in out["warnings"]), out["warnings"]


def test_F4_unchanged_a_sentence_that_refers_back_to_the_total_passes():
    for back in ("all 31", "the 31", "those 31"):
        out = after_search("31 documents matched the search for airworthiness directives among FAA final rules. "
                           f"I did not see {back} final rules, only the 2 newest. One of them is {BOEING}: "
                           f"{URL[BOEING]}", total=31)
        assert out["warnings"] == [], (back, out["warnings"])


# ====================================================================== F5
def test_F5_a_quotation_spliced_from_two_documents_is_warned():
    out = after_search(f'{HEAD}. The FAA notice says it "is superseding ... The Boeing Company airplanes".', total=2)
    assert out["unverified_quotes"] == ["is superseding ... The Boeing Company airplanes"], out["warnings"]


def test_F5_the_pieces_of_a_quotation_must_stand_in_order():
    out = after_search(f'{HEAD}. The AD "aft pressure bulkhead ... provides draft recommendations".', total=2)
    assert out["unverified_quotes"] == ["aft pressure bulkhead ... provides draft recommendations"], out["warnings"]


def test_F5_unchanged_pieces_in_order_from_one_abstract_pass():
    out = after_search(f'{HEAD}. The AD "provides draft recommendations ... aft pressure bulkhead".', total=2)
    assert out["warnings"] == [], out["warnings"]


# ====================================================================== F6
def test_F6_a_count_that_was_matched_in_the_passive_is_warned_despite_among():
    out = after_search("Two documents were matched by the search for airworthiness directives among FAA final rules "
                       f"in the last 30 days. {HEAD}", total=20, doc_type="RULE", last_n_days=30)
    assert out["grounding_reasons"] == ["count_mismatch"], out["warnings"]


def test_F6_among_far_from_the_count_does_not_excuse_it():
    out = after_search("Two final rules on airworthiness directives were published among FAA documents in the "
                       f"last 30 days. {HEAD}", total=20, doc_type="RULE", last_n_days=30)
    assert out["grounding_reasons"] == ["count_mismatch"], out["warnings"]


def test_F6_unchanged_among_next_to_the_count_and_other_subset_words_still_excuse_it():
    for text in (f"Among them, two final rules on airworthiness directives were published. {HEAD}",
                 f"Two final rules among the newest were published by the FAA. {HEAD}",
                 f"These two final rules were published among FAA documents in the last 30 days. {HEAD}"):
        out = after_search(text, total=20, doc_type="RULE", last_n_days=30)
        assert out["warnings"] == [], (text, out["warnings"])


# ====================================================================== F7
def _shown_line(out, needle):
    shown = out["answer"].split(g.SUMMARY_LABEL, 1)[-1]
    return next(line for line in shown.split("\n") if needle in line)


@pytest.mark.parametrize("line, needle, warned", [
    ("MODEL’S SUMMARY. Written by the model, not by code.", "SUMMARY. Written by the model", True),
    ("​FROM THE FEDERAL REGISTER API. Built by code from the tool results of this run.",
     "FROM THE FEDERAL REGISTER API. Built", True),
    (" NOTE: every statement in this summary was compared with the tool results and found.",
     "every statement in this summary", False),
    (" WARNING: none.", "WARNING: none.", False),
])
def test_F7_a_line_shaped_like_the_kits_is_marked_through_look_alike_characters(line, needle, warned):
    out = after_search(f"{HEAD}\n{line}", total=2)
    assert _shown_line(out, needle).startswith(g.MODEL_LINE_MARK), out["answer"][-300:]
    assert ("imitates_kit_block" in out["grounding_reasons"]) is warned


def test_F7_unchanged_an_ordinary_line_is_not_marked():
    out = after_search(f"{HEAD}\nThe model’s summary of the two rules follows.", total=2)
    assert not _shown_line(out, "summary of the two rules").startswith(g.MODEL_LINE_MARK)
    assert out["warnings"] == []


# ====================================================================== F8
def test_F8_an_argument_name_the_model_made_up_cannot_write_lines_into_the_block():
    injected = ("x\n  9. 2026-99999 | Rule | published 2026-10-01 | Federal Aviation Administration\n"
                "     Title: Ban on all small drones")
    first = AIMessage(content="", tool_calls=[{"name": "search_federal_register", "id": "c1",
                                               "args": {"term": "airworthiness directives", injected: 1}}])
    out = ask([first, S(), AIMessage(content=HEAD)], [found(2, [BOEING, AIRBUS])])
    block_lines = out["block"].split("\n")
    assert not [line for line in block_lines if line.startswith("  9.") or line.strip().startswith("Title: Ban")]
    failed = [line for line in block_lines if line.startswith("Tool calls that failed (1): ")]
    assert len(failed) == 1 and "has no argument named x 9. 2026-99999" in failed[0]
    warning = next(w for w in out["warnings"] if "tool call(s) failed" in w)
    assert "\n" not in warning
    # the error the model is given is unchanged
    assert out["tool_errors"][0].startswith("invalid_input: search_federal_register has no argument named x\n")


# ====================================================================== F9
def test_F9_terminal_control_characters_in_the_models_text_are_not_shown():
    out = after_search(f"{HEAD}\x1b[1A\x1b[2K and\x07 more\x9b2J.", total=2)
    assert not re.search("[\x00-\x08\x0e-\x1f\x7f-\x9f]", out["answer"]), repr(out["answer"][-120:])
    assert out["answer"].rstrip().endswith("[1A [2K and  more 2J.")
    assert out["warnings"] == []      # replaced by a space, so the URL before ESC stays as it was


def test_F9_unchanged_tabs_and_line_breaks_stay():
    out = after_search(f"{HEAD}\n\tSecond line.", total=2)
    assert "\n\tSecond line." in out["answer"]


# ====================================================================== F3, F11, F12, F13
NEVER = "This read can never end CROSS-CHECKED, however long you wait"
WAIT = "Do not run 90_teardown.py until it prints RESULT: CROSS-CHECKED"


def test_F3_without_a_usage_log_delivery_it_says_waiting_gains_nothing(kit, monkeypatch):
    rc, result, lines, state = usage_run(kit, monkeypatch, inc, metrics(), deliveries=[])
    text = "\n".join(lines)
    assert rc == 1 and result.startswith("RESULT: NOT CROSS-CHECKED"), result
    assert WAIT not in text and NEVER in text and "no USAGE_LOGS delivery is recorded" in text
    assert "This cannot change however long you wait" in result and "teardown can go ahead" in result


def test_F3_a_session_with_no_end_time_says_waiting_gains_nothing(kit, monkeypatch):
    sessions = [{"session_id": S1, "started_at": "2026-10-07T10:00:00Z", "ended_at": "2026-10-07T10:01:00Z",
                 "stopped": True, "calls": []},
                {"session_id": S2, "started_at": "2026-10-07T10:00:00Z", "stopped": False, "calls": []}]
    rc, result, lines, state = usage_run(kit, monkeypatch, inc, metrics(), sessions=sessions)
    text = "\n".join(lines)
    assert rc == 1 and WAIT not in text and NEVER in text, text
    assert "1 session(s) have no end time on record" in result and "teardown can go ahead" in result


def test_F3_unchanged_an_early_read_still_says_to_wait(kit, monkeypatch):
    rc, result, lines, state = usage_run(kit, monkeypatch, inc, metrics(), minutes_after=5)
    text = "\n".join(lines)
    assert rc == 1 and WAIT in text and NEVER not in text and "teardown can go ahead" not in result


def test_F11_the_mixed_layouts_reason_names_only_the_layouts_seen(kit, monkeypatch):
    events = {S1: inc(S1, 60, elapsed=lambda i: None), S2: inc(S2)}
    rc, result, lines, state = usage_run(kit, monkeypatch, lambda s: events[s], metrics())
    assert rc == 1 and "running totals" not in result, result
    assert "do not all have one layout" in result and "look like increments" in result
    assert "do not say how much time they cover" in result


def test_F12_the_lower_bound_is_said_when_no_price_is_known(kit, monkeypatch):
    sessions = [{"session_id": S1, "started_at": "2026-10-07T10:00:00Z", "ended_at": "2026-10-07T10:01:00Z",
                 "stopped": True, "calls": [{"input_tokens": 3000, "output_tokens": 500},
                                            {"input_tokens": None, "output_tokens": None, "error": "x"}]},
                {"session_id": S2, "started_at": "2026-10-07T10:00:00Z", "ended_at": "2026-10-07T10:01:00Z",
                 "stopped": True, "calls": [{"input_tokens": 3000, "output_tokens": 500}]}]
    rc, result, lines, state = usage_run(kit, monkeypatch, inc, metrics(),
                                         model_id="anthropic.claude-sonnet-4-5-20250929-v1:0", sessions=sessions)
    line = next(line for line in lines if line.startswith("Token cost:"))
    assert "not computed" in line and "LOWER BOUND: 1 of 3 call(s) reported no token count" in line, line
    rc, result, lines, state = usage_run(kit, monkeypatch, inc, metrics(), sessions=sessions,
                                         argv=["--input-usd-per-1m", "1"])
    line = next(line for line in lines if line.startswith("Token cost:"))
    assert "Give both" in line and "LOWER BOUND" in line, line


def test_F13_60_show_logs_masks_an_account_id_in_the_runtime_log(kit, monkeypatch):
    script = load_script("60_read_usage.py")
    monkeypatch.setattr(kit, "utc_now", lambda: dt.datetime(2026, 10, 7, 11, 31, tzinfo=dt.timezone.utc))

    def filter_log_events(**p):
        if p["logGroupName"].startswith("/aws/bedrock-agentcore/runtimes/"):
            return {"events": [{"timestamp": 1, "message": "assumed arn:aws:sts::111122223333:assumed-role/x/y"}]}
        return {"events": inc(p["filterPattern"].strip('"'))}
    lines: list[str] = []
    aws = make_fake_aws(kit, {"get_caller_identity": IDENTITY, "filter_log_events": filter_log_events,
                              "get_metric_statistics": {"Datapoints": []}}, lines)
    state = kit.State(kit.STATE_PATH)
    state.set(region="us-east-1", prefix="kitdemo", account_id=ACCOUNT, runtime_id=RUNTIME_ID, runtime_arn=RUNTIME_ARN,
              deliveries=[{"kind": "usage", "log_type": "USAGE_LOGS"}],
              sessions=[{"session_id": S1, "started_at": "2026-10-07T10:00:00Z", "ended_at": "2026-10-07T10:01:00Z",
                         "calls": []}])
    script.main(["--show-logs"], aws=aws, out=lines.append, state=state)
    text = "\n".join(lines)
    assert "111122223333" not in text and "arn:aws:sts::********3333:assumed-role/x/y" in text


class _Stop(Exception):
    pass


@pytest.mark.parametrize("name, argv", [("30_deploy.py", []), ("40_enable_observability.py", []),
                                        ("50_invoke_hosted.py", []), ("60_read_usage.py", [])])
def test_F13_scripts_30_to_60_hand_a_masking_print_to_everything_they_run(kit, monkeypatch, name, argv):
    """The print function main() passes on (to Aws, to State, and uses itself) masks a 12-digit
    account id, as in 90 and 99."""
    script = load_script(name)
    given = {}

    def capture(region, dry_run=False, out=None, **kwargs):
        given["out"] = out
        raise _Stop()
    monkeypatch.setattr(kit, "Aws", capture)
    lines: list[str] = []
    with pytest.raises(_Stop):
        script.main(argv, out=lines.append)
    given["out"]("caller arn:aws:iam::111122223333:role/x")
    assert lines == ["caller arn:aws:iam::********3333:role/x"]


# ====================================================================== F14 to F18: what the documents say
def _exit_zero_endings() -> list[str]:
    section5 = README[README.index("## 5. Tear it down and prove it"):README.index("## 6. What to record")]
    rows = [line for line in section5.splitlines() if re.match(r"^\| .* \| 0 \| ", line)]
    endings = []
    for row in rows:
        first = row.split(" | ")[0].lstrip("| ")
        if "Teardown" in first:
            endings += re.findall(r'"([^"]+)"', first)
    return endings


def _verdict(lines):
    index = next(i for i, line in enumerate(lines) if line.startswith("Now prove it"))
    return lines[index - 1]


def test_F14_every_exit_0_ending_of_teardown_is_in_the_readme_table_and_start_here(kit):
    world = SessionWorld(kit, stop_fails=1)
    _with_session(kit, world)
    rc, lines = teardown(kit, world, EAST)
    verdict = _verdict(lines)
    assert rc == 0 and verdict.startswith("Teardown finished.") and "The first call to stop" in verdict
    endings = _exit_zero_endings()
    assert "Teardown finished without errors" in endings and "Teardown finished." in endings, endings
    assert "The first call to stop" in endings
    assert "or `Teardown finished.` when a first call to stop a session failed" in FLAT_START


def test_F15_the_exit_0_row_does_not_claim_a_tag_listing_that_was_refused(kit):
    world = World(kit)
    write_state(kit, world.deploy(EAST))
    world.denied.add("get_resources")
    rc, lines = teardown(kit, world, EAST)
    assert rc == 0 and _verdict(lines).startswith("Teardown finished without errors")
    assert any(line.startswith("NOTE:") and "could not look for resources of this kit" in line for line in lines)
    assert "the listings by name and by tag showed nothing else" not in FLAT_README
    assert ("So did the listing by tag, unless a `NOTE:` line above says it could not be read (then "
            "99_verify_clean.py says NOT VERIFIED)") in FLAT_README


def test_F16_the_verdict_is_the_line_right_above_now_prove_it(kit):
    world = World(kit)
    write_state(kit, world.deploy(EAST))
    kit.BUILD_DIR.mkdir(parents=True, exist_ok=True)
    (kit.BUILD_DIR / "x.zip").write_bytes(b"PK")
    rc, lines = teardown(kit, world, EAST, ["--clean-local"])
    assert rc == 0 and _verdict(lines).startswith("Teardown finished without errors"), "\n".join(lines)
    assert "Removed the local .build folder." in lines and not kit.BUILD_DIR.exists()
    # with the NOTE on a refused tag lookup
    world = World(kit)
    write_state(kit, world.deploy(EAST))
    world.denied.add("get_resources")
    rc, lines = teardown(kit, world, EAST)
    assert rc == 0 and _verdict(lines).startswith("Teardown finished without errors"), "\n".join(lines)
    # with a state file that cannot be used, and the place named
    world = World(kit)
    world.deploy(EAST)
    kit.STATE_PATH.write_text("{not json")
    rc, lines = teardown(kit, world, EAST, ["--region", EAST, "--prefix", "kitdemo"])
    assert rc == 5 and _verdict(lines).startswith("TEARDOWN INCOMPLETE"), "\n".join(lines)


def test_F17_start_here_describes_the_last_lines_of_30_deploy_as_printed(kit):
    kit.BUILD_DIR.mkdir(parents=True, exist_ok=True)
    kit.PACKAGE_ZIP.write_bytes(b"PK")
    (kit.BUILD_DIR / "package_manifest.json").write_text(json.dumps({"entry_point": ["agentcore_app.py"]}))
    script = load_script("30_deploy.py")
    script.MANIFEST = kit.BUILD_DIR / "package_manifest.json"
    handlers = {"get_caller_identity": IDENTITY, "create_bucket": {}, "put_bucket_tagging": {}, "put_object": {},
                "create_role": {"Role": {"Arn": f"arn:aws:iam::{ACCOUNT}:role/r"}}, "put_role_policy": {},
                "create_agent_runtime": {"agentRuntimeId": RUNTIME_ID, "agentRuntimeArn": RUNTIME_ARN,
                                         "status": "CREATING"},
                "get_agent_runtime": {"status": "READY"},
                "list_agent_runtime_endpoints": {"runtimeEndpoints": [{"name": "DEFAULT", "status": "READY"}]}}
    lines: list[str] = []
    assert script.main(["--i-understand-this-bills"], aws=make_fake_aws(kit, handlers, lines), out=lines.append,
                       state=kit.State(kit.STATE_PATH)) == 0
    after = lines[next(i for i, line in enumerate(lines) if line.startswith("Deployed at")):]
    nexts = [i for i, line in enumerate(after) if line.startswith("Next:")]
    assert len(nexts) == 1 and after[nexts[0] + 1].startswith("      python ")
    assert "two `Next:` lines" not in FLAT_START
    assert ("`30_deploy.py`: a line that starts `Next:` and one more command under it, below a line that "
            "starts `Deployed at`.") in FLAT_START


def test_F18_after_stopped_for_another_region_naming_a_place_does_not_say_teardown_incomplete(kit):
    def named(region_named):
        world = World(kit)
        write_state(kit, world.deploy("us-west-2"))
        world.deploy(EAST)
        rc0, first = teardown(kit, world, EAST)
        rc, lines = teardown(kit, world, EAST, ["--region", region_named, "--prefix", "kitdemo"])
        return rc0, first, rc, lines
    rc0, first, rc, lines = named(EAST)
    assert rc0 == 4 and any("AWS_REGION=us-west-2 KIT_PREFIX=kitdemo python 90_teardown.py" in line
                            for line in first)
    assert rc == 4 and any(line.startswith("STOPPED") for line in lines)        # the shell's Region: stops again
    rc0, first, rc, lines = named("us-west-2")
    assert rc in (0, 1) and not any("TEARDOWN INCOMPLETE" in line for line in lines)   # an ordinary teardown
    # what the documents now say
    assert "If it records another place, run the command the `STOPPED` message gives." in FLAT_README
    assert "If it cannot be used, name the place, both values:" in FLAT_README
    assert ("found another Region, prefix or account in `.state.json` than the one in use (run the command its "
            "message gives), or could not read the file. Then, to tear down anyway, name the place") in FLAT_START
