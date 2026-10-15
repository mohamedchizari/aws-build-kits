"""Tests written from the round 5 independent review (read 2026-10-07, fixed 2026-10-08).

One reader, kit A and this folder. Its findings that touch this folder: F1 (a sign-in error raised by a create
call taken as "nothing was sent"), F2 (budget_alarm.py did not use kit A's retry rule, and the delete failure
line named no account) and F3 (the exit code table said "whatever stopped it" for kit A, Ctrl-C included).
Each test fails on the code as reviewed, except the ones whose name ends in "_control". The record is in
../kit_a_gpu_endpoint/REVIEW_NOTES_r5.md.

Offline: no network, no credentials, no AWS call.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import botocore.exceptions as bex
import pytest

import budget_alarm as ba
from helpers import TEST_ACCOUNT, RaisingClient, real_client
from test_budget_alarm import EMAIL, FLAG, StubbedBudgets, identity
from test_budget_alarm import run as run_budget
from test_review_r4 import LostAnswer, create_in

COMMON_DIR = Path(ba.__file__).resolve().parent
README = (COMMON_DIR / "README.md").read_text(encoding="utf-8")
NAME = "kitdemo-monthly-cost"


def answered(code, message, status=400, attempts=0, operation="CreateBudget"):
    """A ClientError as botocore raises it; attempts = how many times the SDK had sent the request AGAIN."""
    return bex.ClientError({"Error": {"Code": code, "Message": message},
                            "ResponseMetadata": {"HTTPStatusCode": status, "RetryAttempts": attempts}}, operation)


def delete_raising(exc, tmp_path):
    create_in(TEST_ACCOUNT, tmp_path)  # writes the record of a budget this script created
    stubbed = StubbedBudgets([identity()], [])
    clients = {"sts": stubbed.clients["sts"], "budgets": RaisingClient(real_client("budgets"), "delete_budget", exc)}
    return run_budget(["--delete", FLAG], lambda service, region: clients[service], tmp_path)


def record(state):
    """The budget record in common/.state.json, None when there is none (an empty state file is removed)."""
    return json.loads(state.read_text(encoding="utf-8")).get("budget") if state.exists() else None


# ==========================================================  F1: a sign-in error after a try may have gone out
def test_r5_f1_sign_in_error_raised_by_create_budget_is_outcome_unknown(tmp_path):
    code, out, state = run_budget(["--email", EMAIL, FLAG], LostAnswer(bex.UnauthorizedSSOTokenError()), tmp_path)
    assert code == ba.EXIT_ERROR and "OUTCOME UNKNOWN: CreateBudget was sent" in out
    assert "not created" not in out and "ending 3333" in out


@pytest.mark.parametrize("exc", [bex.NoCredentialsError(), bex.ParamValidationError(report="x"),
                                 bex.NoRegionError(), bex.ProfileNotFound(profile="p")])
def test_r5_f1_errors_raised_before_the_first_try_are_still_nothing_sent_control(exc):
    assert not ba.outcome_unknown(exc)


# ==========================================================  F2: kit A's retry rule, and the delete side
def test_r5_f2_duplicate_answered_to_a_retry_is_outcome_unknown_and_says_the_budget_exists(tmp_path):
    exc = answered("DuplicateRecordException", f"Error creating budget: {NAME} - the budget already exists.", attempts=1)
    code, out, state = run_budget(["--email", EMAIL, FLAG], LostAnswer(exc), tmp_path)
    assert code == ba.EXIT_ERROR and "OUTCOME UNKNOWN: CreateBudget was sent" in out and "not created" not in out
    assert f"a budget named '{NAME}' exists in the account ending 3333" in out


def test_r5_f2_duplicate_on_the_first_try_is_still_a_refusal_control(tmp_path):
    exc = answered("DuplicateRecordException", f"Error creating budget: {NAME} - the budget already exists.")
    code, out, state = run_budget(["--email", EMAIL, FLAG], LostAnswer(exc), tmp_path)
    assert code == ba.EXIT_ERROR and "FAILED, budget not created in the account ending 3333" in out
    assert "OUTCOME UNKNOWN" not in out


def test_r5_f2_the_retry_rule_itself():
    assert ba.outcome_unknown(answered("AccessDeniedException", "no", status=403, attempts=2))
    assert not ba.outcome_unknown(answered("AccessDeniedException", "no", status=403, attempts=0))
    assert ba.outcome_unknown(bex.TokenRetrievalError(provider="sso", error_msg="expired"))


def test_r5_f2_delete_timeout_is_outcome_unknown_names_the_account_and_keeps_the_record(tmp_path):
    code, out, state = delete_raising(bex.ReadTimeoutError(endpoint_url="https://budgets.amazonaws.com"), tmp_path)
    assert code == ba.EXIT_ERROR and "budget not deleted" not in out
    line = next(line for line in out.splitlines() if line.startswith("OUTCOME UNKNOWN: DeleteBudget was sent"))
    assert "MAY have been deleted in the account ending 3333" in line
    assert record(state)["name"] == NAME, "the record stays until a delete is confirmed"


def test_r5_f2_a_delete_refusal_names_the_account(tmp_path):
    code, out, state = delete_raising(answered("AccessDeniedException", "not allowed", 403, operation="DeleteBudget"),
                                      tmp_path)
    assert code == ba.EXIT_ERROR and "FAILED, budget not deleted in the account ending 3333: " in out


def test_r5_f2_not_found_answered_to_a_delete_retry_does_not_say_nothing_was_deleted(tmp_path):
    exc = answered("NotFoundException", "Unable to delete budget: it does not exist", attempts=1, operation="DeleteBudget")
    code, out, state = delete_raising(exc, tmp_path)
    assert code == ba.EXIT_OK and "an earlier try of this run may have deleted it" in out
    assert "Nothing was deleted now" not in out and record(state) is None


# ==========================================================  documents
def test_r5_f3_exit_table_gives_kit_a_ctrl_c_its_own_code():
    rows = {line.split("|")[1].strip(): line.split("|") for line in README.splitlines() if re.match(r"^\| \d+ \|", line)}
    kit_a_1, kit_a_130 = rows["1"][4], rows["130"][4]
    assert "whatever stopped it (" not in kit_a_1 and "Ctrl-C" in kit_a_1 and "130" in kit_a_1
    assert "names" in kit_a_130


def test_r5_f2_readme_says_outcome_unknown_for_retries_sign_in_and_delete():
    section5 = " ".join(README.split("### budget_alarm.py")[1].split("### whats_running.py")[0].split())
    line = next(part for part in section5.split("- ") if part.startswith("Says `OUTCOME UNKNOWN`"))
    assert "DeleteBudget" in line and "sent again" in line and "sign-in" in line
    assert re.search(r"Reviewed independently on 2026-10-08 \(round 5\)", README)
