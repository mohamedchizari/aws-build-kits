#!/usr/bin/env python3
"""budget_alarm.py: one monthly AWS Budgets cost budget with email alerts.

READ THIS FIRST: a budget is an alarm, not a brake.
  * It only sends email. It does not stop, pause or delete anything.
  * It is late. "AWS billing data, which Budgets uses to monitor resources, is
    updated at least once per day." A GPU endpoint left on can run for many
    hours before the first email.
    https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-best-practices.html (read 2026-10-07)
  * Even budget ACTIONS (which this script does not create) cannot stop a
    SageMaker endpoint: the action types are an IAM policy, a service control
    policy, or stopping specific EC2 or RDS instances.
    https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-controls.html (read 2026-10-07)
The control that works is deleting the resource in the same sitting and
running whats_running.py until it exits 0.

Modes
    (default)  create the budget. Needs an address (--email, or the
               BUDGET_ALARM_EMAIL environment variable) and
               --i-understand-this-changes-my-account.
    --show     read-only: list the budgets that exist, mark the one this script
               created, and point to the audit (whats_running.py), which lists
               the same budgets as an informational row.
    --delete   delete the budget this script created, and only that one: the
               name must be the one in .state.json AND you must be signed in
               to the account that record was written for (its last four
               digits are kept with the name), or the budget must carry the
               tag this script sets. Needs the same flag.
    --dry-run  with any mode: print the API calls and make none.

Exit codes: 0 done, 1 AWS call failed or got no clear answer, 3 refused (flag
missing, or --delete was pointed at a budget this script did not create),
64 bad command line.

Every mode that calls AWS says which account it acted in (last four digits).
If CreateBudget is sent and no clear answer comes back, the script does not
say the budget was not created: it says OUTCOME UNKNOWN and how to check.

The email address is taken from the command line or from the environment
variable BUDGET_ALARM_EMAIL, sent to AWS in the CreateBudget call, and
written nowhere else: not to .state.json, not to a log, and only in masked
form on the screen. Every line this script prints, AWS error text included,
passes through one filter that masks the supplied addresses and cuts any
12-digit number (an account id) to its last four digits.

NOT RUN: written without an AWS account. No call here has been made against
AWS. Shapes were checked against the Budgets service model in boto3 1.43.108
and exercised offline with botocore's Stubber (see tests/).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

try:
    import boto3
    import botocore.exceptions as bex
    from botocore.config import Config
except ImportError:  # pragma: no cover - exercised only on a machine without boto3
    boto3 = None
    bex = None
    Config = None

DOCS_READ = "2026-10-07"
DEFAULT_REGION = "us-east-1"
DEFAULT_PREFIX = "kitdemo"
DEFAULT_LIMIT_USD = "25"
DEFAULT_THRESHOLDS = "50,80,100"
CONFIRM_FLAG = "--i-understand-this-changes-my-account"
EMAIL_ENV_VAR = "BUDGET_ALARM_EMAIL"
# Every budget this script creates carries these two tags. --delete looks for the second one
# when .state.json does not vouch for the budget.
PROJECT_TAG = {"Key": "project", "Value": "aws-kits"}
CREATED_BY_TAG = {"Key": "created-by", "Value": "aws-kits-budget-alarm"}
STATE_FILE = Path(__file__).resolve().with_name(".state.json")

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_REFUSED = 3
EXIT_USAGE = 64

# "A budget can have up to five notifications, and each notification can have one SNS
# subscriber and up to 10 email subscribers."
# https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_CreateBudget.html (read 2026-10-07)
MAX_NOTIFICATIONS = 5
MAX_EMAILS = 10

SRC_PRICING = "https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/"
PRICE_NOTE = (
    "Cost of this budget: none expected. 'You can monitor and receive notifications on your budgets "
    f"free of charge.' Source: {SRC_PRICING} (read {DOCS_READ}). This script creates no budget actions."
)

# The only operations this script may call. tests/test_operations.py checks every
# entry against the installed boto3 service model.
AWS_OPERATIONS: tuple[tuple[str, str, str], ...] = (
    ("sts", "GetCallerIdentity", "https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html"),
    ("budgets", "CreateBudget", "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_CreateBudget.html"),
    ("budgets", "DescribeBudgets", "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_DescribeBudgets.html"),
    ("budgets", "DescribeNotificationsForBudget", "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_DescribeNotificationsForBudget.html"),
    ("budgets", "ListTagsForResource", "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_ListTagsForResource.html"),
    ("budgets", "DeleteBudget", "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_DeleteBudget.html"),
)
_ALLOWED = {(svc, op) for svc, op, _ in AWS_OPERATIONS}

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UsageError(Exception):
    pass


class AwsCallFailed(Exception):
    def __init__(self, message: str, code: str = "", outcome_unknown: bool = False):
        super().__init__(message)
        self.code = code  # the AWS error code, when AWS returned one
        # True when the request went out and what came back does not say whether AWS carried it out:
        # no answer at all (a timeout, a dropped connection), a 5xx answer, a 4xx answer that came back after
        # the SDK had sent the request again, or a sign-in error raised while a retry was being signed.
        self.outcome_unknown = outcome_unknown


# Errors botocore raises only before the first try leaves this machine: no credentials at all, an unknown
# profile or no Region (both while the client is built), and a request it refused to build. After one of these
# nothing was sent. The other sign-in errors are not here: botocore 1.43.108 signs every retry again
# (endpoint.py: "Create a new request when retried (including a new signature)"), and a refresh that fails
# then reaches the caller after an earlier try may have been carried out. Round 5, finding F1 (kit A's rule).
_NOT_SENT_ERRORS = ("NoCredentialsError", "ProfileNotFound", "NoRegionError", "ParamValidationError")


def outcome_unknown(exc: BaseException) -> bool:
    """True unless AWS refused the one request that was sent, or nothing was sent (kit A's definitely_rejected)."""
    response = getattr(exc, "response", None)
    if isinstance(response, dict) and error_code(exc):
        metadata = response.get("ResponseMetadata") or {}
        status, again = metadata.get("HTTPStatusCode"), metadata.get("RetryAttempts")
        if isinstance(status, int) and 400 <= status < 500:
            # A 4xx to a request the SDK had sent more than once: an earlier try whose answer was lost may have
            # been carried out (round 5, F2). Missing or 0 means it was sent once.
            return isinstance(again, int) and again > 0
        return isinstance(status, int) and status >= 500
    return type(exc).__name__ not in _NOT_SENT_ERRORS


_ACCOUNT_ID_RE = re.compile(r"(?<!\d)\d{12}(?!\d)")


def make_redactor(addresses: list[str]) -> Callable[[Any], str]:
    """A filter for everything this script prints.

    AWS error text is not under this script's control: an AccessDenied message
    names the caller's ARN, account id included, and a validation message may
    repeat a subscriber address. So no text is printed raw.
    """
    patterns = [
        (re.compile(re.escape(a), re.IGNORECASE), mask_email(a))
        for a in sorted({a.strip() for a in addresses if a and a.strip()}, key=len, reverse=True)
    ]

    def redact(text: Any) -> str:
        cleaned = str(text)
        for pattern, replacement in patterns:
            cleaned = pattern.sub(replacement, cleaned)
        return _ACCOUNT_ID_RE.sub(lambda m: f"[account ending {m.group(0)[-4:]}]", cleaned)

    return redact


def error_code(exc: BaseException) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        return str((response.get("Error") or {}).get("Code", ""))
    return ""


def describe_error(exc: BaseException) -> str:
    if bex is not None:
        if isinstance(exc, bex.ClientError):
            err = exc.response.get("Error", {}) if isinstance(exc.response, dict) else {}
            code = err.get("Code", "ClientError")
            msg = " ".join(str(err.get("Message", "")).split())[:240]
            return f"{code}: {msg}" if msg else str(code)
        if isinstance(exc, (bex.NoCredentialsError, bex.PartialCredentialsError)):
            return "no usable AWS credentials were found"
        if isinstance(exc, bex.EndpointConnectionError):
            return "the AWS endpoint could not be reached (no network?)"
    text = " ".join(str(exc).split())[:240]
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def _call(client: Any, operation: str, **params: Any) -> dict[str, Any]:
    """The single choke point for AWS calls in this script."""
    model = client.meta.service_model
    service = model.service_name
    if (service, operation) not in _ALLOWED:
        raise AwsCallFailed(f"refused: {service}.{operation} is not in this script's list of operations")
    if operation not in set(model.operation_names):
        raise AwsCallFailed(
            f"operation {operation} is not in the installed boto3 ({getattr(boto3, '__version__', '?')}) model for {service}"
        )
    method = next((py for py, api in client.meta.method_to_api_mapping.items() if api == operation), None)
    if method is None:
        raise AwsCallFailed(f"installed boto3 has no client method for {service}.{operation}")
    try:
        return getattr(client, method)(**params)
    except Exception as exc:  # noqa: BLE001
        raise AwsCallFailed(f"{service}.{operation}: {describe_error(exc)}", error_code(exc), outcome_unknown(exc)) from exc


def default_client_factory(service: str, region: str) -> Any:
    if boto3 is None:
        raise AwsCallFailed("boto3 is not installed (pip install -r requirements.txt)")
    # Building a client makes no network call. The Budgets API has one global
    # endpoint (budgets.amazonaws.com) whatever Region is given here.
    return boto3.client(
        service,
        region_name=region,
        config=Config(retries={"max_attempts": 3, "mode": "standard"}, connect_timeout=10, read_timeout=30),
    )


def make_client(client_factory: Callable[[str, str], Any], service: str, region: str) -> Any:
    try:
        return client_factory(service, region)
    except AwsCallFailed:
        raise
    except Exception as exc:  # noqa: BLE001
        raise AwsCallFailed(f"could not build the {service} client: {describe_error(exc)}") from exc


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------
def mask_email(address: str) -> str:
    """First character of the local part and nothing of the domain: a personal domain names its owner."""
    local = address.partition("@")[0]
    return f"{local[:1]}***@***"


def supplied_emails(cli_values: list[str] | None, env: dict[str, str] | None = None) -> list[str]:
    """Raw addresses from --email and from BUDGET_ALARM_EMAIL (comma-separated), not yet validated."""
    env = os.environ if env is None else env
    from_env = [part for part in str(env.get(EMAIL_ENV_VAR, "")).split(",")]
    return [v for v in list(cli_values or []) + from_env if v and v.strip()]


def parse_emails(values: list[str] | None) -> list[str]:
    emails = list(dict.fromkeys(v.strip() for v in (values or []) if v and v.strip()))
    if not emails:
        raise UsageError(
            f"an address is required to create a budget: --email, or the environment variable {EMAIL_ENV_VAR} "
            "(it is sent to AWS and stored nowhere else)"
        )
    if len(emails) > MAX_EMAILS:
        raise UsageError(f"at most {MAX_EMAILS} email addresses per alert")
    for e in emails:
        if not _EMAIL_RE.match(e):
            raise UsageError(f"one address (--email or {EMAIL_ENV_VAR}) does not look like an email address")
    return emails


def parse_thresholds(text: str, forecast: float | None) -> list[float]:
    try:
        values = sorted({float(part) for part in text.split(",") if part.strip()})
    except ValueError as exc:
        raise UsageError("--thresholds must be comma-separated numbers, for example 50,80,100") from exc
    if not values:
        raise UsageError("--thresholds needs at least one percentage")
    # "not (0 < v <= 1000)" also refuses NaN, which every comparison lets through, and both infinities.
    if any(not math.isfinite(v) or not 0 < v <= 1000 for v in values):
        raise UsageError("each threshold must be a finite percentage above 0 and at most 1000")
    if forecast is not None and (not math.isfinite(forecast) or not 0 < forecast <= 1000):
        raise UsageError("--forecast-threshold must be a finite percentage above 0 and at most 1000")
    total = len(values) + (1 if forecast is not None else 0)
    if total > MAX_NOTIFICATIONS:
        raise UsageError(f"a budget can have at most {MAX_NOTIFICATIONS} notifications; you asked for {total}")
    return values


def parse_limit(text: str) -> str:
    try:
        value = float(text)
    except ValueError as exc:
        raise UsageError("--limit must be a number of US dollars, for example 25") from exc
    if not math.isfinite(value) or value <= 0:
        raise UsageError("--limit must be above 0 (a finite number of US dollars)")
    amount = f"{value:.2f}"
    if float(amount) <= 0:  # 0.004 would otherwise be sent to AWS as a limit of "0"
        raise UsageError("--limit must be above 0 after rounding to cents: the smallest limit is 0.01")
    return amount.rstrip("0").rstrip(".")


def check_name(name: str) -> str:
    # "The : and \ characters, and the "/action/" substring, aren't allowed in BudgetName." Length 1 to 100.
    # https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_Budget.html (read 2026-10-07)
    if not name or len(name) > 100 or ":" in name or "\\" in name or "/action/" in name:
        raise UsageError("budget name must be 1 to 100 characters with no ':' or '\\' and no '/action/'")
    return name


def build_create_request(
    account_id: str,
    name: str,
    limit_usd: str,
    thresholds: list[float],
    emails: list[str],
    forecast: float | None = None,
    aws_default_cost_types: bool = False,
) -> dict[str, Any]:
    """The exact CreateBudget request. Kept pure so tests can inspect it."""
    subscribers = [{"SubscriptionType": "EMAIL", "Address": e} for e in emails]
    notifications = [
        {
            "Notification": {
                "NotificationType": "ACTUAL",
                "ComparisonOperator": "GREATER_THAN",
                "Threshold": t,
                "ThresholdType": "PERCENTAGE",
            },
            "Subscribers": subscribers,
        }
        for t in thresholds
    ]
    if forecast is not None:
        # "AWS requires approximately 5 weeks of usage data to generate budget forecasts."
        # https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-best-practices.html (read 2026-10-07)
        notifications.append(
            {
                "Notification": {
                    "NotificationType": "FORECASTED",
                    "ComparisonOperator": "GREATER_THAN",
                    "Threshold": forecast,
                    "ThresholdType": "PERCENTAGE",
                },
                "Subscribers": subscribers,
            }
        )
    budget: dict[str, Any] = {
        "BudgetName": name,
        "BudgetLimit": {"Amount": limit_usd, "Unit": "USD"},
        "TimeUnit": "MONTHLY",
        "BudgetType": "COST",
    }
    if not aws_default_cost_types:
        # By default AWS counts credits and refunds INTO a cost budget (IncludeCredit and
        # IncludeRefund default to true), so credits would hide real usage and delay the
        # alarm. This turns those two off and states every other member at its documented
        # default.
        # https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_CostTypes.html (read 2026-10-07)
        # UNVERIFIED: CostTypes is marked deprecated (in the boto3 1.43.108 model: since
        # 2025-04-18, "Please consider using the new 'Metrics' field"), while CreateBudget
        # still documents it: "Either FilterExpression and Metrics or CostFilters and
        # CostTypes, not both". Whether the live API still accepts it was not tested, and
        # the FilterExpression values that would exclude credits were not found in a doc.
        # If CreateBudget rejects CostTypes, rerun with --aws-default-cost-types.
        budget["CostTypes"] = {
            "IncludeTax": True,
            "IncludeSubscription": True,
            "UseBlended": False,
            "IncludeRefund": False,
            "IncludeCredit": False,
            "IncludeUpfront": True,
            "IncludeRecurring": True,
            "IncludeOtherSubscription": True,
            "IncludeSupport": True,
            "IncludeDiscount": True,
            "UseAmortized": False,
        }
    return {
        "AccountId": account_id,
        "Budget": budget,
        "NotificationsWithSubscribers": notifications,
        "ResourceTags": [dict(PROJECT_TAG), dict(CREATED_BY_TAG)],
    }


def created_by_this_script(tags: Any) -> bool:
    """True when a budget's tags carry the mark build_create_request() sets."""
    return isinstance(tags, list) and any(
        isinstance(t, dict) and t.get("Key") == CREATED_BY_TAG["Key"] and t.get("Value") == CREATED_BY_TAG["Value"] for t in tags
    )


def masked_request(request: dict[str, Any]) -> dict[str, Any]:
    """A copy of the request that is safe to print: emails masked, account id hidden."""
    safe = json.loads(json.dumps(request))
    safe["AccountId"] = "<your account id, from sts:GetCallerIdentity>"
    for n in safe.get("NotificationsWithSubscribers", []):
        for s in n.get("Subscribers", []):
            s["Address"] = mask_email(s["Address"])
    return safe


# ---------------------------------------------------------------------------
# State file: the budget name and the last four digits of the account it was
# created in. Never the email, never the full account id.
# The budget ARN is deliberately not stored because it contains the account id;
# it is arn:aws:budgets::<account id>:budget/<name> if you need it.
# ---------------------------------------------------------------------------
def load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def budget_record(state: dict[str, Any]) -> dict[str, Any]:
    """The record of the budget this script created, or {} when there is none or it is not an object."""
    record = state.get("budget")
    return record if isinstance(record, dict) else {}


def tail(acct: str) -> str:
    return str(acct)[-4:]


def save_state(path: Path, state: dict[str, Any]) -> None:
    if state:
        path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif path.exists():
        path.unlink()


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------
def caller(client_factory: Callable[[str, str], Any], region: str) -> tuple[str, str]:
    """(account id, partition) of the credentials in use. Neither is printed or stored."""
    sts = make_client(client_factory, "sts", region)
    # https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html (read 2026-10-07)
    # "No permissions are required to perform this operation."
    ident = _call(sts, "GetCallerIdentity")
    acct = str(ident.get("Account", ""))
    if not re.fullmatch(r"\d{12}", acct):
        raise AwsCallFailed("sts.GetCallerIdentity did not return a 12-digit account id")
    parts = str(ident.get("Arn", "")).split(":")
    partition = parts[1] if len(parts) > 1 and parts[0] == "arn" and parts[1].startswith("aws") else "aws"
    return acct, partition


def account_id(client_factory: Callable[[str, str], Any], region: str) -> str:
    return caller(client_factory, region)[0]


def budget_arn(partition: str, acct: str, name: str) -> str:
    # The form shown in the ListTagsForResource example on that page: arn:aws:budgets::<account id>:budget/<budget name>.
    # https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_ListTagsForResource.html (read 2026-10-07)
    return f"arn:{partition}:budgets::{acct}:budget/{name}"


def do_show(
    args: argparse.Namespace,
    client_factory: Callable[[str, str], Any],
    out: Callable[[str], None],
    state_path: Path | None = None,
) -> int:
    if args.dry_run:
        out("DRY RUN: no AWS call was made. Read-only calls that --show would make:")
        out("  sts.GetCallerIdentity()")
        out("  budgets.DescribeBudgets(AccountId=<your account id>, MaxResults=100)  [repeated while NextToken is returned]")
        out("  budgets.DescribeNotificationsForBudget(AccountId=<your account id>, BudgetName=<each>, MaxResults=100)")
        return EXIT_OK
    try:
        acct = account_id(client_factory, args.region)
        budgets_client = make_client(client_factory, "budgets", args.region)
        budgets: list[dict[str, Any]] = []
        token: str | None = None
        seen: set[str] = set()
        while True:
            params: dict[str, Any] = {"AccountId": acct, "MaxResults": 100}
            if token:
                params["NextToken"] = token
            # https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_DescribeBudgets.html (read 2026-10-07)
            page = _call(budgets_client, "DescribeBudgets", **params)
            budgets.extend(page.get("Budgets") or [])
            token = page.get("NextToken")
            if not token:
                break
            if token in seen:
                raise AwsCallFailed("budgets.DescribeBudgets: pagination token repeated; listing is incomplete")
            seen.add(token)
        lines: list[str] = []
        record = budget_record(load_state(state_path)) if state_path is not None else {}
        recorded = record.get("name")
        # A record written for another account says nothing about a budget of the same name in this one.
        if record.get("account_tail") not in (None, tail(acct)):
            recorded = None
        for b in budgets:
            name = b.get("BudgetName", "?")
            limit = b.get("BudgetLimit") or {}
            spend = b.get("CalculatedSpend") or {}
            actual = spend.get("ActualSpend") or {}
            forecast = spend.get("ForecastedSpend") or {}
            # https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_DescribeNotificationsForBudget.html (read 2026-10-07)
            notes = _call(budgets_client, "DescribeNotificationsForBudget", AccountId=acct, BudgetName=name, MaxResults=100).get("Notifications") or []
            alerts = ", ".join(
                f"{n.get('NotificationType', '?')} {n.get('ComparisonOperator', '?')} {n.get('Threshold', '?')} {n.get('ThresholdType', 'PERCENTAGE')}"
                for n in notes
            ) or "NO ALERTS SET"
            lines.append(
                f"  {name}: {b.get('BudgetType', '?')} {b.get('TimeUnit', '?')}, limit {limit.get('Amount', '?')} {limit.get('Unit', '')}, "
                f"actual {actual.get('Amount', 'not returned')} {actual.get('Unit', '')}, "
                f"forecast {forecast.get('Amount', 'not returned')} {forecast.get('Unit', '')}"
            )
            lines.append(f"      alerts: {alerts}")
            lines.append(f"      last updated by AWS: {b.get('LastUpdatedTime', 'not returned')}")
            if recorded and name == recorded:
                lines.append(f"      this is the budget budget_alarm.py created (recorded in {state_path.name}); --delete without --name removes this one")
    except AwsCallFailed as exc:
        out(f"COULD NOT LIST BUDGETS: {exc}")
        out("This is a failure to check, not a statement that no budget exists.")
        return EXIT_ERROR
    if not budgets:
        out(f"No budgets exist in this account (the one ending {tail(acct)}). Nothing will email you about spend.")
    else:
        out(f"{len(budgets)} budget(s) in this account, the one ending {tail(acct)} (subscriber addresses are not shown):")
        for line in lines:
            out(line)
    out("Reminder: spend figures here are refreshed by AWS 'at least once per day'. They are not live.")
    out("The audit lists budgets too, under INFORMATIONAL: python whats_running.py. A budget is free and is not a leftover, "
        "so that row never changes its result or its exit code.")
    return EXIT_OK


def do_create(args: argparse.Namespace, client_factory: Callable[[str, str], Any], out: Callable[[str], None], state_path: Path) -> int:
    emails = parse_emails(supplied_emails(args.email))
    thresholds = parse_thresholds(args.thresholds, args.forecast_threshold)
    limit = parse_limit(args.limit)
    name = check_name(args.name)

    preview = build_create_request("0" * 12, name, limit, thresholds, emails, args.forecast_threshold, args.aws_default_cost_types)
    out(f"Budget '{name}': monthly COST budget, limit {limit} USD, email alerts at {', '.join(f'{t:g}%' for t in thresholds)} of actual spend"
        + (f" and {args.forecast_threshold:g}% forecast" if args.forecast_threshold is not None else "")
        + f", to {len(emails)} address(es).")
    out(PRICE_NOTE)
    out("What it does NOT do: it does not stop, pause or delete anything, and its data is up to a day old.")

    if args.dry_run:
        out("DRY RUN: no AWS call was made. Calls that would be made:")
        out("  sts.GetCallerIdentity()")
        out("  budgets.CreateBudget(" + json.dumps(masked_request(preview), indent=2) + ")")
        return EXIT_OK
    if not args.confirmed:
        out(f"REFUSED: creating a budget changes your AWS account. Rerun with {CONFIRM_FLAG} to create it,")
        out("or with --dry-run to see the exact request. Nothing was created and no AWS call was made.")
        return EXIT_REFUSED

    acct = ""
    try:
        acct = account_id(client_factory, args.region)
        budgets_client = make_client(client_factory, "budgets", args.region)
        request = build_create_request(acct, name, limit, thresholds, emails, args.forecast_threshold, args.aws_default_cost_types)
        # https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_CreateBudget.html (read 2026-10-07)
        _call(budgets_client, "CreateBudget", **request)
    except AwsCallFailed as exc:
        where = f" in the account ending {tail(acct)}" if acct else ""
        if exc.outcome_unknown and acct and "budgets.CreateBudget" in str(exc):
            # The request went out and nothing says what AWS did with it. Saying "not created" here would be a
            # guess, and a wrong one whenever only the answer was lost.
            out(f"OUTCOME UNKNOWN: CreateBudget was sent and no clear answer came back ({exc}). The budget '{name}' MAY "
                f"exist{where}. No record was written to {state_path.name}.")
            if exc.code == "DuplicateRecordException":
                out(f"AWS answered the SDK's retry with 'already exists': a budget named '{name}' exists{where}, "
                    "made by an earlier try of this run or there before it.")
            out("Check now: python budget_alarm.py --show   If it is listed, it is the one you asked for, and --delete "
                "finds it by its tag. If it is not listed, run this command again.")
            return EXIT_ERROR
        out(f"FAILED, budget not created{where}: {exc}")
        if "DuplicateRecordException" in str(exc):
            out(f"A budget named '{name}' already exists{where}. See it with --show, or remove it with --delete {CONFIRM_FLAG}.")
        if "CostTypes" in str(exc) or "InvalidParameterException" in str(exc):
            out("If the message is about CostTypes, rerun with --aws-default-cost-types (see README).")
        return EXIT_ERROR

    state = load_state(state_path)
    state["budget"] = {
        "name": name,
        "account_tail": tail(acct),
        "created_by": CREATED_BY_TAG["Value"],
        "limit_usd": limit,
        "thresholds_percent": thresholds,
        "created_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    save_state(state_path, state)
    out(f"Created budget '{name}' in the account ending {tail(acct)}. If that is not the account the kits run in, you are "
        "signed in with the wrong profile: delete it here and create it there.")
    out(f"Its name and those four digits (not the email address, not the full account id) were written to {state_path.name}.")
    out("Check it with: python budget_alarm.py --show")
    return EXIT_OK


def do_delete(args: argparse.Namespace, client_factory: Callable[[str, str], Any], out: Callable[[str], None], state_path: Path) -> int:
    """Delete a budget, but only one this script created.

    Proof is either the record in .state.json (written when the budget was created),
    which counts only in the account it was written for, or the created-by tag on the
    budget itself. A record that is not an object counts as no record.
    """
    state = load_state(state_path)
    record = budget_record(state)
    recorded = record.get("name")
    recorded_tail = record.get("account_tail")  # absent in a record written before round 4: then the name alone counts
    name = check_name(args.name_given or recorded or args.name)
    in_state = bool(recorded) and recorded == name
    out(f"Delete budget '{name}'. 'Deleting a budget also deletes the notifications and subscribers that are associated with that budget.'")
    if args.dry_run:
        out("DRY RUN: no AWS call was made. Calls that would be made:")
        out("  sts.GetCallerIdentity()")
        if in_state:
            out(f"  ({state_path.name} records that this script created '{name}'"
                + (f" in the account ending {recorded_tail}; signed in to that account, its tags are not read. In any "
                   "other account the record does not count and the tag decides)" if recorded_tail
                   else ", so its tags are not read)"))
        else:
            out(f"  budgets.ListTagsForResource(ResourceARN='arn:aws:budgets::<your account id>:budget/{name}')"
                f"  [{state_path.name} has no record of '{name}'; it is deleted only if it carries the tag "
                f"{CREATED_BY_TAG['Key']}={CREATED_BY_TAG['Value']}]")
        out(f"  budgets.DeleteBudget(AccountId=<your account id>, BudgetName='{name}')")
        return EXIT_OK
    if not args.confirmed:
        out(f"REFUSED: deleting a budget changes your AWS account. Rerun with {CONFIRM_FLAG}. No AWS call was made.")
        return EXIT_REFUSED
    acct = ""
    try:
        acct, partition = caller(client_factory, args.region)
        budgets_client = make_client(client_factory, "budgets", args.region)
        if in_state and recorded_tail not in (None, tail(acct)):
            # The record vouches for a budget in ANOTHER account. A budget of the same name here may be
            # somebody else's, so it has to prove itself by its tag, and the record is left alone.
            in_state = False
            out(f"NOTE: {state_path.name} records '{name}' for the account ending {recorded_tail}. You are signed in to "
                f"the account ending {tail(acct)}, so that record does not count here and is not changed. A budget of "
                "that name in this account is deleted only if it carries this script's tag.")
        if not in_state:
            try:
                # https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_ListTagsForResource.html (read 2026-10-07)
                tags = _call(budgets_client, "ListTagsForResource", ResourceARN=budget_arn(partition, acct, name)).get("ResourceTags")
            except AwsCallFailed as exc:
                if exc.code == "NotFoundException":
                    out(f"No budget named '{name}' exists in this account (the one ending {tail(acct)}). Nothing was deleted.")
                    return EXIT_ERROR
                raise
            if not created_by_this_script(tags):
                out(f"REFUSED: budget '{name}' in the account ending {tail(acct)} was not created by this script: "
                    f"{state_path.name} has no record of it for this account and it "
                    f"does not carry the tag {CREATED_BY_TAG['Key']}={CREATED_BY_TAG['Value']}. Nothing was deleted.")
                out("If you do mean to delete it, do it in the Billing and Cost Management console, under Budgets.")
                return EXIT_REFUSED
        try:
            # https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_DeleteBudget.html (read 2026-10-07)
            _call(budgets_client, "DeleteBudget", AccountId=acct, BudgetName=name)
        except AwsCallFailed as exc:
            if exc.code == "NotFoundException" and in_state:
                state.pop("budget", None)
                save_state(state_path, state)
                if exc.outcome_unknown:  # round 5, F2: "not found" to the SDK's retry of this run's delete
                    out(f"Budget '{name}' no longer exists in the account ending {tail(acct)} (an earlier try of this run may "
                        "have deleted it: its answer was lost and the SDK's retry was answered 'not found'). The "
                        f"record of it in {state_path.name} was cleared.")
                    return EXIT_OK
                out(f"Budget '{name}' no longer exists in the account ending {tail(acct)} (it was deleted somewhere else). "
                    f"Nothing was deleted now; the record of it in {state_path.name} was cleared.")
                return EXIT_OK
            raise
    except AwsCallFailed as exc:
        where = f" in the account ending {tail(acct)}" if acct else ""
        if exc.outcome_unknown and acct and "budgets.DeleteBudget" in str(exc):
            # Round 5, F2: the delete went out and nothing says what AWS did with it.
            out(f"OUTCOME UNKNOWN: DeleteBudget was sent and no clear answer came back ({exc}). The budget '{name}' MAY "
                f"have been deleted{where}. {state_path.name} was not changed.")
            out("Check now: python budget_alarm.py --show   If it is still listed, run this command again.")
            return EXIT_ERROR
        out(f"FAILED, budget not deleted{where}: {exc}")
        return EXIT_ERROR
    if in_state:
        state.pop("budget", None)
        save_state(state_path, state)
    out(f"Deleted budget '{name}' in the account ending {tail(acct)}. You now have one alarm fewer; check with --show.")
    return EXIT_OK


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    prefix = os.environ.get("KIT_PREFIX") or DEFAULT_PREFIX
    p = _Parser(
        prog="budget_alarm.py",
        description="Create one monthly cost budget with email alerts. A budget is an alarm, not a brake: it stops nothing.",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--show", action="store_true", help="read-only: list existing budgets and their alerts")
    mode.add_argument("--delete", action="store_true", help=f"delete the budget this script created, and no other (needs {CONFIRM_FLAG})")
    p.add_argument("--email", action="append", help=f"address to alert (repeatable, at most 10). Required to create, here or in the environment variable {EMAIL_ENV_VAR} (comma-separated). Sent to AWS, stored nowhere else. On the command line it lands in your shell history; see the README.")
    p.add_argument("--limit", default=DEFAULT_LIMIT_USD, help=f"monthly limit in US dollars (default {DEFAULT_LIMIT_USD})")
    p.add_argument("--thresholds", default=DEFAULT_THRESHOLDS, help=f"percentages of the limit, on actual spend, that send an email (default {DEFAULT_THRESHOLDS})")
    p.add_argument("--forecast-threshold", type=float, default=None, help="also alert when FORECAST spend passes this percentage (AWS needs about 5 weeks of usage data first)")
    p.add_argument("--name", default=None, help=f"budget name (default {prefix}-monthly-cost, from KIT_PREFIX)")
    p.add_argument("--aws-default-cost-types", action="store_true", help="do not send CostTypes; AWS then counts credits and refunds into the budget (see README)")
    p.add_argument("--region", default=os.environ.get("AWS_REGION") or DEFAULT_REGION, help="Region for the client (default AWS_REGION, else us-east-1). Budgets itself is a global service.")
    p.add_argument(CONFIRM_FLAG, dest="confirmed", action="store_true", help="required to create or delete")
    p.add_argument("--dry-run", action="store_true", help="print the API calls that would be made and make none")
    return p


def main(
    argv: list[str] | None = None,
    client_factory: Callable[[str, str], Any] | None = None,
    out: Callable[[str], None] = print,
    state_path: Path | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    args.name_given = args.name
    if args.name is None:
        args.name = f"{os.environ.get('KIT_PREFIX') or DEFAULT_PREFIX}-monthly-cost"
    factory = client_factory or default_client_factory
    path = state_path or STATE_FILE
    # Nothing is printed raw: every line goes through the filter that masks the supplied
    # addresses and cuts account ids to four digits.
    redact = make_redactor(supplied_emails(args.email))

    def safe_out(line: Any) -> None:
        out(redact(line))

    try:
        if args.show:
            return do_show(args, factory, safe_out, path)
        if args.delete:
            return do_delete(args, factory, safe_out, path)
        return do_create(args, factory, safe_out, path)
    except UsageError as exc:
        print(redact(f"budget_alarm.py: error: {exc}"), file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
