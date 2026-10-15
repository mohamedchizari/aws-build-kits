"""Round 4, what the money reader and the emulator run found in kit B: tests written to fail on the code as reviewed.

MONEY MINOR 15   a deploy killed right after CreateKnowledgeBase or CreateDataSource left a state file that did
                 not name the knowledge base or the data source (the teardown still found them by name).
EMULATOR 1       when the answer to CreateKnowledgeBase was lost and the SDK sent the call again, the deploy
                 stopped with "already exists" and said "Whatever was created so far is recorded in .state.json",
                 which was not true for the knowledge base.
MONEY            .gitignore did not cover a hand copy of the state file (.state.json.bak), and the STOP message for a
                 damaged state file printed its full local path, which can carry a user name.
EMULATOR 4       10_build_corpus.py ended in a 40-line traceback when the download failed.
"""
from __future__ import annotations

import importlib.util
import json
import urllib.error
from pathlib import Path

import pytest

import fakeaws
from conftest import KIT_DIR
from fakeaws import BILLS, run_script
from kitlib import config
from kitlib import state as state_mod
from test_review_r2_state import result_line, write_eval_build


@pytest.fixture
def world(monkeypatch, tmp_path):
    fakeaws.make_corpus(tmp_path / "build")
    return fakeaws.install(monkeypatch, fakeaws.World())


def die_right_after(method: str, seen: dict):
    """Patch one fake AWS call: do it, keep the state file as it is at that moment, then die."""
    original = getattr(fakeaws.FakeClient, method)

    def call_then_die(self, **params):
        result = original(self, **params)
        seen["state"] = json.loads(config.state_path().read_text(encoding="utf-8"))
        seen["result"] = result
        raise RuntimeError("the process died right after the call")

    setattr(fakeaws.FakeClient, method, call_then_die)
    return original


def saved_state() -> dict:
    return json.loads(config.state_path().read_text(encoding="utf-8"))


# --- MONEY MINOR 15, EMULATOR 1 -----------------------------------------------------------------------------------------

def test_the_knowledge_base_is_on_record_before_the_call_that_creates_it(world, tmp_path):
    seen: dict = {}
    original = die_right_after("_bedrock_agent__create_knowledge_base", seen)
    try:
        code, out = run_script("30_deploy_kb.py", BILLS, "--skip-smoke-test")
    finally:
        fakeaws.FakeClient._bedrock_agent__create_knowledge_base = original
    assert code == 1 and world.left()["knowledge_bases"]                  # it exists, and the script died
    recorded = seen["state"]
    assert recorded["knowledge_base_name"] == "kitdemo-fedrag-kb" and recorded["knowledge_base_id"] == state_mod.PENDING
    assert "knowledge_base_id" in state_mod.recorded_resources(recorded)
    assert "Whatever was created so far is recorded in .state.json" in out          # and now that is true

    # the evaluation does not take the placeholder for an id
    write_eval_build(tmp_path)
    code, out = run_script("50_run_eval.py", BILLS)
    assert code == 1 and "30_deploy_kb.py was started and did not finish" in out
    assert not world.calls("bedrock-agent-runtime") and not world.calls("bedrock-runtime")

    # the clean check does not pass, and a plain teardown removes it and clears the record
    code, out = run_script("99_verify_clean.py")
    assert code != 0 and "NOT CLEAN" in result_line(out)
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 0 and world.nothing_left(), out
    assert not state_mod.has_record(saved_state())


def test_the_data_source_is_on_record_before_the_call_that_creates_it(world):
    seen: dict = {}
    original = die_right_after("_bedrock_agent__create_data_source", seen)
    try:
        code, out = run_script("30_deploy_kb.py", BILLS, "--skip-smoke-test")
    finally:
        fakeaws.FakeClient._bedrock_agent__create_data_source = original
    assert code == 1
    recorded = seen["state"]
    assert recorded["data_source_name"] == "kitdemo-fedrag-s3-source" and recorded["data_source_id"] == state_mod.PENDING
    assert recorded["knowledge_base_id"] not in (None, state_mod.PENDING)          # its own id was known by then
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 0 and world.nothing_left(), out
    assert not state_mod.has_record(saved_state())


def test_a_deploy_that_is_run_again_replaces_the_placeholders_with_the_ids(world):
    seen: dict = {}
    original = die_right_after("_bedrock_agent__create_knowledge_base", seen)
    try:
        assert run_script("30_deploy_kb.py", BILLS, "--skip-smoke-test")[0] == 1
    finally:
        fakeaws.FakeClient._bedrock_agent__create_knowledge_base = original
    code, out = run_script("30_deploy_kb.py", BILLS, "--skip-smoke-test")
    assert code == 0, out
    saved = saved_state()
    assert state_mod.PENDING not in (saved["knowledge_base_id"], saved["data_source_id"])
    assert saved["data_source_name"] == "kitdemo-fedrag-s3-source"
    assert len(world.left()["knowledge_bases"]) == 1


def test_a_placeholder_for_something_that_was_never_created_is_cleared_by_teardown(world):
    """The call itself failed: nothing exists, the record says "not known yet"."""
    original = fakeaws.FakeClient._bedrock_agent__create_knowledge_base

    def refuse(self, **params):
        raise RuntimeError("AccessDeniedException: not allowed to create a knowledge base")

    fakeaws.FakeClient._bedrock_agent__create_knowledge_base = refuse
    try:
        assert run_script("30_deploy_kb.py", BILLS, "--skip-smoke-test")[0] == 1
    finally:
        fakeaws.FakeClient._bedrock_agent__create_knowledge_base = original
    assert saved_state()["knowledge_base_id"] == state_mod.PENDING and not world.left()["knowledge_bases"]
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 0 and world.nothing_left(), out
    assert not state_mod.has_record(saved_state())


# --- MONEY: the state file's copies and its path ---------------------------------------------------------------------------

def test_gitignore_covers_a_hand_copy_of_the_state_file():
    lines = (KIT_DIR / ".gitignore").read_text(encoding="utf-8").split()
    assert ".state.json*" in lines and "*.state.json" in lines and "*state*.json.bak" in lines
    import fnmatch
    for name in (".state.json", ".state.json.tmp", ".state.json.bak", ".state.json.old", ".state.json~", "copy.state.json",
                 "kit_b.state.json", "old-state.json.bak"):
        assert any(fnmatch.fnmatch(name, pattern) for pattern in lines), name


def test_the_stop_message_for_a_damaged_state_file_does_not_print_the_home_folder(world, monkeypatch, tmp_path):
    home = tmp_path / "home" / "some.user.name"
    (home / "work").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("KIT_STATE_FILE", str(home / "work" / "state.json"))
    (home / "work" / "state.json").write_text('{"account_id": "1111', encoding="utf-8")
    code, out = run_script("99_verify_clean.py")
    assert code != 0 and "STOP: the state file ~/work/state.json exists but cannot be read" in out
    assert "some.user.name" not in out
    assert config.shown_path(KIT_DIR / ".state.json") == ".state.json"              # in the kit folder: the name alone
    assert config.shown_path(Path("/srv/elsewhere/state.json")) == "/srv/elsewhere/state.json"


# --- EMULATOR 4 --------------------------------------------------------------------------------------------------------

def test_a_failed_download_is_one_message_and_names_the_way_out(monkeypatch, tmp_path, capsys):
    spec = importlib.util.spec_from_file_location("build_corpus_r4", KIT_DIR / "10_build_corpus.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("KIT_BUILD_DIR", str(tmp_path / "build"))

    def no_network(*args, **kwargs):
        raise urllib.error.URLError("[Errno 111] Connection refused")

    monkeypatch.setattr(module.urllib.request, "urlopen", no_network)
    code = module.main([])
    captured = capsys.readouterr()
    assert code == 1 and "Traceback" not in captured.err + captured.out
    assert "ERROR: could not download the inventory CSV" in captured.err and "--csv" in captured.err
    assert "Nothing was built" in captured.err and not (tmp_path / "build" / "corpus_manifest.json").exists()
