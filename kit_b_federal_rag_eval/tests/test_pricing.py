"""Cost arithmetic. The price constants themselves are quoted in kitlib/pricing.py with their sources."""
from __future__ import annotations

import math

from kitlib import pricing


def test_opensearch_floor_is_two_ocu_around_the_clock():
    assert math.isclose(pricing.opensearch_classic_floor_per_day(), 11.52)
    assert math.isclose(pricing.opensearch_classic_floor_per_day() * 30, 345.60)


def test_token_cost_per_million():
    assert math.isclose(pricing.token_cost(1_000_000, 1_000_000, (0.06, 0.24)), 0.30)
    assert math.isclose(pricing.token_cost(183_000, 4_800, pricing.MODEL_PRICES_PER_1M["amazon.nova-lite-v1:0"]),
                        183_000 * 0.06 / 1e6 + 4_800 * 0.24 / 1e6)
    assert pricing.token_cost(10, 10, None) is None


def test_grounding_units_round_up_per_thousand_characters():
    assert pricing.grounding_text_units(0, 0, 1) == 1
    assert pricing.grounding_text_units(900, 50, 50) == 1
    assert pricing.grounding_text_units(900, 50, 51) == 2
    assert pricing.grounding_text_units(5000, 200, 200) == 6
    assert math.isclose(pricing.guardrail_cost(1000), 0.10)
    assert math.isclose(pricing.guardrail_cost(720), 0.072)


def test_retrieve_cost_by_knowledge_base_type():
    assert math.isclose(pricing.retrieve_cost(1000, "managed"), 1.00)
    assert math.isclose(pricing.retrieve_cost(120, "managed"), 0.12)
    assert pricing.retrieve_cost(120, "s3vectors") < 0.001


def test_model_price_table_and_overrides(monkeypatch):
    assert pricing.model_price("amazon.nova-pro-v1:0", "JUDGE") == (0.80, 3.20)
    assert pricing.model_price("some.unknown-model-v1:0", "GEN") is None
    monkeypatch.setenv("PRICE_GEN_INPUT_PER_1M", "2.5")
    monkeypatch.setenv("PRICE_GEN_OUTPUT_PER_1M", "10")
    assert pricing.model_price("some.unknown-model-v1:0", "GEN") == (2.5, 10.0)
    assert pricing.model_price("some.unknown-model-v1:0", "JUDGE") is None


def test_run_estimate_adds_up_and_flags_missing_prices():
    est = pricing.estimate_eval_run(120, 5, 920, "amazon.nova-lite-v1:0", "amazon.nova-pro-v1:0", "managed")
    assert est["complete"] is True
    assert math.isclose(est["total_usd"], sum(est["parts_usd"].values()))
    assert est["guardrail_text_units"] == 120 * 5      # ceil((4600 + 200 + 200) / 1000) = 5 per question
    assert math.isclose(est["parts_usd"]["retrieve_calls"], 0.12)
    assert 0.05 < est["total_usd"] < 1.00
    unknown = pricing.estimate_eval_run(120, 5, 920, "x.unknown-v1:0", "amazon.nova-pro-v1:0", "managed")
    assert unknown["complete"] is False and unknown["parts_usd"]["generation"] is None


def test_fmt_usd_keeps_the_third_decimal_only_when_needed():
    assert [pricing.fmt_usd(v) for v in (0.06, 0.8, 0.035, 3.2, 1.1, 5)] == [
        "$0.06", "$0.80", "$0.035", "$3.20", "$1.10", "$5.00"]
