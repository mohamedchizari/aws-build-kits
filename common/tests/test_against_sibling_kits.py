"""Does common/ still match the three kit folders beside it?

These tests READ the sibling kit folders (never write them) and are skipped when
the folders are not there. They are the automated form of "the coverage table was
re-checked against the kit's current code": if a kit starts creating a new kind of
resource, or renames one, a test here fails and KIT_COVERAGE in whats_running.py
has to be looked at again.
"""
from __future__ import annotations

import re
from pathlib import Path

import botocore.session
import pytest

import whats_running as wr

KITS_ROOT = Path(__file__).resolve().parents[2]

# Every create, put and start call each kit makes, as boto3 method names, on the day KIT_COVERAGE was written.
CREATING_CALLS = {
    "a": {"create_model", "create_endpoint_config", "create_endpoint"},
    "b": {
        "create_bucket", "put_bucket_tagging", "put_object", "create_role", "put_role_policy", "create_knowledge_base",
        "create_data_source", "start_ingestion_job", "create_guardrail", "create_guardrail_version",
        "create_vector_bucket", "create_index",
    },
    "c": {
        "create_bucket", "put_bucket_tagging", "put_object", "create_role", "put_role_policy", "create_agent_runtime",
        "create_log_group", "put_retention_policy", "put_delivery_source", "put_delivery_destination", "create_delivery",
        "create_gateway", "create_gateway_target",
    },
}
# Name fragments the coverage patterns rely on; each must still be in the kit's code.
NAME_FRAGMENTS = {
    "a": ["kita", "/aws/sagemaker/Endpoints/", "endpoint", "config-", "model-"],
    "b": ["-fedrag", "-corpus-", "-kb", "-s3-source", "-grounding", "-vectors", "-index", "-kb-role-"],
    "c": ["_kitc_fr_agent", "-kitc-code-", "-kitc-usage", "-kitc-app", "-kitc-gateway", "-kitc-runtime-role",
          "/aws/vendedlogs/bedrock-agentcore/", "/aws/bedrock-agentcore/runtimes/"],
}
SERVICES = ("sagemaker", "s3", "iam", "bedrock", "bedrock-agent", "s3vectors", "bedrock-agentcore-control", "bedrock-agentcore", "logs")


def kit_source(kit: str) -> str:
    folder = KITS_ROOT / wr.KIT_FOLDERS[kit]
    if not folder.is_dir():
        pytest.skip(f"{wr.KIT_FOLDERS[kit]} is not beside common/")
    # The path is taken relative to the kit folder: a folder ABOVE the kits that happens to be called "tests"
    # must not make every file look like a test file (round 4, emulator finding 7).
    files = [p for p in sorted(folder.rglob("*.py"))
             if not {"tests", "__pycache__", ".venv"} & set(p.relative_to(folder).parts)]
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in files)


def real_method_names() -> set[str]:
    from botocore import xform_name

    session = botocore.session.get_session()
    return {xform_name(op) for service in SERVICES for op in session.get_service_model(service).operation_names}


@pytest.mark.parametrize("kit", ["a", "b", "c"])
def test_the_kit_makes_no_creating_call_the_coverage_table_does_not_know(kit):
    source = kit_source(kit)
    methods = real_method_names()
    quoted = set(re.findall(r"""["']((?:create|put|start|register|attach|upload|copy|enable|associate|run)_[a-z0-9_]+)["']""", source))
    dotted = set(re.findall(r"""\.((?:create|put|start|register|attach|upload|copy|enable|associate|run)_[a-z0-9_]+)\(""", source))
    used = {name for name in quoted | dotted if name in methods}
    new = used - CREATING_CALLS[kit]
    gone = CREATING_CALLS[kit] - used
    assert not new, f"kit {kit} now calls {sorted(new)}: check whether KIT_COVERAGE[{kit!r}] needs a new row, then add the call here"
    assert not gone, f"kit {kit} no longer calls {sorted(gone)}: check whether a KIT_COVERAGE[{kit!r}] row should go"


@pytest.mark.parametrize("kit", ["a", "b", "c"])
def test_the_names_the_coverage_patterns_rely_on_are_still_in_the_kit(kit):
    source = kit_source(kit)
    missing = [fragment for fragment in NAME_FRAGMENTS[kit] if fragment not in source]
    assert not missing, f"kit {kit} code no longer contains {missing}: the --after-teardown patterns may no longer match"


def test_discovery_reads_the_real_kit_folders_without_error():
    if not any((KITS_ROOT / folder).is_dir() for folder in wr.KIT_FOLDERS.values()):
        pytest.skip("no kit folder is beside common/")
    scope = wr.discover_scope(KITS_ROOT, env={})
    present = [folder for folder in wr.KIT_FOLDERS.values() if (KITS_ROOT / folder).is_dir()]
    assert set(present) <= set(scope.kits_read)
    for folder in present:
        if (KITS_ROOT / folder / "config.example.env").is_file():
            # each kit's example file sets both values, and the audit can read them
            assert any(source == f"{folder}/config.example.env" for sources in scope.regions.values() for source in sources), folder
            assert any(source == f"{folder}/config.example.env" for sources in scope.prefixes.values() for source in sources), folder
    for value in list(scope.regions) + list(scope.prefixes):
        assert not re.search(r"\d{12}", value)


@pytest.mark.parametrize("kit", ["a", "b", "c"])
def test_the_kit_still_keeps_its_settings_and_state_where_the_audit_looks(kit):
    source = kit_source(kit)
    assert "AWS_REGION" in source and "KIT_PREFIX" in source
    assert ".state.json" in source and "config.env" in source
