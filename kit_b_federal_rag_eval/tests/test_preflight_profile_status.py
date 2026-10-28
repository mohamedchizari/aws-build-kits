from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "00_check.py"
SPEC = importlib.util.spec_from_file_location("kit_b_preflight_check", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
check = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check)


def test_inference_profile_preflight_requires_active_status(monkeypatch):
    class Aws:
        dry_run = False

    for status, expected_ok in (("ACTIVE", True), ("FAILED", False), (None, False)):
        monkeypatch.setattr(check.api, "get_inference_profile", lambda *_args, **_kwargs: {"status": status})
        ok, lines = check.check_model(Aws(), "Generation model", "us.amazon.nova-micro-v1:0")
        assert ok is expected_ok
        assert any(f"inference profile status: {status}" in line for line in lines)
        if not expected_ok:
            assert any("inference profile is not ACTIVE" in line for line in lines)
