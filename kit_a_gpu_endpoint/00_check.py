#!/usr/bin/env python3
"""00_check.py: read-only preflight. Creates nothing, costs nothing.

Checks, in order: local Python and boto3, AWS identity, Region, the applied Service Quotas value for
the GPU endpoint instance type, the SageMaker execution role, anything this kit already left in the
account, and whether the model on Hugging Face is open (not gated).

If .state.json records a deploy in another Region, account or prefix than this shell points at, the
script stops and says so (exit 2). An exported AWS_REGION overrides config.env.

Exit code 0 means every check passed. 1 means at least one FAIL line. 2 means it could not run.
Never run against AWS by the author of this kit: there was no AWS account. See README section 8.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

import kitlib
from kitlib import Aws, Config

HF_API = "https://huggingface.co/api/models/"


def account_tail(account: str) -> str:
    """Last four digits only, so a pasted terminal log does not carry the whole account id."""
    return kitlib.account_tail(account)


def trust_allows_sagemaker(document: Any) -> bool:
    """True when the role's trust policy lets sagemaker.amazonaws.com assume it.

    Trust policy shape: https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-roles.html (read 2026-10-07).
    """
    if isinstance(document, str):
        try:
            document = json.loads(urllib.parse.unquote(document))
        except ValueError:
            return False
    statements = (document or {}).get("Statement", [])
    if isinstance(statements, dict):
        statements = [statements]
    for statement in statements:
        if statement.get("Effect") != "Allow":
            continue
        services = (statement.get("Principal") or {}).get("Service", [])
        if isinstance(services, str):
            services = [services]
        if "sagemaker.amazonaws.com" in services:
            return True
    return False


def fetch_hf_model(model_id: str, timeout: float = 15.0) -> dict[str, Any]:
    """Public Hugging Face model metadata. Not an AWS call. No token is sent."""
    url = HF_API + urllib.parse.quote(model_id, safe="/")
    request = urllib.request.Request(url, headers={"User-Agent": "aws-kits-kit-a-preflight"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https host
        return json.loads(response.read().decode("utf-8"))


def print_memory_arithmetic(cfg: Config, out: Callable[[str], None]) -> None:
    facts = kitlib.MODEL_FACTS.get(cfg.hf_model_id)
    instance = kitlib.INSTANCES.get(cfg.instance_type)
    if not facts or not instance:
        out("INFO  Memory arithmetic: no recorded facts for this model or instance type. Do it by hand, README section 2.")
        return
    # UNVERIFIED: 0.92 as the share vLLM takes inside this image when GPU_MEMORY_UTILIZATION is empty. It is the
    # default in vLLM v0.30.0 source (vllm/config/cache.py, read 2026-10-07); the AWS container docs table says 0.9.
    # No AWS page confirms either for this image tag. Used only for the arithmetic printed below.
    utilisation = float(cfg.gpu_memory_utilization) if cfg.gpu_memory_utilization else 0.92
    est = kitlib.memory_estimate(facts, cfg.max_model_len, cfg.max_num_seqs, instance["gpu_mem_gib"], utilisation)
    out(f"INFO  Memory arithmetic for {cfg.hf_model_id} on {cfg.instance_type} ({instance['gpu']}, "
        f"{instance['gpu_mem_gib']} GiB), formulas and sources in README section 2:")
    out(f"        weights at 2 bytes per parameter:            {est['weights_gib']:.2f} GiB")
    out(f"        vLLM budget at gpu_memory_utilization {utilisation:.2f}: {est['vllm_budget_gib']:.2f} GiB")
    out(f"        left for KV cache before overhead:           {est['kv_pool_before_overhead_gib']:.2f} GiB")
    out(f"        KV cache per full {cfg.max_model_len}-token sequence:      {est['kv_per_full_sequence_lmi_gib']:.2f} GiB "
        f"(AWS LMI formula), {est['kv_per_full_sequence_gqa_gib']:.2f} GiB (adjusted for 8 key/value heads)")
    out(f"        full-length sequences that fit:              {est['full_sequences_that_fit_lmi']:.1f} "
        f"(LMI formula), {est['full_sequences_that_fit_gqa']:.1f} (adjusted)")
    out("        Compare with the container's own log line 'Maximum concurrency for N tokens per request' (55_observe.py).")


def run(args: Any, cfg: Config, aws: Aws, out: Callable[[str], None] = print,
        hf_fetch: Callable[[str], dict[str, Any]] = fetch_hf_model) -> int:
    failures = 0
    warnings = 0

    def fail(message: str) -> None:
        nonlocal failures
        failures += 1
        out(f"FAIL  {message}")

    def warn(message: str) -> None:
        nonlocal warnings
        warnings += 1
        out(f"WARN  {message}")

    out(f"Kit A preflight. Region {cfg.region}, prefix {cfg.prefix}, instance {cfg.instance_type}, model {cfg.hf_model_id}.")
    if aws.dry_run:
        out("DRY RUN: the AWS calls below are printed, not made. Nothing is checked against your account.")

    # 1. Local
    if sys.version_info < (3, 11):
        fail(f"Python {sys.version_info.major}.{sys.version_info.minor} found. This kit needs Python 3.11 or newer.")
    else:
        out(f"PASS  Python {sys.version_info.major}.{sys.version_info.minor}")
    try:
        import boto3

        out(f"PASS  boto3 {boto3.__version__} (requirements.txt pins 1.43.108)")
    except ImportError:
        fail("boto3 is not installed. Run: python -m pip install -r requirements.txt")

    # 2. Price the owner is about to accept
    try:
        price, source = kitlib.price_for(cfg.instance_type, cfg.region, getattr(args, "price_per_hour", None))
        out(f"INFO  Expected price: ${price:.4f} per hour for {cfg.instance_type} real-time hosting in {cfg.region}.")
        out(f"        Source: {source}")
        out(f"        {cfg.max_hours:g} h (MAX_HOURS) costs about ${price * cfg.max_hours:.2f}. "
            f"Left running for 24 h: about ${price * 24:.2f}.")
    except kitlib.KitError as exc:
        warn(str(exc))

    # 3. Identity
    # GetCallerIdentity: https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html (read 2026-10-07)
    identity = aws.call("sts", "get_caller_identity")
    account = None
    if identity is not None:
        arn = identity.get("Arn", "")
        account = str(identity.get("Account", "")) or None
        out(f"PASS  Signed in. Account ending {account_tail(identity.get('Account', ''))}, "
            f"principal type {arn.split(':')[5].split('/')[0] if arn.count(':') >= 5 else 'unknown'}.")
        if arn.endswith(":root"):
            warn("You are signed in as the account root user. Use an IAM Identity Center user or IAM role instead.")

    # 3b. Does the state file point at the same Region, account and prefix as this shell? Stop if not.
    state = kitlib.load_state(args.state_path)
    kitlib.require_state_matches(state, cfg, account, args.state_path.name)

    # 4. Quota
    quota = kitlib.read_quota(aws, cfg.instance_type)
    quota_name = f"{cfg.instance_type} for endpoint usage"
    if quota["code"] is None:
        warn(f"No quota code is recorded in this kit for {cfg.instance_type}. Look up '{quota_name}' in the "
             "Service Quotas console yourself.")
    elif quota["value"] is not None:
        if quota["value"] >= 1:
            out(f"PASS  Quota '{quota_name}' ({quota['code']}) is {quota['value']:g}. Source: {quota['source']}.")
        else:
            fail(f"Quota '{quota_name}' ({quota['code']}) is {quota['value']:g}. Source: {quota['source']}. "
                 "The AWS default is 0, so this is normal for a new account. Nothing can be deployed until it is 1.")
            out("        You file the request, this kit does not. Either use the Service Quotas console, or run:")
            out(f"        {kitlib.quota_request_command(cfg.instance_type, cfg.region)}")
            out("        Ask for 1, not more. AWS does not publish how long approval takes.")

    # 5. Execution role
    try:
        # GetRole: https://docs.aws.amazon.com/IAM/latest/APIReference/API_GetRole.html (read 2026-10-07)
        role = aws.call("iam", "get_role", RoleName=cfg.role_name)
    except Exception as exc:  # noqa: BLE001 - classified just below
        if kitlib.error_code(exc) not in ("NoSuchEntity", "NoSuchEntityException"):
            raise
        role = {}
        fail(f"IAM role '{cfg.role_name}' does not exist. Create it (README section 3, step 4).")
    if role:
        if trust_allows_sagemaker(role.get("Role", {}).get("AssumeRolePolicyDocument")):
            out(f"PASS  IAM role '{cfg.role_name}' exists and trusts sagemaker.amazonaws.com.")
        else:
            fail(f"IAM role '{cfg.role_name}' exists but its trust policy does not allow sagemaker.amazonaws.com.")
        out("INFO  Not checked: the role's permissions (it needs ECR pull and CloudWatch Logs write), "
            "and your own iam:PassRole on it.")

    # 6. Leftovers from an earlier run
    if kitlib.state_resources(state, "endpoint"):
        warn(f"{args.state_path.name} already records an endpoint. Tear it down before deploying again.")
        for line in kitlib.billing_lines(state, kitlib.utc_now()):
            out(line)
    found = kitlib.find_remaining(aws, cfg, check_logs=True)
    if not aws.dry_run:
        count = kitlib.remaining_count(found)
        if count:
            warn(f"{count} resource(s) from this kit already exist in {cfg.region}:")
            for line in kitlib.describe_remaining(found):
                out("        " + line)
        else:
            out(f"PASS  No resources from this kit exist in {cfg.region}. "
                f"Other SageMaker endpoints in the Region: {found['other_endpoints']}.")

    # 7. Model access (Hugging Face, not AWS)
    if args.skip_hf_check:
        out("SKIP  Hugging Face model check (--skip-hf-check).")
    elif aws.dry_run:
        out(f"DRY-RUN would GET {HF_API}{cfg.hf_model_id} (public Hugging Face metadata, no token, not an AWS call)")
    else:
        try:
            info = hf_fetch(cfg.hf_model_id)
            licence = (info.get("cardData") or {}).get("license", "unknown")
            if info.get("gated") or info.get("private"):
                fail(f"Model {cfg.hf_model_id} is gated or private on Hugging Face. This kit sends no token. "
                     "Choose an open model.")
            else:
                out(f"PASS  Model {cfg.hf_model_id} is open on Hugging Face (gated: False). Licence tag: {licence}.")
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            warn(f"Could not read Hugging Face metadata for {cfg.hf_model_id} from this machine ({exc}). "
                 "The endpoint, not this machine, downloads the weights, so this is a warning only.")

    print_memory_arithmetic(cfg, out)

    out("")
    if aws.dry_run:
        out(f"DRY RUN finished: {aws.calls_printed} AWS call(s) printed, 0 made.")
        return 0
    out(f"Preflight finished: {failures} FAIL, {warnings} WARN.")
    if failures:
        out("Do not deploy yet. Fix the FAIL lines, then run this again.")
        return 1
    out("Next: python 10_deploy.py --i-understand-this-bills")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = kitlib.base_parser(__doc__ or "")
    parser.add_argument("--skip-hf-check", action="store_true", help="Do not contact huggingface.co.")
    parser.add_argument("--price-per-hour", type=float, default=None,
                        help="A price you read yourself, for a Region or instance type this kit has no price for.")
    args = parser.parse_args(argv)
    args.state_path = kitlib.STATE_FILE
    cfg = kitlib.load_config()
    return run(args, cfg, Aws(cfg.region, args.dry_run))


if __name__ == "__main__":
    sys.exit(kitlib.guarded(main))
