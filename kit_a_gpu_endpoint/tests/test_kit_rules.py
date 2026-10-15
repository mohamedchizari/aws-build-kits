"""Checks that the kit keeps the rules it was written under (the spine): README headings, pinned
requirements, a documentation link on every AWS call, no stray identifiers, and a README that owns up to
every unverified shape."""

from __future__ import annotations

import json
import re

from conftest import KIT_DIR, SCRIPT_NAMES

CODE_FILES = sorted(p for p in KIT_DIR.glob("*.py"))
TEXT_FILES = sorted(
    p for p in KIT_DIR.rglob("*")
    if p.is_file() and p.suffix in {".py", ".md", ".txt", ".env", ".json", ""} and "__pycache__" not in p.parts
    and p.name not in {".state.json", "config.env"} and "results" not in p.parts and ".venv" not in p.parts
)
README = (KIT_DIR / "README.md").read_text(encoding="utf-8")

# (service, operation) pairs the kit may call, and the API name the README must list as NOT RUN.
EXPECTED_CALLS = {
    ("sts", "get_caller_identity"): "GetCallerIdentity",
    ("service-quotas", "get_service_quota"): "GetServiceQuota",
    ("service-quotas", "get_aws_default_service_quota"): "GetAWSDefaultServiceQuota",
    ("iam", "get_role"): "GetRole",
    ("sagemaker", "create_model"): "CreateModel",
    ("sagemaker", "create_endpoint_config"): "CreateEndpointConfig",
    ("sagemaker", "create_endpoint"): "CreateEndpoint",
    ("sagemaker", "describe_endpoint"): "DescribeEndpoint",
    ("sagemaker", "list_endpoints"): "ListEndpoints",
    ("sagemaker", "list_endpoint_configs"): "ListEndpointConfigs",
    ("sagemaker", "list_models"): "ListModels",
    ("sagemaker", "list_tags"): "ListTags",
    ("sagemaker", "delete_endpoint"): "DeleteEndpoint",
    ("sagemaker", "delete_endpoint_config"): "DeleteEndpointConfig",
    ("sagemaker", "delete_model"): "DeleteModel",
    ("sagemaker-runtime", "invoke_endpoint"): "InvokeEndpoint",
    ("sagemaker-runtime", "invoke_endpoint_with_response_stream"): "InvokeEndpointWithResponseStream",
    ("cloudwatch", "get_metric_statistics"): "GetMetricStatistics",
    ("logs", "filter_log_events"): "FilterLogEvents",
    ("logs", "describe_log_groups"): "DescribeLogGroups",
    ("logs", "delete_log_group"): "DeleteLogGroup",
}
LITERAL_CALL = re.compile(r'(?:\.call|_delete_quietly)\(\s*(?:aws,\s*)?"([a-z-]+)",\s*"([a-z_]+)"')
PLAN_ROW = re.compile(r'^\s*\("(list_[a-z_]+)",')
DOC_URL = re.compile(r"#.*https://docs\.aws\.amazon\.com/\S+")


def test_readme_has_exactly_the_nine_headings_in_order():
    headings = [line[3:].strip() for line in README.splitlines() if line.startswith("## ")]
    assert headings == [
        "1. What this is",
        "2. Problems first",
        "3. Before you start",
        "4. Run it",
        "5. Tear it down and prove it",
        "6. What to record",
        "7. What you can truthfully say afterwards, and what you cannot",
        "8. What was and was not tested",
        "9. Sources",
    ]


def test_expected_files_exist_and_requirements_are_pinned():
    for name in SCRIPT_NAMES:
        assert (KIT_DIR / f"{name}.py").is_file(), name
    for name in ("README.md", "requirements.txt", "config.example.env", "RESULTS_TEMPLATE.md",
                 "iam/execution_role_trust.json", "iam/execution_role_permissions.json"):
        assert (KIT_DIR / name).is_file(), name
    pins = [line.strip() for line in (KIT_DIR / "requirements.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")]
    assert pins and all(re.fullmatch(r"[A-Za-z0-9_.-]+==\d+(\.\d+)+", pin) for pin in pins), pins
    assert "boto3==1.43.108" in pins
    trust = json.loads((KIT_DIR / "iam/execution_role_trust.json").read_text(encoding="utf-8"))
    assert trust["Statement"][0]["Principal"] == {"Service": "sagemaker.amazonaws.com"}
    permissions = json.loads((KIT_DIR / "iam/execution_role_permissions.json").read_text(encoding="utf-8"))
    actions = permissions["Statement"][0]["Action"]
    assert "ecr:BatchGetImage" in actions and "logs:PutLogEvents" in actions and not any(a.startswith("s3:") for a in actions)


def test_every_aws_call_site_carries_a_doc_url_and_the_date_it_was_read():
    missing = []
    seen = set()
    for path in CODE_FILES:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        sites = [(text.count("\n", 0, m.start()), (m.group(1), m.group(2))) for m in LITERAL_CALL.finditer(text)]
        sites += [(number, ("sagemaker", PLAN_ROW.match(line).group(1)))
                  for number, line in enumerate(lines) if PLAN_ROW.match(line)]
        for number, call in sites:
            seen.add(call)
            window = "\n".join(lines[max(0, number - 6):number + 1])
            api_name = EXPECTED_CALLS.get(call, "an operation this kit should not call")
            named = re.search(rf"#.*\b{re.escape(api_name)}\b", window)
            cited = named and DOC_URL.search(window) and "read 2026-10-07" in window
            if not cited and "same page as above" not in window:
                missing.append(f"{path.name}:{number + 1}: {call[0]}.{call[1]}")
    assert not missing, "AWS call sites without a documentation comment:\n" + "\n".join(missing)
    assert seen == set(EXPECTED_CALLS), f"unexpected or missing AWS operations: {seen ^ set(EXPECTED_CALLS)}"


def test_readme_lists_every_aws_call_as_not_run_and_every_unverified_marker():
    section = README.split("## 8. What was and was not tested")[1].split("## 9. Sources")[0]
    for label in ("**SAFE:", "**NOT RUN:", "**UNVERIFIED:"):
        assert label in section, label
    not_run = section.split("**NOT RUN:")[1].split("**UNVERIFIED:")[0]
    for api_name in EXPECTED_CALLS.values():
        assert re.search(rf"\b{api_name}\b", not_run), f"{api_name} is called by the kit but not listed as NOT RUN"
    assert "/openai/v1/chat/completions" in not_run
    unverified = section.split("**UNVERIFIED:")[1]
    markers = []
    for path in CODE_FILES:
        text = path.read_text(encoding="utf-8")
        markers += [(path.name, m.start()) for m in re.finditer(r"# UNVERIFIED:", text)]
    by_file = {name: sum(1 for marked, _ in markers if marked == name) for name, _ in markers}
    assert by_file == {"00_check.py": 1, "10_deploy.py": 1, "50_invoke.py": 3, "60_loadtest.py": 2, "kitlib.py": 3,
                       "streamstats.py": 1}, \
        f"UNVERIFIED markers in code changed: {by_file}. Update README section 8 and this test."
    # One keyword per marker in code; each must be owned up to in README section 8.
    for keyword in ("InferenceAmiVersion", "CreationTime", "Could not find", "0.92", "stream_options",
                    "chat_template_kwargs", "ignore_eos", "Hugging Face id as `model`", "ModelStreamError.Message",
                    "keeps the warm-up connections open", "Cannot create already existing endpoint"):
        assert keyword in unverified, f"README section 8 does not mention the unverified item '{keyword}'"


def test_no_dashes_secrets_or_stray_account_ids():
    allowed_numbers = {
        "763104351884",  # AWS's public Deep Learning Containers registry account, from the AWS image list
        "111122223333",  # the example account id used throughout AWS documentation (tests only)
        "444455556666",  # a second example account id from AWS documentation (tests only)
    }
    problems = []
    for path in TEXT_FILES:
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(KIT_DIR)
        if chr(0x2014) in text or chr(0x2013) in text:
            problems.append(f"{relative}: contains an em dash or en dash")
        for number in set(re.findall(r"(?<!\d)\d{12}(?!\d)", text)) - allowed_numbers:
            problems.append(f"{relative}: 12-digit number {number} looks like an account id")
        if re.search(r"AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|aws_secret_access_key\s*=\s*\S{20,}|hf_[A-Za-z0-9]{20,}", text):
            problems.append(f"{relative}: looks like it contains a credential")
    assert not problems, "\n".join(problems)
    for path in TEXT_FILES:
        if path.suffix == ".py" and "tests" not in path.parts:
            text = path.read_text(encoding="utf-8")
            assert "111122223333" not in text and "444455556666" not in text, f"{path.name} contains an example account id"


def test_billing_scripts_declare_the_flag_and_every_script_says_it_was_never_run():
    for name in SCRIPT_NAMES:
        text = (KIT_DIR / f"{name}.py").read_text(encoding="utf-8")
        assert "kitlib.base_parser(" in text, f"{name} does not use the shared parser with --dry-run"
        assert "Never run against AWS" in text, f"{name} does not say it was never run against AWS"
        creates = bool(re.search(r"create_stack\(", text))
        declares = "bills=True" in text
        assert creates == declares, f"{name}: creates billable resources={creates}, declares the flag={declares}"
    assert {n for n in SCRIPT_NAMES if "bills=True" in (KIT_DIR / f"{n}.py").read_text(encoding="utf-8")} == {
        "10_deploy", "70_change_one_setting"}


# ---------------------------------------------------------------- added after the review of 2026-10-07 (round 1)

def test_readme_permission_list_names_every_iam_action_the_scripts_need():
    """Finding 4: the list omitted sagemaker:InvokeEndpointWithResponseStream, a separate IAM action."""
    paragraph = README.split("**Your identity needs these permissions.**")[1].split("\n- **")[0]
    # The list itself is the first sentence; the sentences after it explain two of the entries.
    listed, explained = paragraph.split("`cloudwatch:GetMetricStatistics`.", 1)
    listed += "`cloudwatch:GetMetricStatistics`"
    for api_name in list(EXPECTED_CALLS.values()) + ["CallWithBearerToken", "PassRole"]:
        if api_name == "GetCallerIdentity":
            assert "`sts:GetCallerIdentity`" in explained and "No permissions are required" in explained
            continue
        assert re.search(rf"`[a-z:]*{api_name}`", listed), f"{api_name} is called by the kit but missing from the permission list"


def test_every_script_compares_the_state_file_with_the_current_shell():
    for name in SCRIPT_NAMES:
        text = (KIT_DIR / f"{name}.py").read_text(encoding="utf-8")
        assert "AWS_REGION overrides config.env" in text, f"{name}: the docstring must say an exported AWS_REGION wins"
        if name == "99_verify_clean":
            assert "kitlib.named_scopes(" in text and "kitlib.caller_account(" in text and "EXIT_DRY_RUN = 3" in text
        else:
            assert "kitlib.require_state_matches(" in text, f"{name} reads the state file without comparing it"
    kitlib_text = (KIT_DIR / "kitlib.py").read_text(encoding="utf-8")
    assert "overrides config.env" in kitlib_text


def test_readme_states_the_region_account_prefix_rule_and_the_audit_command():
    section5 = README.split("## 5. Tear it down and prove it")[1].split("## 6. What to record")[0]
    assert "python ../common/whats_running.py --region <the AWS_REGION in your config.env> --prefix <your KIT_PREFIX>" in section5
    assert not re.search(r"whats_running\.py --region [a-z]{2}-[a-z]+-\d", README), "the audit command must not hardcode a Region"
    assert "An exported `AWS_REGION` overrides `config.env`" in section5
    assert "RESULT: INCOMPLETE" in section5 and "| 3 |" in section5
    section8 = README.split("## 8. What was and was not tested")[1].split("## 9. Sources")[0]
    assert re.search(r"Reviewed independently on 2026-10-07 \(round 1\): \d+ findings, \d+ fixed, \d+ left open \(listed below\)",
                     section8)
    ignored = (KIT_DIR / ".gitignore").read_text(encoding="utf-8").split()
    for entry in (".state.json", "config.env", "results/", ".venv/"):
        assert entry in ignored, f"{entry} is not git-ignored"
