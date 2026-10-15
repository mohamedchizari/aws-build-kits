"""Round 1 review, findings in deploy and teardown: tests written to fail on the code as reviewed.

MAJOR 2   a corpus rebuild followed by a re-deploy left the old documents in the bucket.
MINOR 2   a bucket with versioning switched on could not be emptied.
MINOR 6   switching KB_TYPE without a teardown reused the old knowledge base and left a vector bucket.
"""
from __future__ import annotations

import json

import pytest

import fakeaws
from fakeaws import BILLS, run_script
from kitlib import config, resources


@pytest.fixture
def world(monkeypatch, tmp_path):
    fakeaws.make_corpus(tmp_path / "build", ("uc-0001", "uc-0002", "uc-0003"))
    return fakeaws.install(monkeypatch, fakeaws.World())


def state() -> dict:
    return json.loads(config.state_path().read_text(encoding="utf-8"))


def local_keys(tmp_path) -> set:
    return {"corpus/" + path.name for path in (tmp_path / "build" / "corpus").iterdir()}


# --- MAJOR 2 ------------------------------------------------------------------------------------------

def test_a_redeploy_after_a_corpus_rebuild_leaves_exactly_the_new_corpus_in_the_bucket(world, tmp_path):
    assert run_script("30_deploy_kb.py", BILLS)[0] == 0
    first_fingerprint = state()["corpus_fingerprint"]
    assert world.bucket_keys() == local_keys(tmp_path) and len(world.bucket_keys()) == 6

    # The corpus is rebuilt with another sample: uc-0001 leaves, uc-0004 and uc-0005 arrive.
    fakeaws.make_corpus(tmp_path / "build", ("uc-0002", "uc-0003", "uc-0004", "uc-0005"))
    world.log.clear()
    code, out = run_script("30_deploy_kb.py", BILLS)
    assert code == 0, out
    assert world.bucket_keys() == local_keys(tmp_path) and len(world.bucket_keys()) == 8
    assert "corpus/uc-0001.txt" not in world.bucket_keys()
    assert "removed 2 object(s) left from an earlier corpus build" in out
    assert "the bucket now holds exactly the 8 local corpus objects" in out
    saved = state()
    assert saved["stale_objects_removed"] == 2 and saved["corpus_documents"] == 4
    assert saved["corpus_fingerprint"] != first_fingerprint

    # The stale objects are gone BEFORE the sync starts, so the sync can drop them from the index.
    operations = [entry[3] for entry in world.log]
    assert operations.index("delete_objects") < operations.index("start_ingestion_job")


def test_held_out_documents_cannot_survive_a_redeploy(world, tmp_path):
    """The reviewer's scenario: first every row is deployed, then the default sample."""
    everything = tuple(f"uc-{n:04d}" for n in range(1, 31))
    fakeaws.make_corpus(tmp_path / "build", everything)
    assert run_script("30_deploy_kb.py", BILLS)[0] == 0
    sample = everything[::3]                              # 10 documents stay, 20 are now held out
    fakeaws.make_corpus(tmp_path / "build", sample)
    assert run_script("30_deploy_kb.py", BILLS)[0] == 0
    in_bucket = {key for key in world.bucket_keys() if key.endswith(".txt")}
    assert in_bucket == {f"corpus/{doc_id}.txt" for doc_id in sample}
    held_out = set(everything) - set(sample)
    assert not [doc_id for doc_id in held_out if f"corpus/{doc_id}.txt" in world.bucket_keys()]


def test_an_object_this_kit_did_not_write_stops_the_deploy_before_ingestion(world, tmp_path):
    assert run_script("30_deploy_kb.py", BILLS)[0] == 0
    bucket = next(iter(world.buckets.values()))
    bucket["objects"].append({"Key": "corpus/someone-elses-notes.txt", "VersionId": "null", "marker": False})
    world.log.clear()
    code, out = run_script("30_deploy_kb.py", BILLS)
    assert code == 1
    assert "this kit did not write" in out and "corpus/someone-elses-notes.txt" in out
    assert not world.calls("bedrock-agent", "start_ingestion_job")
    assert "corpus/someone-elses-notes.txt" in world.bucket_keys()          # it is reported, never deleted


def test_the_deploy_fingerprint_is_the_fingerprint_of_the_files_on_disk(world, tmp_path):
    assert run_script("30_deploy_kb.py", BILLS)[0] == 0
    files = resources.corpus_files(tmp_path / "build" / "corpus")
    assert state()["corpus_fingerprint"] == resources.corpus_fingerprint(files)
    (tmp_path / "build" / "corpus" / "uc-0001.txt").write_text("edited by hand\n", encoding="utf-8")
    assert state()["corpus_fingerprint"] != resources.corpus_fingerprint(files)


# --- MINOR 2 -------------------------------------------------------------------------------------------

@pytest.mark.parametrize("versioning", ["Enabled", "Suspended"])
def test_teardown_empties_a_bucket_whose_versioning_was_switched_on_after_the_upload(world, versioning):
    assert run_script("30_deploy_kb.py", BILLS)[0] == 0
    for bucket in world.buckets.values():
        bucket["versioning"] = versioning                # the objects keep their "null" version ids
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 0, out
    assert world.nothing_left()


def test_teardown_empties_a_bucket_with_real_versions_null_versions_and_delete_markers(world, tmp_path):
    assert run_script("30_deploy_kb.py", BILLS)[0] == 0
    for bucket in world.buckets.values():
        bucket["versioning"] = "Enabled"
    fakeaws.make_corpus(tmp_path / "build", ("uc-0002", "uc-0003", "uc-0004"))
    assert run_script("30_deploy_kb.py", BILLS)[0] == 0   # new versions, and a delete marker for uc-0001
    bucket = next(iter(world.buckets.values()))
    assert any(o["marker"] for o in bucket["objects"]) and any(o["VersionId"] == "null" for o in bucket["objects"])
    assert any(o["VersionId"] not in ("null",) and not o["marker"] for o in bucket["objects"])
    code, out = run_script("90_teardown.py", "--yes")
    assert code == 0, out
    assert world.nothing_left()


def test_a_bucket_that_was_never_versioned_is_emptied_without_naming_null_versions(world):
    assert run_script("30_deploy_kb.py", BILLS)[0] == 0
    world.log.clear()
    assert run_script("90_teardown.py", "--yes")[0] == 0
    deletes = world.calls("s3", "delete_objects")
    assert len(deletes) == 1                              # one round was enough
    assert all("VersionId" not in target for target in deletes[0][4]["Delete"]["Objects"])


# --- MINOR 6 -------------------------------------------------------------------------------------------

def test_switching_the_knowledge_base_type_without_a_teardown_is_refused(world):
    assert run_script("30_deploy_kb.py", BILLS)[0] == 0
    before = world.left()
    code, out = run_script("30_deploy_kb.py", BILLS, env={"KB_TYPE": "s3vectors"})
    assert code == 1
    assert "STOP" in out and "'managed'" in out and "'s3vectors'" in out and "90_teardown.py" in out
    assert world.left() == before and not world.vector_buckets          # no unused vector bucket
    assert state()["kb_type"] == "managed"


def test_the_type_of_an_existing_knowledge_base_is_checked_even_when_the_state_file_is_lost(world):
    assert run_script("30_deploy_kb.py", BILLS)[0] == 0
    config.state_path().unlink()
    code, out = run_script("30_deploy_kb.py", BILLS, env={"KB_TYPE": "s3vectors"})
    assert code == 1
    assert "already exists with type MANAGED" in out and "needs type VECTOR" in out
    assert not world.vector_buckets and not config.state_path().exists()


def test_after_a_teardown_the_other_type_can_be_deployed(world):
    assert run_script("30_deploy_kb.py", BILLS)[0] == 0
    assert run_script("90_teardown.py", "--yes")[0] == 0
    code, out = run_script("30_deploy_kb.py", BILLS, env={"KB_TYPE": "s3vectors"})
    assert code == 0, out
    assert state()["kb_type"] == "s3vectors" and world.vector_buckets
    assert [kb["type"] for kb in world.kbs.values()] == ["VECTOR"]
    code, out = run_script("90_teardown.py", "--yes", env={"KB_TYPE": "s3vectors"})
    assert code == 0 and world.nothing_left()


def test_a_deploy_that_does_not_finish_ingestion_leaves_no_corpus_fingerprint(world, tmp_path):
    """Otherwise the evaluation would accept a knowledge base whose index was never synced to the new corpus."""
    assert run_script("30_deploy_kb.py", BILLS)[0] == 0
    assert state()["corpus_fingerprint"]
    fakeaws.make_corpus(tmp_path / "build", ("uc-0002", "uc-0003", "uc-0004"))
    world.fail[("bedrock-agent", "start_ingestion_job")] = lambda: RuntimeError("ThrottlingException: slow down")
    code, out = run_script("30_deploy_kb.py", BILLS)
    assert code == 1 and "corpus_fingerprint" not in state()          # the bucket changed, the index did not
    world.fail.clear()
    assert run_script("30_deploy_kb.py", BILLS)[0] == 0
    files = resources.corpus_files(tmp_path / "build" / "corpus")
    assert state()["corpus_fingerprint"] == resources.corpus_fingerprint(files)
