"""Tests written from the round 4 independent review (2026-10-07).

Two readers. One followed the money: every script run as a process against a stateful fake account (its
findings are MINOR 6 to 9 and 16 here, with its check ids P03, P07, P09, P14, P150 and its sequence W045).
One ran the kits against a local emulator (its findings are "emulator 2" and "emulator 7" here). Each test
fails on the code as reviewed, except the ones whose name ends in "_control". REVIEW_NOTES_r4.md has the table.

Offline: no network, no credentials, no AWS call.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import botocore.exceptions as bex
import pytest

import budget_alarm as ba
import whats_running as wr
from helpers import TEST_ACCOUNT, Err, FakeAccount, RaisingClient, client_error, real_client
from test_budget_alarm import ARN, EMAIL, FLAG, OUR_TAGS, StubbedBudgets, expected_create, identity
from test_budget_alarm import run as run_budget
from test_review_r2 import KIT_A, KIT_B, KIT_C, budget, good_state, info_block, make_kit, result_line
from test_review_r2 import run as run_audit

COMMON_DIR = Path(ba.__file__).resolve().parent
README = (COMMON_DIR / "README.md").read_text(encoding="utf-8")
OTHER_ACCOUNT = "444455556666"  # a second AWS documentation placeholder account id
NAME = "kitdemo-monthly-cost"


def identity_of(account):
    return ("get_caller_identity", {"Account": account, "UserId": "AIDAEXAMPLE", "Arn": f"arn:aws:iam::{account}:user/example"}, {})


def create_in(account, tmp_path):
    request = expected_create()
    request["AccountId"] = account
    factory = StubbedBudgets([identity_of(account)], [("create_budget", {}, request)])
    return run_budget(["--email", EMAIL, FLAG], factory, tmp_path)


class LostAnswer:
    """sts answers; budgets.create_budget raises what the SDK raises when no answer comes back."""

    def __init__(self, exc):
        stubbed = StubbedBudgets([identity()], [])
        self.clients = {"sts": stubbed.clients["sts"], "budgets": RaisingClient(real_client("budgets"), "create_budget", exc)}

    def __call__(self, service, region):
        return self.clients[service]


# ==========================================================  MINOR 6 (P03, P07): which account was it?
def test_r4_minor6_create_says_which_account_got_the_budget(tmp_path):
    """Reviewed code: "Created budget 'kitdemo-monthly-cost'." and nothing about the account. Created under the
    wrong profile, the budget landed in the second account and nothing on the screen showed it."""
    code, out, state = create_in(OTHER_ACCOUNT, tmp_path)
    assert code == 0
    assert f"Created budget '{NAME}' in the account ending 6666" in out and "wrong profile" in out
    assert OTHER_ACCOUNT not in out, "the last four digits, never the whole id"
    record = json.loads(state.read_text(encoding="utf-8"))["budget"]
    assert record["account_tail"] == "6666" and OTHER_ACCOUNT not in state.read_text(encoding="utf-8")


def test_r4_minor6_show_and_delete_name_the_account_too(tmp_path):
    factory = StubbedBudgets([identity()], [("describe_budgets", {"Budgets": []}, {"AccountId": TEST_ACCOUNT, "MaxResults": 100})])
    code, out, _ = run_budget(["--show"], factory, tmp_path)
    assert code == 0 and "No budgets exist in this account (the one ending 3333)" in out
    create_in(TEST_ACCOUNT, tmp_path)
    factory = StubbedBudgets([identity()], [("delete_budget", {}, {"AccountId": TEST_ACCOUNT, "BudgetName": NAME})])
    code, out, _ = run_budget(["--delete", FLAG], factory, tmp_path)
    assert code == 0 and f"Deleted budget '{NAME}' in the account ending 3333" in out and TEST_ACCOUNT not in out


# ==========================================================  MINOR 7 (P09): "not created" when the answer was lost
@pytest.mark.parametrize("exc", [
    bex.ReadTimeoutError(endpoint_url="https://budgets.amazonaws.com"),
    bex.ConnectionClosedError(endpoint_url="https://budgets.amazonaws.com"),
    client_error("InternalErrorException", "try again later", "CreateBudget", status=500),
])
def test_r4_minor7_a_lost_answer_is_not_reported_as_not_created(exc, tmp_path):
    """Reviewed code: "FAILED, budget not created: ... Read timeout", while the budget existed."""
    code, out, state = run_budget(["--email", EMAIL, FLAG], LostAnswer(exc), tmp_path)
    assert code == ba.EXIT_ERROR
    assert "not created" not in out, "nothing says whether AWS carried the request out"
    assert out.splitlines()[-2].startswith("OUTCOME UNKNOWN: CreateBudget was sent") and f"The budget '{NAME}' MAY exist in the account ending 3333" in out
    assert "python budget_alarm.py --show" in out.splitlines()[-1] and "--delete" in out.splitlines()[-1]
    assert not state.exists(), "no record is written for a budget that may not exist; --delete finds it by its tag"


def test_r4_minor7_a_refusal_is_still_reported_as_not_created_control(tmp_path):
    factory = StubbedBudgets([identity()], [("create_budget", Err("AccessDeniedException", "not authorized"), expected_create())])
    code, out, state = run_budget(["--email", EMAIL, FLAG], factory, tmp_path)
    assert code == ba.EXIT_ERROR and "FAILED, budget not created" in out and not state.exists()


def test_r4_minor7_what_counts_as_an_unknown_outcome(tmp_path):
    assert not ba.outcome_unknown(client_error("AccessDeniedException", "no", status=403)), "AWS said no"
    assert not ba.outcome_unknown(bex.NoCredentialsError()), "nothing was sent"
    assert ba.outcome_unknown(TimeoutError()) and ba.outcome_unknown(client_error("InternalFailure", "x", status=503))
    factory = StubbedBudgets([identity()], [("create_budget", Err("AccessDeniedException", "not authorized"), expected_create())])
    _, out, _ = run_budget(["--email", EMAIL, FLAG], factory, tmp_path)
    assert "FAILED, budget not created in the account ending 3333" in out, "a refusal names the account as well"


def test_r4_minor7_no_credentials_before_the_call_is_not_an_unknown_outcome_control(tmp_path):
    stubbed = StubbedBudgets([], [])
    factory = lambda service, region: RaisingClient(stubbed.clients[service], "get_caller_identity", bex.NoCredentialsError())  # noqa: E731
    code, out, state = run_budget(["--email", EMAIL, FLAG], factory, tmp_path)
    assert code == ba.EXIT_ERROR and "FAILED, budget not created" in out and "OUTCOME UNKNOWN" not in out


# ==========================================================  MINOR 8 (P14): a record trusted across accounts
def test_r4_minor8_a_record_from_one_account_does_not_vouch_for_a_budget_in_another(tmp_path):
    """Reviewed code: recorded in account 3333, --delete while signed in to account 6666, which has its own
    untagged budget of that name: it was deleted, and the record of the real one was cleared."""
    create_in(TEST_ACCOUNT, tmp_path)
    other_arn = f"arn:aws:budgets::{OTHER_ACCOUNT}:budget/{NAME}"
    theirs = [{"Key": "team", "Value": "finance"}]
    factory = StubbedBudgets([identity_of(OTHER_ACCOUNT)], [("list_tags_for_resource", {"ResourceTags": theirs}, {"ResourceARN": other_arn})])
    code, out, state = run_budget(["--delete", FLAG], factory, tmp_path)
    assert code == ba.EXIT_REFUSED == 3, out
    assert "REFUSED" in out and "records 'kitdemo-monthly-cost' for the account ending 3333" in out
    assert "signed in to the account ending 6666" in out
    factory.assert_all_calls_made()  # and no DeleteBudget: the Stubber would have raised on one
    assert json.loads(state.read_text(encoding="utf-8"))["budget"]["account_tail"] == "3333", "the record is left alone"


def test_r4_minor8_a_tagged_budget_in_the_other_account_goes_and_the_record_stays(tmp_path):
    create_in(TEST_ACCOUNT, tmp_path)
    other_arn = f"arn:aws:budgets::{OTHER_ACCOUNT}:budget/{NAME}"
    factory = StubbedBudgets([identity_of(OTHER_ACCOUNT)], [
        ("list_tags_for_resource", {"ResourceTags": OUR_TAGS}, {"ResourceARN": other_arn}),
        ("delete_budget", {}, {"AccountId": OTHER_ACCOUNT, "BudgetName": NAME})])
    code, out, state = run_budget(["--delete", FLAG], factory, tmp_path)
    assert code == 0 and f"Deleted budget '{NAME}' in the account ending 6666" in out
    assert json.loads(state.read_text(encoding="utf-8"))["budget"]["account_tail"] == "3333"


def test_r4_minor8_in_its_own_account_the_record_still_decides_control(tmp_path):
    create_in(TEST_ACCOUNT, tmp_path)
    factory = StubbedBudgets([identity()], [("delete_budget", {}, {"AccountId": TEST_ACCOUNT, "BudgetName": NAME})])
    code, out, state = run_budget(["--delete", FLAG], factory, tmp_path)
    assert code == 0 and not state.exists()
    factory.assert_all_calls_made()  # no tag was read


def test_r4_minor8_show_does_not_mark_a_same_named_budget_in_another_account(tmp_path):
    create_in(TEST_ACCOUNT, tmp_path)
    factory = StubbedBudgets([identity_of(OTHER_ACCOUNT)], [
        ("describe_budgets", {"Budgets": [budget(NAME)]}, {"AccountId": OTHER_ACCOUNT, "MaxResults": 100}),
        ("describe_notifications_for_budget", {"Notifications": []}, {"AccountId": OTHER_ACCOUNT, "BudgetName": NAME, "MaxResults": 100})])
    code, out, _ = run_budget(["--show"], factory, tmp_path)
    assert code == 0 and "1 budget(s) in this account, the one ending 6666" in out
    assert "this is the budget budget_alarm.py created" not in out


def test_r4_minor8_the_audit_row_goes_by_the_account_of_the_record(tmp_path, monkeypatch, capsys):
    for kit in (KIT_A, KIT_B, KIT_C):
        make_kit(tmp_path, kit, state=good_state())
    path = tmp_path / "common-state.json"
    path.write_text(json.dumps({"budget": {"name": NAME, "account_tail": "6666"}}), encoding="utf-8")
    monkeypatch.setattr(wr, "BUDGET_STATE_FILE", path, raising=False)
    account = FakeAccount({("budgets", "describe_budgets"): {"Budgets": [budget(NAME)]}})
    code, out = run_audit([], account, capsys, tmp_path, monkeypatch)
    block = info_block(out)
    assert code == 0 and "recorded in common/.state.json)" not in block, "that record is for another account"
    assert "NOTE: common/.state.json records a budget that budget_alarm.py created in the account ending 6666" in block
    assert wr.recorded_budget(path) == (NAME, "6666") and wr.recorded_budget_name(path) == NAME


# ==========================================================  MINOR 9 (P150): a record of the wrong shape
@pytest.mark.parametrize("text", ['{"budget": "kitdemo-monthly-cost"}', '{"budget": ["x"]}', '{"budget": 7}'])
def test_r4_minor9_delete_does_not_crash_on_a_record_that_is_not_an_object(text, tmp_path):
    """Reviewed code: AttributeError, a traceback, exit 1."""
    state = tmp_path / ".state.json"
    state.write_text(text, encoding="utf-8")
    factory = StubbedBudgets([identity()], [
        ("list_tags_for_resource", {"ResourceTags": OUR_TAGS}, {"ResourceARN": ARN}),
        ("delete_budget", {}, {"AccountId": TEST_ACCOUNT, "BudgetName": NAME})])
    code, out, _ = run_budget(["--delete", FLAG], factory, tmp_path)
    assert code == 0 and f"Deleted budget '{NAME}'" in out, "with no usable record the tag decides"
    factory.assert_all_calls_made()
    assert state.read_text(encoding="utf-8") == text, "a record this script cannot read is not rewritten"
    code, out, _ = run_budget(["--delete", "--dry-run"], lambda *a: (_ for _ in ()).throw(AssertionError("no call")), tmp_path)
    assert code == 0 and "ListTagsForResource" in out


# ==========================================================  emulator 2: "exported" read as a name prefix
KIT_A_COMMENT = (
    "# Kit A settings. Copy to config.env and edit:   cp config.example.env config.env\n"
    "# Environment variables with the same names win over this file. So an AWS_REGION or KIT_PREFIX exported in\n"
    "# your shell overrides the value here.\n"
    "AWS_REGION=us-east-1\n\n"
    "# Every resource name starts with this, then \"-kita-\". KIT_PREFIX: lower-case letters, digits, hyphens.\n"
    "KIT_PREFIX=kitdemo\n")


def test_r4_emulator2_a_comment_that_mentions_kit_prefix_names_no_prefix(tmp_path, monkeypatch, capsys):
    """Reviewed code: "Audited: ... prefixes kitdemo, exported." in every RESULT line once the owner had done
    the README's own step, cp config.example.env config.env."""
    make_kit(tmp_path, KIT_A, config=KIT_A_COMMENT, state=good_state())
    scope = wr.discover_scope(tmp_path, env={})
    assert sorted(scope.prefixes) == ["kitdemo"], f"prefixes read: {sorted(scope.prefixes)}"
    code, out = run_audit(["--dry-run"], FakeAccount(), capsys, tmp_path, monkeypatch)
    assert not re.search(r"prefix(es)?\b[^\n]*\bexported\b", out) and "lower-case" not in out and "kitdemo" in out


def test_r4_emulator2_the_real_example_files_give_no_stray_prefix():
    kits = COMMON_DIR.parent
    examples = sorted(kits.glob("kit_*/config.example.env"))
    if not examples:
        pytest.skip("no kit folder is beside common/")
    for example in examples:
        found = {m.group(1) for m in wr._CONFIG_PREFIX_RE.finditer(example.read_text(encoding="utf-8"))}
        assert found <= {"kitdemo"}, f"{example.parent.name}/config.example.env copied to config.env would add {found}"


def test_r4_emulator2_a_prefix_that_is_assigned_is_still_found_control(tmp_path):
    config = ("# KIT_PREFIX=oldone   # the prefix I used last week\nset KIT_PREFIX = 'acme'\nKIT_PREFIX: \"my-kit\"\n"
              "export KIT_PREFIX=third;\n")
    make_kit(tmp_path, KIT_A, config=config, state=good_state())
    scope = wr.discover_scope(tmp_path, env={})
    assert {"oldone", "acme", "my-kit", "third"} <= set(scope.prefixes)


# ==========================================================  emulator 7: a parent folder called "tests"
def test_r4_emulator7_the_sibling_check_works_under_a_folder_called_tests(tmp_path, monkeypatch):
    """Reviewed code: every file of the kit was dropped ("tests" anywhere in the absolute path), so nine tests
    of test_against_sibling_kits.py failed in a checkout below a folder of that name."""
    import test_against_sibling_kits as siblings

    root = tmp_path / "tests" / "aws_kits"
    kit = root / wr.KIT_FOLDERS["a"]
    (kit / "tests").mkdir(parents=True)
    (kit / "kitlib.py").write_text("NAME_INFIX = 'kita'\n", encoding="utf-8")
    (kit / "tests" / "test_x.py").write_text("ONLY_IN_A_TEST = 1\n", encoding="utf-8")
    monkeypatch.setattr(siblings, "KITS_ROOT", root)
    source = siblings.kit_source("a")
    assert "NAME_INFIX" in source, "the kit's own code is read whatever the folders above it are called"
    assert "ONLY_IN_A_TEST" not in source, "the kit's tests folder is still left out"


# ==========================================================  the record of this round, and the one table
def test_r4_readme_exit_code_table_says_what_kit_a_now_does():
    rows = {line.split("|")[1].strip(): line.split("|") for line in README.splitlines() if re.match(r"^\| \d+ \|", line)}
    kit_a_1, kit_a_2 = rows["1"][4], rows["2"][4]
    assert "stopped after it had sent a create or delete call" in kit_a_1
    assert "before it created or deleted anything" in kit_a_2
    assert "1 or 2 in kit A" in README, "a damaged state file: unchanged for kit A"


def test_r4_readme_states_the_stale_kit_a_state_file_limit_and_points_to_the_notes():
    section2 = README.split("## 2. Problems first")[1].split("## 3. Before you start")[0]
    assert "older copy" in section2 and "W045" in section2
    assert re.search(r"Reviewed independently on 2026-10-07 \(round 4\): \d+ findings for this folder, \d+ fixed, "
                     r"\d+ stated as a limit, \d+ not changed \(`REVIEW_NOTES_r4\.md`\)", README)
    notes = (COMMON_DIR / "REVIEW_NOTES_r4.md").read_text(encoding="utf-8")
    for finding in ("MINOR 6", "MINOR 7", "MINOR 8", "MINOR 9", "MINOR 16", "Emulator 2", "Emulator 7"):
        assert finding in notes, finding
    section5 = README.split("### budget_alarm.py")[1].split("### whats_running.py")[0]
    assert "last four digits" in section5 and "OUTCOME UNKNOWN" in section5
