"""List prices used for the cost estimates this kit prints.

Every figure below was read on 2026-10-07. Nothing here is from memory.
Region: US East (N. Virginia), us-east-1, unless a line says otherwise.
These are estimates at list price. The bill is the only real number.

Sources
  [P1] AWS Price List file, offer AmazonBedrock, us-east-1, publication date 2026-10-06
       https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/current/us-east-1/index.json
  [P2] AWS Price List file, offer AmazonBedrockFoundationModels, us-east-1, publication date 2026-09-30
       https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrockFoundationModels/current/us-east-1/index.json
  [P3] Amazon Bedrock pricing page (the Managed Knowledge Base and Guardrails tables state no Region)
       https://aws.amazon.com/bedrock/pricing/
  [P4] AWS Price List file, offer AmazonS3, us-east-1, publication date 2026-09-28
       https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonS3/current/us-east-1/index.json
  [P5] AWS Price List file, offer AmazonES (OpenSearch Service), us-east-1, publication date 2026-09-27
       https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonES/current/us-east-1/index.json
  [P6] Amazon OpenSearch Service pricing page
       https://aws.amazon.com/opensearch-service/pricing/
"""
from __future__ import annotations

import math
import os

READ_DATE = "2026-10-07"
REGION = "us-east-1"

# USD per 1,000,000 tokens (input, output), standard on-demand tier.
MODEL_PRICES_PER_1M = {
    # [P1] USE1-NovaLite-input-tokens $0.00006 per 1K; USE1-NovaLite-output-tokens $0.00024 per 1K
    "amazon.nova-lite-v1:0": (0.06, 0.24),
    # [P1] USE1-NovaMicro-input-tokens $0.000035 per 1K; output $0.00014 per 1K
    "amazon.nova-micro-v1:0": (0.035, 0.14),
    # [P1] USE1-NovaPro-input-tokens $0.0008 per 1K; output $0.0032 per 1K
    "amazon.nova-pro-v1:0": (0.80, 3.20),
    # [P2] Claude Haiku 4.5, "Million Input Tokens Regional" $1.10, "Million Response Tokens Regional" $5.50
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": (1.10, 5.50),
    # [P2] Claude Haiku 4.5, "Million Input Tokens Global" $1.00, "Million Response Tokens Global" $5.00
    "global.anthropic.claude-haiku-4-5-20251001-v1:0": (1.00, 5.00),
}

# [P1] USE1-TitanEmbeddingV2-Text-input-tokens $0.00002 per 1K tokens (only used when KB_TYPE=s3vectors)
EMBED_PRICE_PER_1M = {"amazon.titan-embed-text-v2:0": 0.02}

# [P1] USE1-Guardrail-ContextualGroundingPolicyUnitsConsumed $0.1 per 1K text units.
# [P3] "A text unit can contain up to 1000 characters"; for contextual grounding the units are
#      "calculated by combining all the characters in the source, query, and model response."
GUARDRAIL_GROUNDING_PER_1K_UNITS = 0.10
GUARDRAIL_TEXT_UNIT_CHARS = 1000

# [P3] Managed Knowledge Base: "Index Storage $5.00 per GB of raw data / month";
#      "Standard Retrieval (Retrieve API) $1.00 per 1,000 API calls"; managed parsing,
#      managed embeddings and managed re-ranking $0. No Region and no minimum charge is stated.
# UNVERIFIED: whether storage is billed pro rata for a part month, whether a minimum applies,
#      and whether the us-east-1 price equals the page price. These rows are not in the
#      us-east-1 Price List files [P1] [P2] read on the same day.
MANAGED_KB_STORAGE_PER_GB_MONTH = 5.00
MANAGED_KB_RETRIEVE_PER_1K_CALLS = 1.00

# [P4] S3 Standard: $0.023 per GB-month (first 50 TB); $0.005 per 1,000 PUT/COPY/POST/LIST requests.
S3_STANDARD_PER_GB_MONTH = 0.023
S3_PUT_PER_1K = 0.005
# [P4] S3 Vectors: storage $0.06 per GB-month; PUT $0.20 per GB; query requests $0.0000025 each
#      plus a small per-GB data-processed fee.
S3_VECTORS_STORAGE_PER_GB_MONTH = 0.06
S3_VECTORS_PUT_PER_GB = 0.20
S3_VECTORS_QUERY_PER_REQUEST = 0.0000025

# [P5] USE1-SearchOCU and USE1-IndexingOCU: $0.24 per OCU-hour.
# [P6] "You will be billed at least for a minimum of 2 OCUs ... for the first collection in an account."
OPENSEARCH_SERVERLESS_OCU_HOUR = 0.24
OPENSEARCH_SERVERLESS_MIN_OCU_CLASSIC = 2


def opensearch_classic_floor_per_day() -> float:
    """2 OCU x $0.24 x 24 h = $11.52 a day, with zero queries."""
    return OPENSEARCH_SERVERLESS_MIN_OCU_CLASSIC * OPENSEARCH_SERVERLESS_OCU_HOUR * 24


def fmt_usd(value: float) -> str:
    """$0.06, $0.80, $0.035: at least two decimals, a third only when needed."""
    text = f"{value:.3f}"
    return "$" + (text[:-1] if text.endswith("0") else text)


def _env_float(name: str) -> float | None:
    value = os.environ.get(name)
    return float(value) if value else None


def model_price(model_id: str, role: str) -> tuple[float, float] | None:
    """(input, output) USD per 1M tokens. role is 'GEN' or 'JUDGE'.

    PRICE_<role>_INPUT_PER_1M and PRICE_<role>_OUTPUT_PER_1M override the table,
    which you need if you pick a model that is not listed above.
    """
    override_in = _env_float(f"PRICE_{role}_INPUT_PER_1M")
    override_out = _env_float(f"PRICE_{role}_OUTPUT_PER_1M")
    if override_in is not None and override_out is not None:
        return (override_in, override_out)
    return MODEL_PRICES_PER_1M.get(model_id)


def token_cost(input_tokens: int, output_tokens: int, price: tuple[float, float] | None) -> float | None:
    if price is None:
        return None
    return (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000


def grounding_text_units(source_chars: int, query_chars: int, answer_chars: int) -> int:
    """Estimate only. The real count comes back in the ApplyGuardrail response."""
    return max(1, math.ceil((source_chars + query_chars + answer_chars) / GUARDRAIL_TEXT_UNIT_CHARS))


def guardrail_cost(text_units: int) -> float:
    return text_units * GUARDRAIL_GROUNDING_PER_1K_UNITS / 1000


def retrieve_cost(calls: int, kb_type: str) -> float:
    if kb_type == "managed":
        return calls * MANAGED_KB_RETRIEVE_PER_1K_CALLS / 1000
    return calls * S3_VECTORS_QUERY_PER_REQUEST


def estimate_tokens(chars: int) -> int:
    """ASSUMPTION, not an AWS figure: about 4 characters per token for English text.

    UNVERIFIED: that 4 characters per token is close for the Amazon Nova models. It is used
    only for the estimate printed before a run; the cost after a run uses the token counts
    AWS returned.
    """
    return math.ceil(chars / 4)


def estimate_eval_run(n_questions: int, top_k: int, mean_doc_chars: float, gen_model: str,
                      judge_model: str, kb_type: str, use_guardrail: bool = True) -> dict:
    """Rough cost of one run of 50_run_eval.py, printed before it starts.

    use_guardrail False (--no-guardrail): no ApplyGuardrail call is made, so no text unit is estimated.
    """
    prompt_overhead_chars = 900          # system prompt plus passage labels
    question_chars = 200
    answer_chars = 200
    judge_prompt_chars = 1200
    judge_answer_chars = 120
    source_chars = top_k * mean_doc_chars

    gen_in = n_questions * estimate_tokens(prompt_overhead_chars + question_chars + source_chars)
    gen_out = n_questions * estimate_tokens(answer_chars)
    judge_in = n_questions * estimate_tokens(judge_prompt_chars + question_chars + answer_chars)
    judge_out = n_questions * estimate_tokens(judge_answer_chars)
    units = n_questions * grounding_text_units(int(source_chars), question_chars, answer_chars) if use_guardrail else 0

    gen_cost = token_cost(gen_in, gen_out, model_price(gen_model, "GEN"))
    judge_cost = token_cost(judge_in, judge_out, model_price(judge_model, "JUDGE"))
    parts = {
        "generation": gen_cost,
        "judge": judge_cost,
        "guardrail_grounding": guardrail_cost(units) if use_guardrail else 0.0,
        "retrieve_calls": retrieve_cost(n_questions, kb_type),
    }
    known = [v for v in parts.values() if v is not None]
    return {
        "questions": n_questions,
        "gen_input_tokens": gen_in, "gen_output_tokens": gen_out,
        "judge_input_tokens": judge_in, "judge_output_tokens": judge_out,
        "guardrail_text_units": units,
        "parts_usd": parts,
        "total_usd": sum(known),
        "complete": len(known) == len(parts),
    }
