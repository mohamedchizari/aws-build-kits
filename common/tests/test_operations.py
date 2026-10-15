"""Every AWS operation the scripts can call must exist in the installed boto3.

This reads the service models that ship inside botocore. It makes no network
call and needs no credentials. It prints "n of m found" so the count can be
recorded.
"""
from __future__ import annotations

import re
from pathlib import Path

import boto3
import botocore.session

import budget_alarm as ba
import whats_running as wr

COMMON_DIR = Path(__file__).resolve().parents[1]
ALL_OPERATIONS = list(wr.READ_OPERATIONS) + list(ba.AWS_OPERATIONS)


def _model(service: str):
    return botocore.session.get_session().get_service_model(service)


def test_every_registered_operation_exists_in_the_installed_service_model(capsys):
    session = botocore.session.get_session()
    available = set(session.get_available_services())
    missing = []
    for service, operation, _doc in ALL_OPERATIONS:
        if service not in available or operation not in _model(service).operation_names:
            missing.append(f"{service}.{operation}")
    found = len(ALL_OPERATIONS) - len(missing)
    with capsys.disabled():
        print(f"\n[operations] boto3 {boto3.__version__}: {found} of {len(ALL_OPERATIONS)} registered operations found in the service models")
    assert not missing, f"not in boto3 {boto3.__version__}: {missing}"


def test_every_registered_operation_has_a_client_method():
    for service, operation, _doc in ALL_OPERATIONS:
        client = boto3.client(service, region_name="us-east-1", aws_access_key_id="testing", aws_secret_access_key="testing")
        methods = [py for py, api in client.meta.method_to_api_mapping.items() if api == operation]
        assert len(methods) == 1 and hasattr(client, methods[0]), f"{service}.{operation}"


def test_every_registered_operation_carries_an_aws_doc_url():
    for service, operation, doc in ALL_OPERATIONS:
        assert doc.startswith("https://docs.aws.amazon.com/"), f"{service}.{operation}"
        assert operation in doc, f"{service}.{operation}: doc URL does not name the operation"


_CALL_RE = re.compile(r"""_(?:call|paginate)\(\s*[A-Za-z_][\w.]*\s*,\s*["']([A-Za-z]+)["']""")


def _operations_used_in(path: Path) -> set[str]:
    return set(_CALL_RE.findall(path.read_text(encoding="utf-8")))


def test_source_calls_only_registered_operations_and_uses_all_of_them():
    for path, registry in ((COMMON_DIR / "whats_running.py", wr.READ_OPERATIONS), (COMMON_DIR / "budget_alarm.py", ba.AWS_OPERATIONS)):
        used = _operations_used_in(path)
        registered = {operation for _, operation, _ in registry}
        assert used, f"no calls found in {path.name}; the scan pattern is broken"
        assert used <= registered, f"{path.name} calls unregistered operations: {sorted(used - registered)}"
        assert registered <= used, f"{path.name} registers operations it never calls: {sorted(registered - used)}"


def test_no_script_reaches_aws_except_through_the_choke_point():
    """No direct client.method(...) call: the only getattr-driven call sits inside _call()."""
    direct = re.compile(r"\b(?:client|c|sts|budgets_client|sagemaker)\.(?:list|describe|get|batch|create|delete|update|put|start|stop|invoke)_\w+\(")
    for name in ("whats_running.py", "budget_alarm.py"):
        text = (COMMON_DIR / name).read_text(encoding="utf-8")
        assert not direct.search(text), f"{name} calls a client method directly"
        assert text.count("getattr(client, method") == 1, name


def test_every_call_site_has_a_doc_url_and_read_date_comment_above_it():
    for name in ("whats_running.py", "budget_alarm.py"):
        lines = (COMMON_DIR / name).read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines):
            match = _CALL_RE.search(line)
            if not match or line.lstrip().startswith(("def ", "#")):
                continue
            operation = match.group(1)
            window = "\n".join(lines[max(0, number - 8) : number])
            assert re.search(rf"# https://docs\.aws\.amazon\.com/\S*{operation}\S* \(read \d{{4}}-\d{{2}}-\d{{2}}\)", window), (
                f"{name}:{number + 1}: call to {operation} has no doc URL and read date in the comments above it"
            )


def test_pagination_token_names_match_the_service_model():
    """The token names passed to _paginate must be real members of the request and response."""
    text = (COMMON_DIR / "whats_running.py").read_text(encoding="utf-8")
    pattern = re.compile(r"""_paginate\(\s*c\s*,\s*"([A-Za-z]+)"\s*,\s*"([A-Za-z]+)"(?:\s*,\s*"([A-Za-z]+)"\s*,\s*"([A-Za-z]+)")?""")
    by_operation = {operation: service for service, operation, _ in wr.READ_OPERATIONS}
    seen = 0
    for operation, result_key, token_in, token_out in pattern.findall(text):
        seen += 1
        op_model = _model(by_operation[operation]).operation_model(operation)
        token_in, token_out = token_in or "nextToken", token_out or "nextToken"
        assert token_in in op_model.input_shape.members, f"{operation}: request has no {token_in}"
        assert token_out in op_model.output_shape.members, f"{operation}: response has no {token_out}"
        assert result_key in op_model.output_shape.members, f"{operation}: response has no {result_key}"
    assert seen >= 20


def test_no_personal_data_or_secrets_in_shipped_files():
    account_id = re.compile(r"(?<!\d)\d{12}(?!\d)")
    allowed_ids = {"111122223333", "444455556666"}  # AWS documentation placeholders, used in tests only
    access_key_id = re.compile(r"A[KS]IA[0-9A-Z]{16}")
    for path in sorted(COMMON_DIR.rglob("*")):
        if not path.is_file() or path.suffix not in {".py", ".md", ".txt"}:
            continue
        text = path.read_text(encoding="utf-8")
        assert chr(0x2014) not in text, f"{path.name}: em dash"
        assert not access_key_id.search(text), f"{path.name}: looks like an access key id"
        for found in account_id.findall(text):
            assert found in allowed_ids and path.parent.name == "tests", f"{path.name}: looks like an account id: {found}"
        for address in re.findall(r"[\w.+-]+@[\w-]+\.[\w.-]+", text):
            assert address.endswith(("example.com", "example.org")), f"{path.name}: non-placeholder email {address}"


def test_page_sizes_are_within_the_limits_in_the_service_model():
    """A page size above the model's maximum would be refused by AWS; check every one the audit sends."""
    text = (COMMON_DIR / "whats_running.py").read_text(encoding="utf-8")
    by_operation = {operation: service for service, operation, _ in wr.READ_OPERATIONS}
    seen = 0
    for operation, rest in re.findall(r"""_paginate\(\s*c\s*,\s*"([A-Za-z]+)"([^\n]*)""", text):
        size = re.search(r"\b(MaxResults|maxResults|limit|MaxBuckets)=(\d+)", rest)
        assert size, f"{operation}: no page size given"
        shape = _model(by_operation[operation]).operation_model(operation).input_shape.members[size.group(1)]
        low, high = shape.metadata.get("min", 1), shape.metadata.get("max")
        assert high is not None, f"{operation}: the model gives no maximum for {size.group(1)}"
        assert low <= int(size.group(2)) <= high, f"{operation}: {size.group(1)}={size.group(2)} is outside {low}..{high}"
        seen += 1
    assert seen >= 22


# IAM action each API operation needs, where it is not simply <prefix>:<OperationName>.
_IAM_PREFIX = {
    "sagemaker": "sagemaker", "bedrock-agent": "bedrock", "bedrock": "bedrock", "opensearchserverless": "aoss",
    "s3vectors": "s3vectors", "s3": "s3", "bedrock-agentcore-control": "bedrock-agentcore", "ecr": "ecr", "logs": "logs",
    "budgets": "budgets", "account": "account",
}
_IAM_SPECIAL = {
    ("s3", "ListBuckets"): {"s3:ListAllMyBuckets"},
    ("s3", "ListObjectVersions"): {"s3:ListBucketVersions"},
    ("budgets", "DescribeBudgets"): {"budgets:ViewBudget"},
    ("budgets", "DescribeNotificationsForBudget"): {"budgets:ViewBudget"},
    ("budgets", "CreateBudget"): {"budgets:ModifyBudget", "budgets:TagResource"},
    ("budgets", "DeleteBudget"): {"budgets:ModifyBudget"},
    ("sts", "GetCallerIdentity"): set(),  # "No permissions are required to perform this operation."
}


def _readme_policy_actions() -> list[set[str]]:
    import json

    readme = (COMMON_DIR / "README.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)\n```", readme, flags=re.S)
    return [{a for statement in json.loads(block)["Statement"] for a in statement["Action"]} for block in blocks]


def test_readme_iam_policies_cover_every_operation_and_grant_nothing_else():
    read_policy, write_policy = _readme_policy_actions()
    needed_read, needed_write = set(), set()
    for service, operation, _doc in ALL_OPERATIONS:
        actions = _IAM_SPECIAL.get((service, operation), {f"{_IAM_PREFIX.get(service, service)}:{operation}"})
        # budgets:ListTagsForResource is a Read action and the audit's budget row uses it, so it sits in the read policy.
        is_write = service == "budgets" and operation in {"CreateBudget", "DeleteBudget"}
        (needed_write if is_write else needed_read).update(actions)
    assert read_policy == needed_read, f"missing {sorted(needed_read - read_policy)}, extra {sorted(read_policy - needed_read)}"
    assert write_policy == needed_write, f"missing {sorted(needed_write - write_policy)}, extra {sorted(write_policy - needed_write)}"
    assert not any(a.split(":")[1].startswith(("Create", "Delete", "Update", "Put", "Invoke", "Start", "Stop")) for a in read_policy)
    readme = (COMMON_DIR / "README.md").read_text(encoding="utf-8")
    assert f"All {len(read_policy | write_policy)} action names" in readme


def test_readme_states_the_operation_count_that_the_registries_hold():
    readme = (COMMON_DIR / "README.md").read_text(encoding="utf-8")
    total, audit, budget = len(ALL_OPERATIONS), len(wr.READ_OPERATIONS), len(ba.AWS_OPERATIONS)
    assert f"{total} of {total} AWS operations" in readme
    assert f"({audit} in `whats_running.py`, {budget} in `budget_alarm.py`" in readme
    distinct = len({(service, operation) for service, operation, _doc in ALL_OPERATIONS})
    assert f"{distinct} different operations" in readme  # some are used by both scripts
    assert f"all {len(wr.CHECKS)} checks and the identity check" in readme


def test_readme_exit_code_table_matches_the_scripts():
    readme = (COMMON_DIR / "README.md").read_text(encoding="utf-8")
    assert (wr.EXIT_CLEAN, wr.EXIT_NOT_CLEAN, wr.EXIT_DRY_RUN, wr.EXIT_USAGE) == (0, 2, 3, 64)
    assert (ba.EXIT_OK, ba.EXIT_ERROR, ba.EXIT_REFUSED, ba.EXIT_USAGE) == (0, 1, 3, 64)
    rows = {line.split("|")[1].strip(): line for line in readme.splitlines() if re.match(r"^\| \d+ \|", line)}
    assert set(rows) == {"0", "1", "2", "3", "4", "5", "64", "130"}
    assert "NOT CLEAN" in rows["2"].split("|")[2] and "nothing was checked" in rows["3"].split("|")[2]
    assert "refused" in rows["3"].split("|")[3] and "bad command line" in rows["64"].split("|")[3]
