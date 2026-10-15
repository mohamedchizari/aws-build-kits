"""Small helpers shared by the numbered scripts."""
from __future__ import annotations

import argparse
import sys

from . import pricing

BILLS_FLAG = "--i-understand-this-bills"


def make_parser(description: str, bills: bool = False) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be done (and every AWS API call) and do none of it")
    if bills:
        parser.add_argument(BILLS_FLAG, dest="bills_ok", action="store_true",
                            help="required: confirms you have read the prices this script prints")
    return parser


def require_bills_flag(args: argparse.Namespace, price_lines: list[str]) -> None:
    """Print the expected prices, then stop unless the flag (or --dry-run) was given."""
    print("This script spends money. Expected list prices:")
    for line in price_lines:
        print(f"  - {line}")
    if getattr(args, "dry_run", False):
        print("(--dry-run: nothing will be created and nothing will be billed.)")
        return
    if not getattr(args, "bills_ok", False):
        print(f"\nRefusing to run without {BILLS_FLAG}. Nothing was created.", file=sys.stderr)
        raise SystemExit(2)


def stop(error: Exception) -> int:
    """Print a kitlib.state.StopHere message and return the exit code for it."""
    print(f"\n{error}", file=sys.stderr)
    return 1


FAMILY_NAMES = {"amazon.nova": "Amazon Nova", "amazon.titan": "Amazon Titan", "anthropic.claude": "Anthropic Claude",
                "meta.llama": "Meta Llama", "mistral.mistral": "Mistral"}
# Providers whose model ids this kit can read. An id that names none of them is "could not tell".
KNOWN_PROVIDERS = {"amazon": "Amazon", "anthropic": "Anthropic", "meta": "Meta", "mistral": "Mistral",
                   "cohere": "Cohere", "ai21": "AI21 Labs", "deepseek": "DeepSeek", "openai": "OpenAI",
                   "qwen": "Qwen", "writer": "Writer", "google": "Google", "nvidia": "NVIDIA",
                   "stability": "Stability AI", "luma": "Luma", "twelvelabs": "TwelveLabs"}


def _model_parts(model_id: str) -> tuple[str | None, str]:
    """(provider, the rest of the id after the provider) from any way a Bedrock model id is written.

    Accepts a plain id (amazon.nova-pro-v1:0), an inference-profile id (us.amazon.nova-pro-v1:0),
    an ARN of either (the text after the last "/"), in any case. The provider is the first of
    the first two dot-separated parts that is a known provider; otherwise it is None.
    """
    text = (model_id or "").strip().rsplit("/", 1)[-1].lower()
    parts = text.split(".")
    for position in (0, 1):
        if position < len(parts) - 1 and parts[position] in KNOWN_PROVIDERS:
            return parts[position], ".".join(parts[position + 1:])
    return None, text


def model_provider(model_id: str) -> str | None:
    """'amazon' for amazon.nova-lite-v1:0 and for an ARN of us.amazon.nova-pro-v1:0. None if it cannot be read."""
    return _model_parts(model_id)[0]


def model_family(model_id: str) -> str:
    """'Amazon Nova' for amazon.nova-lite-v1:0. The provider's name alone for a model line this kit has no
    name for, and 'unknown' when the provider cannot be read. For display only: judge_family_line decides
    by provider."""
    provider, rest = _model_parts(model_id)
    if provider is None:
        return "unknown"
    line = rest.split("-")[0]
    return FAMILY_NAMES.get(f"{provider}.{line}", KNOWN_PROVIDERS[provider])


def judge_family_line(gen_model_id: str, judge_model_id: str) -> str:
    """The disclosure that goes wherever the results table is described.

    "different families" is printed only when both ids name a known provider and the two
    providers differ. Two models of one provider are never called different, whatever their
    names (Nova Lite and Nova Pro, Llama 3 and Llama 4, Mistral and Mixtral). An id that cannot
    be read gives COULD NOT TELL.
    """
    gen_provider, judge_provider = model_provider(gen_model_id), model_provider(judge_model_id)
    gen, judge = model_family(gen_model_id), model_family(judge_model_id)
    caution = ("A judge can favour answers written in its own family's style, so say this whenever you quote "
               "a judged number.")
    if gen_provider is None or judge_provider is None:
        unread = " and ".join(f"'{model_id}'" for model_id, provider in
                              ((judge_model_id, judge_provider), (gen_model_id, gen_provider)) if provider is None)
        return (f"COULD NOT TELL: the provider could not be read from {unread} (judge '{judge_model_id}', "
                f"generator '{gen_model_id}'). Find out which model that is, and do not call the judge "
                "independent of the generator unless you know they come from two providers.")
    if gen_provider != judge_provider:
        return (f"different families: the judge ({judge_model_id}) is from the {judge} family, the generator "
                f"({gen_model_id}) is from the {gen} family")
    if gen == judge:
        return (f"SAME FAMILY: the judge ({judge_model_id}) and the generator ({gen_model_id}) are both "
                f"{judge} models. {caution}")
    return (f"SAME PROVIDER: the judge ({judge_model_id}, {judge}) and the generator ({gen_model_id}, {gen}) are "
            f"both {KNOWN_PROVIDERS[gen_provider]} models. {caution}")


def banner(text: str) -> None:
    line = "=" * max(20, min(100, len(text) + 4))
    print(f"\n{line}\n  {text}\n{line}")


def opensearch_warning(collections: list[dict]) -> list[str]:
    """Loud text for any OpenSearch Serverless collection. Used by 00_check.py and 99_verify_clean.py."""
    if not collections:
        return []
    floor = pricing.opensearch_classic_floor_per_day()
    lines = [
        "!" * 78,
        f"!!  WARNING: {len(collections)} OpenSearch Serverless collection(s) exist in this account and Region.",
        "!!  This kit did not create them and never creates one.",
        f"!!  A Classic collection bills at least {pricing.OPENSEARCH_SERVERLESS_MIN_OCU_CLASSIC} OCUs at "
        f"${pricing.OPENSEARCH_SERVERLESS_OCU_HOUR:.2f} per OCU-hour whether or not it is queried:",
        f"!!  {pricing.OPENSEARCH_SERVERLESS_MIN_OCU_CLASSIC} x ${pricing.OPENSEARCH_SERVERLESS_OCU_HOUR:.2f} x 24 h "
        f"= ${floor:.2f} a day, about ${floor * 30:.2f} in 30 days ({pricing.REGION}, read {pricing.READ_DATE},",
        "!!  https://aws.amazon.com/opensearch-service/pricing/ ).",
        "!!  NextGen collections have no minimum; this script cannot tell which kind yours are.",
        "!!  A knowledge base that used an OpenSearch Serverless vector store leaves the collection",
        "!!  behind when the knowledge base is deleted (docs.aws.amazon.com/bedrock/latest/userguide/kb-delete.html).",
    ]
    for c in collections:
        lines.append(f"!!    - {c.get('name')}  id={c.get('id')}  type={c.get('type', '?')}  "
                     f"status={c.get('status')}  group={c.get('collectionGroupName', '-')}")
    lines += ["!!  If you do not need them, delete them in the OpenSearch Service console and check the bill.",
              "!" * 78]
    return lines
