"""Offline tests for budget_alarm.py. No network, no credentials, no AWS call."""
from __future__ import annotations

import datetime as dt
import json

import pytest
from botocore.stub import Stubber

import budget_alarm as ba
from helpers import Err, forbidden_factory, real_client

EMAIL = "owner@example.com"
ACCOUNT = "111122223333"
FLAG = "--i-understand-this-changes-my-account"


class StubbedBudgets:
    """Client factory for sts and budgets, answered by botocore's Stubber in order."""

    def __init__(self, sts_steps=None, budgets_steps=None):
        self.clients = {"sts": real_client("sts"), "budgets": real_client("budgets")}
        self.stubbers = {name: Stubber(client) for name, client in self.clients.items()}
        for name, steps in (("sts", sts_steps), ("budgets", budgets_steps)):
            for method, payload, expected in steps or []:
                if isinstance(payload, Err):
                    self.stubbers[name].add_client_error(method, service_error_code=payload.code, service_message=payload.message, expected_params=expected)
                else:
                    self.stubbers[name].add_response(method, payload, expected)
            self.stubbers[name].activate()
        self.requested = []

    def __call__(self, service, region):
        self.requested.append(service)
        return self.clients[service]

    def assert_all_calls_made(self):
        for stubber in self.stubbers.values():
            stubber.assert_no_pending_responses()


def identity():
    return ("get_caller_identity", {"Account": ACCOUNT, "UserId": "AIDAEXAMPLE", "Arn": f"arn:aws:iam::{ACCOUNT}:user/example"}, {})


def run(argv, factory, tmp_path):
    lines: list[str] = []
    state = tmp_path / ".state.json"
    code = ba.main(argv, client_factory=factory, out=lines.append, state_path=state)
    return code, "\n".join(lines), state


# ------------------------------------------------------------------- refusal
def test_refuses_to_create_without_the_flag_and_makes_no_call(tmp_path):
    code, out, state = run(["--email", EMAIL], forbidden_factory, tmp_path)
    assert code == ba.EXIT_REFUSED == 3
    assert "REFUSED" in out and FLAG in out
    assert "no AWS call was made" in out
    assert not state.exists()
    assert EMAIL not in out


def test_refuses_to_delete_without_the_flag_and_makes_no_call(tmp_path):
    code, out, _ = run(["--delete"], forbidden_factory, tmp_path)
    assert code == ba.EXIT_REFUSED
    assert "REFUSED" in out


def test_flag_alone_is_not_enough_email_is_required(tmp_path, capsys):
    code, _, state = run([FLAG], forbidden_factory, tmp_path)
    assert code == ba.EXIT_USAGE == 64
    assert "an address is required" in capsys.readouterr().err
    assert not state.exists()


# ------------------------------------------------------------------- dry run
def test_dry_run_prints_the_request_masks_the_email_and_makes_no_call(tmp_path):
    code, out, state = run(["--email", EMAIL, "--dry-run", FLAG], forbidden_factory, tmp_path)
    assert code == 0
    assert "DRY RUN: no AWS call was made" in out
    assert "budgets.CreateBudget(" in out and "sts.GetCallerIdentity()" in out
    assert EMAIL not in out and "example.com" not in out and "o***@***" in out
    assert not state.exists()


# -------------------------------------------------------------------- create
def expected_create(thresholds=(50.0, 80.0, 100.0), limit="25", name="kitdemo-monthly-cost", cost_types=True, forecast=None):
    subs = [{"SubscriptionType": "EMAIL", "Address": EMAIL}]
    notes = [
        {"Notification": {"NotificationType": "ACTUAL", "ComparisonOperator": "GREATER_THAN", "Threshold": t, "ThresholdType": "PERCENTAGE"}, "Subscribers": subs}
        for t in thresholds
    ]
    if forecast is not None:
        notes.append({"Notification": {"NotificationType": "FORECASTED", "ComparisonOperator": "GREATER_THAN", "Threshold": forecast, "ThresholdType": "PERCENTAGE"}, "Subscribers": subs})
    budget = {"BudgetName": name, "BudgetLimit": {"Amount": limit, "Unit": "USD"}, "TimeUnit": "MONTHLY", "BudgetType": "COST"}
    if cost_types:
        budget["CostTypes"] = {
            "IncludeTax": True, "IncludeSubscription": True, "UseBlended": False, "IncludeRefund": False, "IncludeCredit": False,
            "IncludeUpfront": True, "IncludeRecurring": True, "IncludeOtherSubscription": True, "IncludeSupport": True,
            "IncludeDiscount": True, "UseAmortized": False,
        }
    tags = [{"Key": "project", "Value": "aws-kits"}, {"Key": "created-by", "Value": "aws-kits-budget-alarm"}]
    return {"AccountId": ACCOUNT, "Budget": budget, "NotificationsWithSubscribers": notes, "ResourceTags": tags}


def test_create_with_flag_sends_exactly_the_expected_request(tmp_path):
    factory = StubbedBudgets([identity()], [("create_budget", {}, expected_create())])
    code, out, state = run(["--email", EMAIL, FLAG], factory, tmp_path)
    assert code == 0
    assert "Created budget 'kitdemo-monthly-cost'" in out
    assert "free of charge" in out and "aws-budgets/pricing/ (read 2026-10-07)" in out
    assert "does not stop, pause or delete anything" in out
    factory.assert_all_calls_made()


def test_email_and_account_id_are_never_stored_or_printed(tmp_path):
    factory = StubbedBudgets([identity()], [("create_budget", {}, expected_create())])
    code, out, state = run(["--email", EMAIL, FLAG], factory, tmp_path)
    assert code == 0
    saved = state.read_text(encoding="utf-8")
    assert EMAIL not in saved and "example.com" not in saved and ACCOUNT not in saved
    assert json.loads(saved)["budget"]["name"] == "kitdemo-monthly-cost"
    assert EMAIL not in out and ACCOUNT not in out
    assert sorted(p.name for p in tmp_path.iterdir()) == [".state.json"]


def test_create_honours_limit_thresholds_name_forecast_and_cost_type_switch(tmp_path):
    expected = expected_create(thresholds=(25.0, 90.0), limit="10.5", name="acme-alarm", cost_types=False, forecast=100.0)
    factory = StubbedBudgets([identity()], [("create_budget", {}, expected)])
    argv = ["--email", EMAIL, "--limit", "10.50", "--thresholds", "90,25", "--forecast-threshold", "100", "--name", "acme-alarm", "--aws-default-cost-types", FLAG]
    code, _, _ = run(argv, factory, tmp_path)
    assert code == 0
    factory.assert_all_calls_made()


def test_duplicate_budget_is_reported_as_failure_with_no_state(tmp_path):
    factory = StubbedBudgets([identity()], [("create_budget", Err("DuplicateRecordException", "budget already exists"), expected_create())])
    code, out, state = run(["--email", EMAIL, FLAG], factory, tmp_path)
    assert code == ba.EXIT_ERROR == 1
    assert "FAILED, budget not created" in out and "already exists" in out
    assert not state.exists()


def test_access_denied_on_create_is_reported_not_swallowed(tmp_path):
    factory = StubbedBudgets([identity()], [("create_budget", Err("AccessDeniedException", "not authorized"), expected_create())])
    code, out, state = run(["--email", EMAIL, FLAG], factory, tmp_path)
    assert code == 1 and "AccessDeniedException" in out and not state.exists()


@pytest.mark.parametrize(
    "argv, fragment",
    [
        (["--email", "not-an-address", FLAG], "does not look like an email address"),
        (["--email", EMAIL, "--thresholds", "10,20,30,40,50,60", FLAG], "at most 5 notifications"),
        (["--email", EMAIL, "--thresholds", "10,20,30,40,50", "--forecast-threshold", "100", FLAG], "at most 5 notifications"),
        (["--email", EMAIL, "--thresholds", "fifty", FLAG], "comma-separated numbers"),
        (["--email", EMAIL, "--thresholds", "0", FLAG], "above 0"),
        (["--email", f"{EMAIL} extra", FLAG], "does not look like an email address"),
        (["--email", EMAIL, "--limit", "-3", FLAG], "--limit must be above 0"),
        (["--email", EMAIL, "--limit", "lots", FLAG], "--limit must be a number"),
        (["--email", EMAIL, "--name", "bad:name", FLAG], "budget name must be"),
    ],
)
def test_bad_input_is_a_usage_error_before_any_call(argv, fragment, tmp_path, capsys):
    code, _, state = run(argv, forbidden_factory, tmp_path)
    assert code == 64
    err = capsys.readouterr().err
    assert fragment in err
    assert "not-an-address" not in err  # never echo what was typed as an email
    assert not state.exists()


def test_show_and_delete_cannot_be_combined():
    with pytest.raises(SystemExit) as excinfo:
        ba.main(["--show", "--delete"], client_factory=forbidden_factory)
    assert excinfo.value.code == 64


# ---------------------------------------------------------------------- show
def budget(name, limit="25", actual="3.10"):
    return {
        "BudgetName": name, "BudgetType": "COST", "TimeUnit": "MONTHLY",
        "BudgetLimit": {"Amount": limit, "Unit": "USD"},
        "CalculatedSpend": {"ActualSpend": {"Amount": actual, "Unit": "USD"}, "ForecastedSpend": {"Amount": "9.00", "Unit": "USD"}},
        "LastUpdatedTime": dt.datetime(2026, 10, 6, tzinfo=dt.timezone.utc),
    }


def note(threshold):
    return {"NotificationType": "ACTUAL", "ComparisonOperator": "GREATER_THAN", "Threshold": threshold, "ThresholdType": "PERCENTAGE"}


def test_show_is_read_only_and_follows_pagination(tmp_path):
    factory = StubbedBudgets(
        [identity()],
        [
            ("describe_budgets", {"Budgets": [budget("kitdemo-monthly-cost")], "NextToken": "page-2"}, {"AccountId": ACCOUNT, "MaxResults": 100}),
            ("describe_budgets", {"Budgets": [budget("another-budget", limit="100")]}, {"AccountId": ACCOUNT, "MaxResults": 100, "NextToken": "page-2"}),
            ("describe_notifications_for_budget", {"Notifications": [note(50.0), note(100.0)]}, {"AccountId": ACCOUNT, "BudgetName": "kitdemo-monthly-cost", "MaxResults": 100}),
            ("describe_notifications_for_budget", {"Notifications": []}, {"AccountId": ACCOUNT, "BudgetName": "another-budget", "MaxResults": 100}),
        ],
    )
    code, out, state = run(["--show"], factory, tmp_path)
    assert code == 0
    assert "2 budget(s) in this account" in out
    assert "kitdemo-monthly-cost: COST MONTHLY, limit 25 USD, actual 3.10 USD" in out
    assert "ACTUAL GREATER_THAN 50.0 PERCENTAGE" in out
    assert "another-budget" in out and "NO ALERTS SET" in out
    assert "at least once per day" in out
    assert ACCOUNT not in out and not state.exists()
    factory.assert_all_calls_made()


def test_show_with_no_budgets_says_so_plainly(tmp_path):
    factory = StubbedBudgets([identity()], [("describe_budgets", {"Budgets": []}, {"AccountId": ACCOUNT, "MaxResults": 100})])
    code, out, _ = run(["--show"], factory, tmp_path)
    assert code == 0 and "No budgets exist in this account" in out


def test_show_failure_is_not_reported_as_no_budgets(tmp_path):
    factory = StubbedBudgets([identity()], [("describe_budgets", Err("AccessDeniedException", "not authorized to perform budgets:ViewBudget"), {"AccountId": ACCOUNT, "MaxResults": 100})])
    code, out, _ = run(["--show"], factory, tmp_path)
    assert code == 1
    assert "COULD NOT LIST BUDGETS" in out and "AccessDeniedException" in out
    assert "No budgets exist" not in out


def test_show_without_credentials_fails_plainly_and_does_not_say_no_budgets(tmp_path):
    import botocore.exceptions as bex
    from helpers import RaisingClient

    def factory(service, region):
        return RaisingClient(real_client(service), "get_caller_identity", bex.NoCredentialsError())

    code, out, _ = run(["--show"], factory, tmp_path)
    assert code == 1
    assert "COULD NOT LIST BUDGETS" in out and "no usable AWS credentials" in out
    assert "No budgets exist" not in out


def test_show_dry_run_makes_no_call(tmp_path):
    code, out, _ = run(["--show", "--dry-run"], forbidden_factory, tmp_path)
    assert code == 0 and "budgets.DescribeBudgets" in out


# -------------------------------------------------------------------- delete
def test_delete_with_flag_uses_the_name_in_state_and_clears_it(tmp_path):
    state = tmp_path / ".state.json"
    state.write_text(json.dumps({"budget": {"name": "kitdemo-monthly-cost"}}), encoding="utf-8")
    factory = StubbedBudgets([identity()], [("delete_budget", {}, {"AccountId": ACCOUNT, "BudgetName": "kitdemo-monthly-cost"})])
    code, out, _ = run(["--delete", FLAG], factory, tmp_path)
    assert code == 0 and "Deleted budget 'kitdemo-monthly-cost'" in out
    assert not state.exists()
    factory.assert_all_calls_made()


def test_delete_failure_keeps_state(tmp_path):
    state = tmp_path / ".state.json"
    state.write_text(json.dumps({"budget": {"name": "kitdemo-monthly-cost"}}), encoding="utf-8")
    factory = StubbedBudgets([identity()], [("delete_budget", Err("AccessDeniedException", "not authorized to perform budgets:ModifyBudget"), {"AccountId": ACCOUNT, "BudgetName": "kitdemo-monthly-cost"})])
    code, out, _ = run(["--delete", FLAG], factory, tmp_path)
    assert code == 1 and "FAILED, budget not deleted" in out
    assert state.exists()


# ----------------------------------------------------------------- internals
def test_call_refuses_operations_outside_the_list():
    budgets = real_client("budgets")
    with pytest.raises(ba.AwsCallFailed, match="refused"):
        ba._call(budgets, "CreateBudgetAction")
    with pytest.raises(ba.AwsCallFailed, match="refused"):
        ba._call(budgets, "UpdateBudget")


def test_this_script_never_creates_budget_actions():
    assert not any("Action" in op for _, op, _ in ba.AWS_OPERATIONS)


def test_mask_email_hides_the_local_part():
    assert ba.mask_email("someone@example.org") == "s***@***"


# ------------------------------------------- round 1 review, MINOR findings 1, 3, 4, 7
PRIVATE_EMAIL = "owner.name@family-surname.example.org"
ARN = f"arn:aws:budgets::{ACCOUNT}:budget/kitdemo-monthly-cost"
OUR_TAGS = [{"Key": "project", "Value": "aws-kits"}, {"Key": "created-by", "Value": "aws-kits-budget-alarm"}]


def test_minor1_account_id_in_aws_error_text_is_cut_to_four_digits(tmp_path):
    message = f"User: arn:aws:iam::{ACCOUNT}:user/jane.doe is not authorized to perform: budgets:ModifyBudget on resource: {ARN}"
    factory = StubbedBudgets([identity()], [("create_budget", Err("AccessDeniedException", message), expected_create())])
    code, out, state = run(["--email", EMAIL, FLAG], factory, tmp_path)
    assert code == 1 and "AccessDeniedException" in out
    assert ACCOUNT not in out
    assert "[account ending 3333]" in out
    assert not state.exists()


def test_minor1_supplied_address_in_aws_error_text_is_masked(tmp_path):
    request = expected_create()
    for n in request["NotificationsWithSubscribers"]:
        n["Subscribers"] = [{"SubscriptionType": "EMAIL", "Address": PRIVATE_EMAIL}]
    message = f"Subscriber address {PRIVATE_EMAIL.upper()} is not valid, nor is {PRIVATE_EMAIL}"
    factory = StubbedBudgets([identity()], [("create_budget", Err("InvalidParameterException", message), request)])
    code, out, _ = run(["--email", PRIVATE_EMAIL, FLAG], factory, tmp_path)
    assert code == 1 and "InvalidParameterException" in out
    assert PRIVATE_EMAIL not in out and PRIVATE_EMAIL.upper() not in out
    assert "family-surname" not in out.lower() and "owner.name" not in out.lower()


def test_minor1_address_can_come_from_the_environment_instead_of_the_command_line(tmp_path, monkeypatch):
    monkeypatch.setenv("BUDGET_ALARM_EMAIL", f"{EMAIL}, second@example.org")
    request = expected_create()
    for n in request["NotificationsWithSubscribers"]:
        n["Subscribers"] = [{"SubscriptionType": "EMAIL", "Address": EMAIL}, {"SubscriptionType": "EMAIL", "Address": "second@example.org"}]
    factory = StubbedBudgets([identity()], [("create_budget", {}, request)])
    code, out, state = run([FLAG], factory, tmp_path)
    assert code == 0 and "to 2 address(es)" in out
    assert EMAIL not in out and "second@example.org" not in out
    assert "example" not in state.read_text(encoding="utf-8")
    factory.assert_all_calls_made()


def test_minor1_a_bad_address_in_the_environment_is_not_echoed(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BUDGET_ALARM_EMAIL", "not-an-address")
    code, out, _ = run([FLAG], forbidden_factory, tmp_path)
    assert code == 64
    assert "not-an-address" not in capsys.readouterr().err and "not-an-address" not in out


@pytest.mark.parametrize(
    "argv, fragment",
    [
        (["--limit", "0"], "--limit"),
        (["--limit", "0.004"], "--limit"),          # would have been sent to AWS as Amount "0"
        (["--limit", "-1"], "--limit"),
        (["--limit", "nan"], "--limit"),
        (["--limit", "inf"], "--limit"),
        (["--limit=-inf"], "--limit"),
        (["--thresholds", "nan"], "threshold"),
        (["--thresholds", "50,inf"], "threshold"),
        (["--thresholds", "0"], "threshold"),
        (["--thresholds=-5,50"], "threshold"),
        (["--forecast-threshold", "nan"], "--forecast-threshold"),
        (["--forecast-threshold", "inf"], "--forecast-threshold"),
        (["--forecast-threshold", "0"], "--forecast-threshold"),
        (["--forecast-threshold", "-10"], "--forecast-threshold"),
    ],
)
def test_minor3_zero_negative_nan_and_infinite_numbers_are_refused_even_in_a_dry_run(argv, fragment, tmp_path, capsys):
    code, out, state = run(["--email", EMAIL, "--dry-run"] + argv, forbidden_factory, tmp_path)
    assert code == 64, out
    assert fragment in capsys.readouterr().err
    assert "CreateBudget" not in out and not state.exists()


def test_minor3_the_smallest_limit_that_survives_rounding_is_accepted(tmp_path):
    code, out, _ = run(["--email", EMAIL, "--dry-run", "--limit", "0.01"], forbidden_factory, tmp_path)
    assert code == 0 and '"Amount": "0.01"' in out


def test_minor4_delete_refuses_a_budget_this_script_did_not_create(tmp_path):
    # No state record for this name, and its tags do not carry this script's mark: no DeleteBudget call is made.
    other = f"arn:aws:budgets::{ACCOUNT}:budget/someone-elses-budget"
    factory = StubbedBudgets([identity()], [("list_tags_for_resource", {"ResourceTags": [{"Key": "team", "Value": "finance"}]}, {"ResourceARN": other})])
    state = tmp_path / ".state.json"
    state.write_text(json.dumps({"budget": {"name": "kitdemo-monthly-cost"}}), encoding="utf-8")
    code, out, _ = run(["--delete", "--name", "someone-elses-budget", FLAG], factory, tmp_path)
    assert code == ba.EXIT_REFUSED == 3
    assert "REFUSED" in out and "not created by this script" in out
    assert json.loads(state.read_text(encoding="utf-8"))["budget"]["name"] == "kitdemo-monthly-cost"
    factory.assert_all_calls_made()  # and nothing else: the Stubber would have raised on a DeleteBudget call


def test_minor4_delete_without_a_state_file_goes_by_the_tag_this_script_sets(tmp_path):
    factory = StubbedBudgets(
        [identity()],
        [
            ("list_tags_for_resource", {"ResourceTags": OUR_TAGS}, {"ResourceARN": ARN}),
            ("delete_budget", {}, {"AccountId": ACCOUNT, "BudgetName": "kitdemo-monthly-cost"}),
        ],
    )
    code, out, state = run(["--delete", FLAG], factory, tmp_path)
    assert code == 0 and "Deleted budget 'kitdemo-monthly-cost'" in out
    assert ACCOUNT not in out and not state.exists()
    factory.assert_all_calls_made()


def test_minor4_create_sets_the_tag_that_delete_looks_for():
    request = ba.build_create_request(ACCOUNT, "n", "25", [50.0], [EMAIL])
    assert request["ResourceTags"] == OUR_TAGS
    assert ba.created_by_this_script(request["ResourceTags"])
    assert not ba.created_by_this_script([{"Key": "project", "Value": "aws-kits"}])
    assert not ba.created_by_this_script(None)


def test_minor4_state_is_cleared_when_the_budget_is_already_gone(tmp_path):
    state = tmp_path / ".state.json"
    state.write_text(json.dumps({"budget": {"name": "kitdemo-monthly-cost"}}), encoding="utf-8")
    gone = Err("NotFoundException", "Unable to delete budget: kitdemo-monthly-cost; the budget doesn't exist.")
    factory = StubbedBudgets([identity()], [("delete_budget", gone, {"AccountId": ACCOUNT, "BudgetName": "kitdemo-monthly-cost"})])
    code, out, _ = run(["--delete", FLAG], factory, tmp_path)
    assert code == 0
    assert "no longer exists" in out and "cleared" in out
    assert not state.exists()


def test_minor4_unknown_name_that_does_not_exist_deletes_nothing_and_says_so(tmp_path):
    arn = f"arn:aws:budgets::{ACCOUNT}:budget/typo"
    factory = StubbedBudgets([identity()], [("list_tags_for_resource", Err("NotFoundException", "not found"), {"ResourceARN": arn})])
    code, out, _ = run(["--delete", "--name", "typo", FLAG], factory, tmp_path)
    assert code == 1
    assert "No budget named 'typo'" in out and "Nothing was deleted" in out
    factory.assert_all_calls_made()


def test_minor4_tags_that_cannot_be_read_mean_no_delete(tmp_path):
    factory = StubbedBudgets([identity()], [("list_tags_for_resource", Err("AccessDeniedException", "not authorized"), {"ResourceARN": ARN})])
    code, out, _ = run(["--delete", FLAG], factory, tmp_path)
    assert code == 1 and "FAILED, budget not deleted" in out
    factory.assert_all_calls_made()


def test_minor4_delete_dry_run_shows_the_tag_check_only_when_state_does_not_vouch_for_the_budget(tmp_path):
    code, out, _ = run(["--delete", "--dry-run"], forbidden_factory, tmp_path)
    assert code == 0 and "budgets.ListTagsForResource" in out and "budgets.DeleteBudget" in out
    (tmp_path / ".state.json").write_text(json.dumps({"budget": {"name": "kitdemo-monthly-cost"}}), encoding="utf-8")
    code, out, _ = run(["--delete", "--dry-run"], forbidden_factory, tmp_path)
    assert code == 0 and "budgets.ListTagsForResource" not in out and "budgets.DeleteBudget" in out


@pytest.mark.parametrize("address", ["someone@example.org", "a@family-surname.example.org", "x.y+z@sub.example.com"])
def test_minor7_mask_hides_the_domain_as_well(address):
    masked = ba.mask_email(address)
    local, domain = address.split("@")
    assert masked == f"{local[0]}***@***"
    assert domain not in masked and domain.split(".")[0] not in masked


def test_real_clients_without_credentials_fail_plainly_and_write_no_state(tmp_path):
    # The real client factory. conftest.py removes credentials and makes any socket use fail the test.
    lines: list[str] = []
    state = tmp_path / ".state.json"
    assert ba.main(["--show"], out=lines.append, state_path=state) == 1
    assert ba.main(["--email", EMAIL, FLAG], out=lines.append, state_path=state) == 1
    assert ba.main(["--delete", FLAG], out=lines.append, state_path=state) == 1
    text = "\n".join(lines)
    assert "no usable AWS credentials" in text and EMAIL not in text
    assert not state.exists()
