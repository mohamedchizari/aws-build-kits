"""--after-teardown KIT: one screen of what a kit can create and what the audit saw of it. Offline."""
from __future__ import annotations

import json
import re

import pytest

import whats_running as wr
from helpers import TEST_ACCOUNT, FakeAccount, client_error, forbidden_factory, log_groups_like_aws

STATUSES = {wr.COVERAGE_NONE, wr.COVERAGE_FOUND, wr.COVERAGE_COULD_NOT, wr.COVERAGE_NOT_CHECKABLE}


def run(argv, account, capsys):
    code = wr.main(list(argv), client_factory=account)
    return code, capsys.readouterr().out


def rows_of(out):
    """{resource label: status} from the text screen."""
    rows = {}
    for line in out.splitlines():
        match = re.match(r"^  \[([^\]]+)\]\s+(.*)$", line)
        if match:
            rows[match.group(2)] = match.group(1).lower()
    return rows


@pytest.mark.parametrize("kit", ["a", "b", "c"])
def test_every_resource_type_of_the_kit_is_listed_with_one_of_the_four_marks(kit, capsys):
    code, out = run(["--after-teardown", kit], FakeAccount(), capsys)
    rows = rows_of(out)
    assert code == 0
    assert list(rows) == [r.label for r in wr.KIT_COVERAGE[kit]]  # the exact list, in order, nothing dropped
    assert set(rows.values()) <= STATUSES
    for resource in wr.KIT_COVERAGE[kit]:
        expected = wr.COVERAGE_NONE if resource.check_id else wr.COVERAGE_NOT_CHECKABLE
        assert rows[resource.label] == expected, resource.label
    assert f"KIT {kit.upper()} ({wr.KIT_FOLDERS[kit]})" in out
    assert "Audited: account ending 3333; Regions us-east-1; prefixes kitdemo." in out
    result = next(line for line in out.splitlines() if line.startswith("RESULT: "))
    # These tests run with no kit folder beside the script, and since round 2 the RESULT line says so first.
    assert result.startswith("RESULT: no kit folder was found beside this script")
    assert "nothing that bills while idle was found, and every check ran (exit 0)" in result


def test_what_the_audit_cannot_see_is_marked_not_checkable_with_a_place_to_look(capsys):
    code, out = run(["--after-teardown", "c"], FakeAccount(), capsys)
    rows = rows_of(out)
    not_checkable = [label for label, status in rows.items() if status == wr.COVERAGE_NOT_CHECKABLE]
    for needle in ("Open runtime sessions", "IAM roles", "Log delivery sources", "Workload identity", "Gateway target"):
        assert any(needle in label for label in not_checkable), needle
    block = out.split("Open runtime sessions")[1].split("  [")[0]
    assert "look in:" in block and "no AWS API in the installed boto3 lists a runtime's sessions" in block
    assert "900 seconds" in block and "28800 seconds" in block
    assert "console.aws.amazon.com/iam/" in out
    assert "console.aws.amazon.com/bedrock-agentcore/agents" in out and "Log delivery pane" in out
    for resource in (r for kit in wr.KIT_COVERAGE.values() for r in kit):
        if not resource.check_id:
            assert resource.where, f"{resource.label}: a row the audit cannot check must say where to look"


def test_leftovers_are_marked_found_with_their_names_whatever_the_prefix(capsys):
    bucket = f"acme-kitc-code-{TEST_ACCOUNT}-us-east-1"
    groups = ["/aws/vendedlogs/bedrock-agentcore/acme-kitc-usage", "/aws/bedrock-agentcore/runtimes/acme_kitc_fr_agent-AbC-DEFAULT", "/aws/sagemaker/Endpoints/acme-kita-endpoint"]
    account = FakeAccount({
        ("s3", "list_buckets"): {"Buckets": [{"Name": bucket}]},
        ("bedrock-agentcore-control", "list_agent_runtimes"): {"agentRuntimes": [{"agentRuntimeName": "acme_kitc_fr_agent", "agentRuntimeId": "acme_kitc_fr_agent-AbC", "status": "READY"}]},
        ("logs", "describe_log_groups"): log_groups_like_aws(groups),
        ("sagemaker", "list_endpoints"): {"Endpoints": [{"EndpointName": "acme-kita-endpoint", "EndpointStatus": "InService"}]},
    })
    code, out = run(["--after-teardown", "c"], account, capsys)
    rows = rows_of(out)
    assert code == 2
    found = {label for label, status in rows.items() if status == wr.COVERAGE_FOUND}
    assert len(found) == 4
    assert any(label.startswith("S3 bucket") for label in found)
    assert any(label.startswith("AgentCore runtime") for label in found)
    assert "us-east-1: acme-kitc-code-[account ending 3333]-us-east-1 | bills while idle: storage only" in out
    assert "us-east-1: acme_kitc_fr_agent (acme_kitc_fr_agent-AbC, version ?) | bills while idle: storage only | READY, microVMs, direct code deployment, session idle timeout 900 s, session max lifetime 28800 s" in out
    assert TEST_ACCOUNT not in out
    # kit A's endpoint and log group are not kit C rows, but the screen does not hide that they exist
    assert "acme-kita-endpoint" not in "".join(l for l in out.splitlines() if l.startswith("      us-east-1:"))
    assert "not this kit's by name): 2 item(s): bills yes 1, unknown 0, storage only 1, no idle charge 0." in out
    assert "bills while idle, yes:        1" in out and "RESULT: NOT CLEAN (exit 2)" in out
    assert "OPEN SESSIONS CANNOT BE LISTED" in out

    code, out = run(["--after-teardown", "a"], account, capsys)
    rows = rows_of(out)
    assert rows["SageMaker endpoint <prefix>-kita-endpoint"] == wr.COVERAGE_FOUND
    assert rows["CloudWatch log group /aws/sagemaker/Endpoints/<prefix>-kita-endpoint"] == wr.COVERAGE_FOUND
    assert rows["SageMaker model <prefix>-kita-model-<revision>"] == wr.COVERAGE_NONE


def test_a_check_that_failed_or_was_skipped_is_marked_could_not_check_never_none_found(capsys):
    account = FakeAccount({
        ("bedrock-agent", "list_knowledge_bases"): client_error("AccessDeniedException", f"User: arn:aws:iam::{TEST_ACCOUNT}:user/x is not authorized"),
    })
    code, out = run(["--after-teardown", "b", "--skip", "s3vectors"], account, capsys)
    rows = rows_of(out)
    assert code == 2
    assert rows["Bedrock knowledge base <prefix>-fedrag-kb"] == wr.COVERAGE_COULD_NOT
    assert rows["Knowledge base data source <prefix>-fedrag-s3-source"] == wr.COVERAGE_COULD_NOT
    assert rows[next(label for label in rows if label.startswith("S3 Vectors bucket"))] == wr.COVERAGE_COULD_NOT
    assert rows["Bedrock guardrail <prefix>-fedrag-grounding and its version"] == wr.COVERAGE_NONE
    assert "could not check in us-east-1: bedrock-agent.ListKnowledgeBases: AccessDeniedException" in out
    assert "could not check in us-east-1: skipped at your request (--skip)" in out
    assert TEST_ACCOUNT not in out  # account ids in AWS error text are cut to four digits
    assert "could not check: 3" in out
    # the whole-audit list of what did not run is on the same screen
    assert "NOT CHECKED anywhere in this audit" in out
    assert "skipped at your request (--skip), in every Region: s3vectors" in out


def test_a_failed_check_outside_the_kits_rows_is_still_shown_on_the_screen(capsys):
    account = FakeAccount({("ecr", "describe_repositories"): client_error("AccessDeniedException", "denied")})
    code, out = run(["--after-teardown", "a"], account, capsys)
    assert code == 2
    assert wr.COVERAGE_COULD_NOT not in rows_of(out).values()  # no kit A row depends on ECR
    assert "us-east-1 [ecr] ECR repositories whose name carries a kit prefix: COULD NOT CHECK: ecr.DescribeRepositories: AccessDeniedException" in out


def test_found_in_one_region_and_failed_in_another_shows_both(tmp_path, monkeypatch, capsys):
    account = FakeAccount({
        ("sagemaker", "list_endpoints", "us-east-1"): {"Endpoints": [{"EndpointName": "kitdemo-kita-endpoint", "EndpointStatus": "InService"}]},
        ("sagemaker", "list_endpoints", "us-west-2"): client_error("ThrottlingException", "Rate exceeded"),
    })
    code, out = run(["--after-teardown", "a", "--region", "us-west-2"], account, capsys)
    assert code == 2
    assert rows_of(out)["SageMaker endpoint <prefix>-kita-endpoint"] == wr.COVERAGE_FOUND
    assert "us-east-1: kitdemo-kita-endpoint | bills while idle: yes" in out
    assert "could not check in us-west-2: sagemaker.ListEndpoints: ThrottlingException" in out


def test_json_carries_the_same_rows(capsys):
    code, out = run(["--after-teardown", "b", "--json"], FakeAccount(), capsys)
    doc = json.loads(out)
    rows = doc["after_teardown"]["rows"]
    assert doc["after_teardown"]["kit"] == "b" and doc["after_teardown"]["folder"] == "kit_b_federal_rag_eval"
    assert [r["resource"] for r in rows] == [r.label for r in wr.KIT_COVERAGE["b"]]
    assert {r["status"] for r in rows} == {wr.COVERAGE_NONE, wr.COVERAGE_NOT_CHECKABLE}
    assert all(r["where_to_look"] for r in rows if r["status"] == wr.COVERAGE_NOT_CHECKABLE)


def test_dry_run_lists_the_rows_and_makes_no_client(capsys):
    code = wr.main(["--after-teardown", "c", "--dry-run"], client_factory=forbidden_factory)
    out = capsys.readouterr().out
    assert code == 3 and "DRY RUN: no AWS call was made" in out
    assert out.count("[would be checked]") == sum(1 for r in wr.KIT_COVERAGE["c"] if r.check_id)
    assert out.count(f"[{wr.COVERAGE_NOT_CHECKABLE}]") == sum(1 for r in wr.KIT_COVERAGE["c"] if not r.check_id)


def test_kit_letter_is_case_insensitive_and_an_unknown_kit_is_a_usage_error(capsys):
    assert wr.main(["--after-teardown", "B", "--dry-run"], client_factory=forbidden_factory) == 3
    with pytest.raises(SystemExit) as excinfo:
        wr.main(["--after-teardown", "d"], client_factory=forbidden_factory)
    assert excinfo.value.code == 64


def test_coverage_table_points_at_real_checks_and_real_item_kinds():
    check_ids = {c.check_id for c in wr.CHECKS}
    source = (wr.Path(wr.__file__)).read_text(encoding="utf-8")
    for kit, resources in wr.KIT_COVERAGE.items():
        assert kit in wr.KIT_FOLDERS
        for resource in resources:
            if not resource.check_id:
                assert not resource.pattern and not resource.kinds
                continue
            assert resource.check_id in check_ids, resource.label
            re.compile(resource.pattern)
            assert resource.pattern, resource.label
            for kind in resource.kinds:
                assert f'kind="{kind}"' in source, f"{resource.label}: no check yields the item kind {kind!r}"
