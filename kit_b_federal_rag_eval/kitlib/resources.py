"""Create, find and delete the kit's AWS resources.

All AWS calls go through kitlib.aws, where each one carries its doc URL.
Existing resources are found by LISTING and matching names, never by relying
on a particular error code, so re-running a step is safe and a lost
.state.json does not hide anything.

The state file is trusted only for the place it names. deploy() and
create_guardrail() refuse to run when .state.json records a deploy in another
account, Region or prefix (kitlib.state.require_same_place); the teardown and
clean-check scripts do the same before they call anything here.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

from . import aws as api
from . import config
from . import state as state_mod

KB_WAIT_S = 900
INGEST_WAIT_S = 3600
DELETE_WAIT_S = 1200
# UNVERIFIED: how long a new IAM role needs before Bedrock can assume it.
# The AWS sample utils/managed_knowledge_base.py sleeps 10 seconds.
IAM_PROPAGATION_S = 15

# Every name this kit builds is "<prefix>-fedrag-<something>" (kitlib.config.Names), so a name
# that contains this marker is this kit's whatever the prefix was when it was created.
KIT_MARKER = "-fedrag-"


def _try(found: dict, label: str, fn):
    """Run one listing call; record a failure instead of hiding it."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - reported to the user, never swallowed silently
        found["errors"].append(f"{label}: {type(exc).__name__}: {exc}"[:300])
        return None


ALL_KINDS = ("buckets", "roles", "knowledge_bases", "guardrails", "vectors")


def discover(aws: api.Aws, name_prefix: str = "", kinds: tuple[str, ...] = ALL_KINDS,
             children: bool = True) -> dict:
    """List every resource of the kinds this kit creates whose name starts with name_prefix.

    name_prefix "" means every name. `kinds` limits which services are asked, so a step does
    not fail on a listing it does not need (for example S3 Vectors when the knowledge base is
    the managed type). `children` False skips the per-knowledge-base and per-vector-bucket
    listings. found["listed"] names the kinds whose listing succeeded: an empty list for a
    kind is proof of absence only when the kind is in there.
    """
    found: dict = {"buckets": [], "roles": [], "knowledge_bases": [], "data_sources": [],
                   "guardrails": [], "vector_buckets": [], "vector_indexes": [], "errors": [], "listed": set()}

    def listing(kind: str, label: str, fn) -> list:
        if kind not in kinds:
            return []
        result = _try(found, label, fn)
        if result is None:
            return []
        found["listed"].add(kind)
        return result

    found["buckets"] = [b["Name"] for b in listing("buckets", "S3 buckets", lambda: api.list_buckets(aws, name_prefix))]
    found["roles"] = [{"name": r["RoleName"], "arn": r.get("Arn")}
                      for r in listing("roles", "IAM roles", lambda: api.list_roles(aws))
                      if r.get("RoleName", "").startswith(name_prefix)]
    for kb in listing("knowledge_bases", "knowledge bases", lambda: api.list_knowledge_bases(aws)):
        if not kb.get("name", "").startswith(name_prefix):
            continue
        found["knowledge_bases"].append(
            {"id": kb["knowledgeBaseId"], "name": kb["name"], "status": kb.get("status")})
        if children:
            found["data_sources"] += data_sources_of(aws, kb["knowledgeBaseId"], found) or []
    found["guardrails"] = [{"id": g["id"], "name": g["name"], "arn": g.get("arn"), "status": g.get("status")}
                           for g in listing("guardrails", "guardrails", lambda: api.list_guardrails(aws))
                           if g.get("name", "").startswith(name_prefix)]
    for vb in listing("vectors", "S3 vector buckets", lambda: api.list_vector_buckets(aws, name_prefix)):
        found["vector_buckets"].append({"name": vb["vectorBucketName"], "arn": vb.get("vectorBucketArn")})
        if children:
            found["vector_indexes"] += vector_indexes_of(aws, vb["vectorBucketName"], found) or []
    return found


def data_sources_of(aws: api.Aws, kb_id: str, found: dict) -> list | None:
    """Data sources of one knowledge base, or None (with the error recorded) if they cannot be listed."""
    listed = _try(found, f"data sources of {kb_id}", lambda: api.list_data_sources(aws, kb_id))
    if listed is None:
        return None
    return [{"knowledge_base_id": kb_id, "id": ds["dataSourceId"], "name": ds.get("name"),
             "status": ds.get("status")} for ds in listed]


def vector_indexes_of(aws: api.Aws, vector_bucket: str, found: dict) -> list | None:
    listed = _try(found, f"vector indexes of {vector_bucket}", lambda: api.list_vector_indexes(aws, vector_bucket))
    if listed is None:
        return None
    return [{"vector_bucket": vector_bucket, "name": index["indexName"], "arn": index.get("indexArn")}
            for index in listed]


def corpus_files(corpus_dir: Path) -> list[Path]:
    """Documents and their sidecars, nothing else."""
    docs = sorted(corpus_dir.glob("uc-*.txt"))
    sidecars = sorted(corpus_dir.glob("uc-*.txt.metadata.json"))
    return docs + sidecars


def corpus_fingerprint(files: list[Path]) -> str:
    """One SHA-256 over the names and contents of the corpus files, in name order.

    It is stored in .state.json at deploy time and compared by 50_run_eval.py, so an
    evaluation cannot silently run against a knowledge base built from another corpus.
    """
    from . import corpus
    return corpus.fingerprint({path.name: path.read_bytes() for path in files})


KIT_CORPUS_KEY = re.compile(r"uc-\d{4,}\.txt(\.metadata\.json)?")


def _wait(aws: api.Aws, check, describe: str, timeout_s: int, echo, sleep):
    if aws.dry_run:
        return check()
    return api.wait_until(check, describe, timeout_s=timeout_s, interval_s=10, sleep=sleep, echo=echo)


def _is_role_propagation_error(exc: Exception) -> bool:
    # UNVERIFIED: the error Bedrock returns while a brand-new role is not yet assumable.
    # This matches on words in the message, so an unrelated error is never retried for long:
    # at most 5 retries, 10 seconds apart, then the error is raised.
    text = str(exc).lower()
    return "role" in text and any(word in text for word in ("assume", "trust", "not authorized", "permission"))


def deploy(aws: api.Aws, settings: config.Settings, corpus_dir: Path, echo=print, sleep=time.sleep) -> dict:
    """Bucket, documents, role, [vector store], knowledge base, data source, ingestion."""
    identity = api.get_caller_identity(aws)
    account = identity["Account"]
    names = config.Names(settings.prefix, account, settings.region)
    recorded = config.load_state()
    # A second deploy must never overwrite the record of a first one that still exists.
    state_mod.require_same_place(recorded, settings, None if aws.dry_run else account, "The deploy")
    wanted_type = "MANAGED" if settings.kb_type == "managed" else "VECTOR"
    switch_advice = ("A knowledge base cannot change type. Run 90_teardown.py with the old KB_TYPE first, "
                     "then deploy again with the new one.")
    if state_mod.has_record(recorded) and recorded.get("kb_type") not in (None, settings.kb_type):
        raise state_mod.StopHere(
            f"STOP: .state.json records a knowledge base of type '{recorded['kb_type']}', but KB_TYPE is now "
            f"'{settings.kb_type}'. Nothing was changed. {switch_advice}")
    state = {} if aws.dry_run else dict(recorded)

    def remember(**changes):
        state.update(changes)
        if not aws.dry_run:
            config.update_state(**changes)

    kinds = ("buckets", "roles", "knowledge_bases") + (("vectors",) if settings.kb_type == "s3vectors" else ())
    found = discover(aws, names.stem, kinds)
    if found["errors"]:
        raise RuntimeError("could not list existing resources, so it is not safe to create new ones: "
                           + "; ".join(found["errors"]))
    kbs = {kb["name"]: kb for kb in found["knowledge_bases"]}
    if names.knowledge_base in kbs:
        # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent_KnowledgeBaseConfiguration.html
        # (read 2026-10-07): type is VECTOR | KENDRA | SQL | MANAGED. Checked before anything is
        # created, so a changed KB_TYPE cannot leave an unused vector bucket behind a reused knowledge base.
        existing = api.get_knowledge_base(aws, kbs[names.knowledge_base]["id"])
        actual_type = (existing.get("knowledgeBaseConfiguration") or {}).get("type")
        if actual_type and actual_type != wanted_type:
            raise state_mod.StopHere(
                f"STOP: the knowledge base {names.knowledge_base} already exists with type {actual_type}, but "
                f"KB_TYPE={settings.kb_type} needs type {wanted_type}. Nothing was changed. {switch_advice}")
    remember(**state_mod.start_record(recorded, settings, account), kb_type=settings.kb_type)

    # Resources with a fixed name are recorded BEFORE the call that creates them, so a crash
    # between the two cannot leave something that exists but is not on record. A record of
    # something that was never created is harmless: teardown confirms it absent and clears it.
    echo(f"[1/7] S3 bucket {names.bucket}")
    bucket_existed = names.bucket in found["buckets"]
    remember(bucket=names.bucket)
    if bucket_existed:
        echo("      exists already, reusing it")
    else:
        api.create_bucket(aws, names.bucket)
    api.put_bucket_tagging(aws, names.bucket, config.tags_list_upper())

    files = corpus_files(corpus_dir)
    wanted_keys = {names.corpus_prefix + path.name for path in files}
    echo(f"[2/7] Uploading {len(files)} objects to s3://{names.bucket}/{names.corpus_prefix}")
    if not files and not aws.dry_run:
        raise RuntimeError(f"no corpus files in {corpus_dir}. Run 10_build_corpus.py first.")
    removed = 0
    # The fingerprint of the deployed corpus is taken off the record before the bucket is touched
    # and written back only after the ingestion job completes. A deploy that stops anywhere in
    # between leaves no fingerprint, and 50_run_eval.py refuses to run without one.
    fingerprint = corpus_fingerprint(files)
    remember(corpus_fingerprint=None)
    if bucket_existed:
        # The data source ingests everything under corpus/. Objects left from an earlier corpus
        # build would stay in the knowledge base, and a question that is meant to have no answer
        # could then have one. So the prefix is made to hold exactly the local corpus.
        left_over = sorted(set(api.list_object_keys(aws, names.bucket, names.corpus_prefix)) - wanted_keys)
        foreign = [key for key in left_over
                   if not KIT_CORPUS_KEY.fullmatch(key[len(names.corpus_prefix):])]
        if foreign and not aws.dry_run:
            raise RuntimeError(
                f"the bucket holds {len(foreign)} object(s) under {names.corpus_prefix} that this kit did not "
                f"write (first: {foreign[0]}). The data source would ingest them. Remove them, or run "
                "90_teardown.py and deploy again.")
        if left_over and not aws.dry_run:
            removed = api.delete_object_keys(aws, names.bucket, left_over)
            stale_documents = sum(1 for key in left_over if key.endswith(".txt"))
            echo(f"      removed {removed} object(s) left from an earlier corpus build "
                 f"({stale_documents} document(s) and their metadata files); the sync below drops them "
                 "from the knowledge base")
    for position, path in enumerate(files):
        aws.quiet_dry_run = position >= 2  # show two example calls, then stay quiet
        content_type = "application/json" if path.name.endswith(".json") else "text/plain; charset=utf-8"
        api.put_object(aws, names.bucket, names.corpus_prefix + path.name, path.read_bytes(), content_type)
        if not aws.dry_run and (position + 1) % 200 == 0:
            echo(f"      {position + 1} uploaded")
    aws.quiet_dry_run = False
    if aws.dry_run:
        if files:
            echo(f"DRY-RUN ... and {max(0, len(files) - 2)} more s3.put_object calls like these")
        else:
            echo("DRY-RUN corpus not built yet: one s3.put_object per document and one per sidecar")
    else:
        in_bucket = set(api.list_object_keys(aws, names.bucket, names.corpus_prefix))
        if in_bucket != wanted_keys:
            raise RuntimeError(
                f"after the upload the bucket holds {len(in_bucket)} object(s) under {names.corpus_prefix} but "
                f"the local corpus has {len(wanted_keys)}: {len(in_bucket - wanted_keys)} extra, "
                f"{len(wanted_keys - in_bucket)} missing. Not starting ingestion.")
        echo(f"      the bucket now holds exactly the {len(wanted_keys)} local corpus objects")
    remember(objects_uploaded=len(files), stale_objects_removed=removed,
             corpus_documents=sum(1 for path in files if path.name.endswith(".txt")))

    vector_bucket_arn = vector_index_arn = ""
    if settings.kb_type == "s3vectors":
        echo(f"[3/7] S3 vector bucket {names.vector_bucket} and index {names.vector_index}")
        existing = {vb["name"]: vb for vb in found["vector_buckets"]}
        remember(vector_bucket=names.vector_bucket)
        if names.vector_bucket in existing:
            vector_bucket_arn = existing[names.vector_bucket]["arn"]
        else:
            vector_bucket_arn = api.create_vector_bucket(aws, names.vector_bucket, config.tags_map())["vectorBucketArn"]
        remember(vector_bucket=names.vector_bucket, vector_bucket_arn=vector_bucket_arn)
        indexes = {i["name"]: i for i in found["vector_indexes"] if i["vector_bucket"] == names.vector_bucket}
        remember(vector_index=names.vector_index)
        if names.vector_index in indexes:
            vector_index_arn = indexes[names.vector_index]["arn"]
        else:
            vector_index_arn = api.create_vector_index(aws, names.vector_bucket, names.vector_index,
                                                       settings.embed_dimensions, config.tags_map())["indexArn"]
        remember(vector_index=names.vector_index, vector_index_arn=vector_index_arn)
    else:
        echo("[3/7] No vector store to create: the knowledge base is the managed type")

    echo(f"[4/7] IAM role {names.role}")
    roles = {r["name"]: r for r in found["roles"]}
    role_is_new = names.role not in roles
    remember(role_name=names.role)
    if role_is_new:
        role_arn = api.create_role(aws, names.role, api.kb_trust_policy(account, settings.region),
                                   config.tags_list_upper())["Role"]["Arn"]
    else:
        role_arn = roles[names.role]["arn"]
        echo("      exists already, reusing it")
    api.put_role_policy(aws, names.role, names.role_policy, api.kb_permissions_policy(
        account, settings.region, names.bucket, settings.kb_type, settings.embed_model_id, vector_index_arn))
    remember(role_name=names.role, role_arn=role_arn)
    if role_is_new and not aws.dry_run:
        echo(f"      waiting {IAM_PROPAGATION_S}s for the new role to become usable")
        sleep(IAM_PROPAGATION_S)

    echo(f"[5/7] Knowledge base {names.knowledge_base} (type: {settings.kb_type})")
    if names.knowledge_base in kbs:
        kb_id = kbs[names.knowledge_base]["id"]
        echo(f"      exists already ({kb_id}), reusing it")
    else:
        def create():
            if settings.kb_type == "managed":
                return api.create_managed_knowledge_base(aws, names.knowledge_base, role_arn, config.tags_map())
            embed_arn = f"arn:aws:bedrock:{settings.region}::foundation-model/{settings.embed_model_id}"
            return api.create_s3vectors_knowledge_base(
                aws, names.knowledge_base, role_arn, embed_arn, settings.embed_dimensions,
                vector_bucket_arn, vector_index_arn, config.tags_map())

        # Round 4: the fixed name goes on record BEFORE the call that creates the knowledge base (its id is
        # not known yet), as for the bucket, the role and the guardrail. A process killed right after the
        # call, or an answer that was lost on the way, then leaves a record that names it. Teardown and
        # the clean check go by the name; a record of something never created is cleared by teardown.
        remember(knowledge_base_id=state_mod.PENDING, knowledge_base_name=names.knowledge_base)
        kb = None
        for attempt in range(6):
            try:
                kb = create()
                break
            except Exception as exc:  # noqa: BLE001
                if attempt == 5 or not _is_role_propagation_error(exc):
                    raise
                echo(f"      the role is not usable yet ({api.error_code(exc) or type(exc).__name__}); retrying in 10s")
                sleep(10)
        kb_id = kb["knowledgeBaseId"]
        # The time of creation, by this computer's clock, so that 90_teardown.py can print how long the
        # knowledge base existed. A re-run that reuses the knowledge base keeps the first time.
        remember(knowledge_base_arn=kb.get("knowledgeBaseArn"), knowledge_base_created_at=state_mod.now())
    remember(knowledge_base_id=kb_id, knowledge_base_name=names.knowledge_base)

    def kb_ready():
        current = api.get_knowledge_base(aws, kb_id)
        if current.get("status") == "FAILED":
            raise RuntimeError(f"knowledge base creation FAILED: {current.get('failureReasons')}")
        return current if current.get("status") == "ACTIVE" else None

    _wait(aws, kb_ready, "the knowledge base to become ACTIVE", KB_WAIT_S, echo, sleep)

    echo(f"[6/7] Data source {names.data_source}")
    sources = {ds["name"]: ds for ds in found["data_sources"] if ds["knowledge_base_id"] == kb_id}
    if names.data_source in sources:
        ds_id = sources[names.data_source]["id"]
        echo(f"      exists already ({ds_id}), reusing it")
    elif settings.kb_type == "managed":
        remember(data_source_id=state_mod.PENDING, data_source_name=names.data_source)     # before the call, as above
        ds_id = api.create_managed_s3_data_source(aws, kb_id, names.data_source, names.bucket, account,
                                                  names.corpus_prefix)["dataSourceId"]
    else:
        remember(data_source_id=state_mod.PENDING, data_source_name=names.data_source)
        ds_id = api.create_vector_s3_data_source(aws, kb_id, names.data_source, names.bucket, account,
                                                 names.corpus_prefix)["dataSourceId"]
    remember(data_source_id=ds_id, data_source_name=names.data_source)

    def source_ready():
        for ds in api.list_data_sources(aws, kb_id):
            if ds.get("dataSourceId") == ds_id:
                if ds.get("status") == "FAILED":
                    raise RuntimeError("the data source is in status FAILED")
                return ds.get("status") == "AVAILABLE"
        return aws.dry_run

    _wait(aws, source_ready, "the data source to become AVAILABLE", 600, echo, sleep)

    echo("[7/7] Ingestion job (parse, chunk, embed, index)")
    job = api.start_ingestion_job(aws, kb_id, ds_id)
    job_id = job["ingestionJobId"]

    def ingestion_done():
        current = api.get_ingestion_job(aws, kb_id, ds_id, job_id)
        return current if current.get("status") in ("COMPLETE", "FAILED", "STOPPED") else None

    final = _wait(aws, ingestion_done, "the ingestion job to finish", INGEST_WAIT_S, echo, sleep) or job
    stats = final.get("statistics") or {}
    remember(ingestion={"job_id": job_id, "status": final.get("status"), "statistics": stats,
                        "failure_reasons": final.get("failureReasons")})
    echo(f"      status: {final.get('status')}")
    for key in sorted(stats):
        echo(f"      {key}: {stats[key]}")
    if final.get("status") != "COMPLETE" and not aws.dry_run:
        raise RuntimeError(f"ingestion ended as {final.get('status')}: {final.get('failureReasons')}")
    remember(corpus_fingerprint=fingerprint)       # only now is the knowledge base known to hold this corpus
    return state


def smoke_retrieve(aws: api.Aws, settings: config.Settings, kb_id: str, echo=print) -> None:
    """Two Retrieve calls so you see retrieval and a metadata filter work."""
    query = "chatbot that answers questions from the public"
    plain = api.parse_retrieve_response(api.retrieve(aws, kb_id, settings.kb_type, query, 3))
    echo(f'      "{query}" -> {[p.doc_id for p in plain]}')
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_agent-runtime_Retrieve.html (read 2026-10-07)
    # The filter uses the development_stage attribute from the metadata sidecars.
    stage_filter = {"equals": {"key": "development_stage", "value": "Deployed"}}
    filtered = api.parse_retrieve_response(api.retrieve(aws, kb_id, settings.kb_type, query, 3, stage_filter))
    echo(f"      same query, filter development_stage = Deployed -> {[p.doc_id for p in filtered]}")


def create_guardrail(aws: api.Aws, settings: config.Settings, echo=print, sleep=time.sleep) -> dict:
    identity = api.get_caller_identity(aws)
    account = identity["Account"]
    names = config.Names(settings.prefix, account, settings.region)
    recorded = config.load_state()
    state_mod.require_same_place(recorded, settings, None if aws.dry_run else account, "Creating the guardrail")
    place = state_mod.start_record(recorded, settings, account)
    existing = [g for g in api.list_guardrails(aws) if g.get("name") == names.guardrail]
    if existing:
        guardrail_id = existing[0]["id"]
        guardrail_arn = existing[0].get("arn")
        echo(f"Guardrail {names.guardrail} exists already ({guardrail_id}). Its thresholds are NOT changed "
             "by this run; to change them, delete it with 90_teardown.py first.")
        saved = recorded if not aws.dry_run else {}
        if saved.get("guardrail_id") == guardrail_id and saved.get("guardrail_version"):
            echo(f"Reusing version {saved['guardrail_version']} recorded in .state.json")
            return saved
    else:
        # The place and the guardrail's fixed name go on record BEFORE the call that creates it (its id
        # is not known yet), so a crash right after the call cannot leave a guardrail nothing records.
        # Teardown finds it by the name; a record of something never created is cleared by teardown.
        if not aws.dry_run and not recorded.get("guardrail_id"):
            config.update_state(**place, guardrail_id=state_mod.PENDING, guardrail_name=names.guardrail)
        created = api.create_grounding_guardrail(aws, names.guardrail, settings.grounding_threshold,
                                                 settings.relevance_threshold, config.tags_list_lower())
        guardrail_id, guardrail_arn = created["guardrailId"], created.get("guardrailArn")
        echo(f"Created guardrail {names.guardrail} ({guardrail_id}), working draft")
    if not aws.dry_run:
        config.update_state(**place, guardrail_id=guardrail_id, guardrail_arn=guardrail_arn,
                            guardrail_name=names.guardrail)

    def ready(version=None):
        current = api.get_guardrail(aws, guardrail_id, version)
        if current.get("status") == "FAILED":
            raise RuntimeError(f"guardrail is FAILED: {current.get('statusReasons')}")
        return current if current.get("status") == "READY" else None

    _wait(aws, ready, "the guardrail draft to be READY", 300, echo, sleep)
    version = api.create_guardrail_version(aws, guardrail_id)["version"]
    described = _wait(aws, lambda: ready(version), f"guardrail version {version} to be READY", 300, echo, sleep)
    # The thresholds that go on record (and from there into the results table) are the ones the
    # guardrail reports, not the ones in the settings: a guardrail that existed already keeps its own.
    # DOC: https://docs.aws.amazon.com/bedrock/latest/APIReference/API_GetGuardrail.html (read 2026-10-07)
    # contextualGroundingPolicy.filters[] carries type and threshold.
    reported = {f.get("type"): f.get("threshold") for f in
                ((described if isinstance(described, dict) else {}).get("contextualGroundingPolicy") or {})
                .get("filters") or []}
    thresholds = {"grounding_threshold": reported.get("GROUNDING", settings.grounding_threshold),
                  "relevance_threshold": reported.get("RELEVANCE", settings.relevance_threshold)}
    for label, key, wanted in (("grounding", "grounding_threshold", settings.grounding_threshold),
                               ("relevance", "relevance_threshold", settings.relevance_threshold)):
        if thresholds[key] != wanted:
            echo(f"NOTE: the guardrail's {label} threshold is {thresholds[key]}, not the {wanted} in your "
                 "settings. The guardrail's own value is recorded and used.")
    result = {"guardrail_id": guardrail_id, "guardrail_arn": guardrail_arn,
              "guardrail_version": version, "guardrail_name": names.guardrail, **thresholds}
    if not aws.dry_run:
        config.update_state(**result)
    echo(f"Guardrail version {version} is ready")
    return result


def teardown(aws: api.Aws, settings: config.Settings, state: dict, echo=print, sleep=time.sleep) -> list[str]:
    """Delete everything this kit created, each thing separately. Returns a list of failures.

    The caller (90_teardown.py) has already checked that `state` describes the account, Region
    and prefix in use, so the fixed names below and the ids in `state` are in the same place.
    A clean return here is not yet a reason to forget anything: see confirm_gone().
    """
    account = api.get_caller_identity(aws)["Account"]
    names = config.Names(settings.prefix, account, settings.region)
    failures: list[str] = []
    found = discover(aws, names.stem)
    for error in found["errors"]:
        failures.append(f"could not list: {error}")

    def stage(title: str, fn) -> bool:
        echo(title)
        try:
            fn()
            return True
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{title}: {type(exc).__name__}: {exc}"[:400])
            echo(f"      FAILED: {exc}")
            return False

    # by the fixed name or by the recorded id (the id may be the "not known yet" placeholder: then by the name)
    kb_targets = [kb for kb in found["knowledge_bases"]
                  if kb["name"] == names.knowledge_base or kb["id"] == state.get("knowledge_base_id")]

    def delete_knowledge_bases():
        for kb in kb_targets:
            sources = [ds for ds in found["data_sources"] if ds["knowledge_base_id"] == kb["id"]]
            for ds in sources:
                echo(f"      deleting data source {ds['id']} of knowledge base {kb['id']}")
                api.delete_data_source(aws, kb["id"], ds["id"])

            def sources_gone():
                left = api.list_data_sources(aws, kb["id"])
                stuck = [d for d in left if d.get("status") == "DELETE_UNSUCCESSFUL"]
                if stuck:
                    raise RuntimeError(f"data source deletion was unsuccessful: {stuck}. "
                                       "Check that the knowledge base role still exists, then retry.")
                return not left

            if sources:
                _wait(aws, sources_gone, "the data sources to be deleted", DELETE_WAIT_S, echo, sleep)
            echo(f"      deleting knowledge base {kb['id']}")
            api.delete_knowledge_base(aws, kb["id"])
            _wait(aws, lambda: kb["id"] not in [k["knowledgeBaseId"] for k in api.list_knowledge_bases(aws)],
                  "the knowledge base to be deleted", DELETE_WAIT_S, echo, sleep)

    def delete_guardrails():
        targets = [g for g in found["guardrails"]
                   if g["name"] == names.guardrail or g["id"] == state.get("guardrail_id")]
        for g in targets:
            echo(f"      deleting guardrail {g['id']} and all its versions")
            api.delete_guardrail(aws, g["id"])
            _wait(aws, lambda: g["id"] not in [x["id"] for x in api.list_guardrails(aws)],
                  "the guardrail to be deleted", 300, echo, sleep)

    def delete_vector_store():
        for vb in found["vector_buckets"]:
            if vb["name"] != names.vector_bucket:
                continue
            for index in [i for i in found["vector_indexes"] if i["vector_bucket"] == vb["name"]]:
                echo(f"      deleting vector index {index['name']}")
                api.delete_vector_index(aws, vb["name"], index["name"])
            echo(f"      deleting vector bucket {vb['name']}")
            api.delete_vector_bucket(aws, vb["name"])

    def delete_role():
        if names.role not in [r["name"] for r in found["roles"]]:
            return
        for policy_name in api.list_role_policies(aws, names.role):
            api.delete_role_policy(aws, names.role, policy_name)
        echo(f"      deleting role {names.role}")
        api.delete_role(aws, names.role)

    def delete_bucket():
        if names.bucket not in found["buckets"]:
            return
        removed = api.empty_bucket(aws, names.bucket)
        echo(f"      deleted {removed} objects; deleting bucket {names.bucket}")
        api.delete_bucket(aws, names.bucket)

    # Order: the role is deleted only after the data source and knowledge base are gone,
    # so the service can still use it while they are removed. This is a precaution taken
    # from the cleanup order of the AWS sample utils/managed_knowledge_base.py
    # (data sources, knowledge base, IAM, bucket); it is not a documented rule.
    # A knowledge base that could not be listed may still exist. Nothing it depends on is deleted then:
    # the role is what the service uses to remove the data source (round 2 review, MAJOR 6).
    kb_listed = "knowledge_bases" in found["listed"] and not any(
        error.startswith("data sources of ") for error in found["errors"])
    if kb_listed:
        kb_ok = stage("[1/5] Data sources and knowledge base", delete_knowledge_bases)
    else:
        echo("[1/5] Data sources and knowledge base")
        echo("      NOT ATTEMPTED: the knowledge bases or their data sources could not be listed, so this "
             "script does not know whether one still exists")
        kb_ok = False
    stage("[2/5] Guardrail", delete_guardrails)
    if kb_ok:
        stage("[3/5] S3 vector index and vector bucket (not deleted with the knowledge base)", delete_vector_store)
        stage("[4/5] IAM role", delete_role)
        stage("[5/5] S3 document bucket (not deleted with the knowledge base)", delete_bucket)
    else:
        echo("[3/5] [4/5] [5/5] vector store, IAM role and S3 bucket: NOT ATTEMPTED")
        failures.append("skipped the vector store, role and bucket because the knowledge base step failed or "
                        "the knowledge bases could not be listed; fix that and run teardown again")
    return failures


def confirm_gone(aws: api.Aws, state: dict) -> tuple[list[str], dict[str, str]]:
    """Which recorded resources does a fresh listing show to be absent?

    Returns (keys confirmed gone, {key: why it is NOT confirmed}). A resource counts as gone
    only when the listing for its kind succeeded, in the Region and account in use, and
    does not contain it. A listing that failed confirms nothing.
    """
    recorded = state_mod.recorded_resources(state)
    kinds = ["buckets", "roles", "knowledge_bases", "guardrails"]
    if "vector_bucket" in recorded or "vector_index" in recorded:
        kinds.append("vectors")
    found = discover(aws, "", tuple(kinds), children=False)
    gone: list[str] = []
    kept: dict[str, str] = {}

    def settle(key: str, kind: str, present: bool) -> None:
        if key not in recorded:
            return
        if kind not in found["listed"]:
            kept[key] = "its listing failed, so its absence could not be confirmed"
        elif present:
            kept[key] = "it is still listed"
        else:
            gone.append(key)

    settle("bucket", "buckets", recorded.get("bucket") in found["buckets"])
    settle("role_name", "roles", recorded.get("role_name") in [r["name"] for r in found["roles"]])
    kb_id = recorded.get("knowledge_base_id") or state.get("knowledge_base_id")
    if kb_id == state_mod.PENDING:                             # recorded before its id was known: go by the name
        by_name = [kb["id"] for kb in found["knowledge_bases"] if kb["name"] == state.get("knowledge_base_name")]
        kb_id = by_name[0] if by_name else None
    settle("knowledge_base_id", "knowledge_bases", kb_id in [kb["id"] for kb in found["knowledge_bases"]])
    if recorded.get("guardrail_id") == state_mod.PENDING:      # recorded before its id was known: go by the name
        guardrail_present = state.get("guardrail_name") in [g["name"] for g in found["guardrails"]]
    else:
        guardrail_present = recorded.get("guardrail_id") in [g["id"] for g in found["guardrails"]]
    settle("guardrail_id", "guardrails", guardrail_present)
    settle("vector_bucket", "vectors",
           recorded.get("vector_bucket") in [vb["name"] for vb in found["vector_buckets"]])

    if "data_source_id" in recorded:
        if "knowledge_bases" not in found["listed"]:
            kept["data_source_id"] = "the knowledge base listing failed, so its absence could not be confirmed"
        elif not kb_id or kb_id not in [kb["id"] for kb in found["knowledge_bases"]]:
            gone.append("data_source_id")              # its knowledge base is gone, and it cannot outlive it
        else:
            sources = data_sources_of(aws, kb_id, found)
            if sources is None:
                kept["data_source_id"] = "its listing failed, so its absence could not be confirmed"
            elif (recorded["data_source_id"] in [ds["id"] for ds in sources]
                  or (recorded["data_source_id"] == state_mod.PENDING
                      and state.get("data_source_name") in [ds.get("name") for ds in sources])):
                kept["data_source_id"] = "it is still listed"
            else:
                gone.append("data_source_id")
    if "vector_index" in recorded:
        vector_bucket = state.get("vector_bucket")
        if "vectors" not in found["listed"]:
            kept["vector_index"] = "the vector bucket listing failed, so its absence could not be confirmed"
        elif not vector_bucket or vector_bucket not in [vb["name"] for vb in found["vector_buckets"]]:
            gone.append("vector_index")
        else:
            indexes = vector_indexes_of(aws, vector_bucket, found)
            if indexes is None:
                kept["vector_index"] = "its listing failed, so its absence could not be confirmed"
            elif recorded["vector_index"] in [i["name"] for i in indexes]:
                kept["vector_index"] = "it is still listed"
            else:
                gone.append("vector_index")
    return gone, kept


KIT_B_ARN_MARKERS = (":knowledge-base/", ":guardrail/", ":s3vectors:")
_NAME_SHAPES = (
    ("buckets", re.compile(r"(?P<prefix>.+)-fedrag-corpus-\d{12}-(?P<region>.+)")),
    ("roles", re.compile(r"(?P<prefix>.+)-fedrag-kb-role-(?P<region>.+)")),
)


def place_of(kind: str, name: str, region_in_use: str) -> dict:
    """The prefix and the Region a kit B name was built with. Bucket and role names carry the Region;
    the other kinds exist in the Region they were listed in."""
    for shaped_kind, pattern in _NAME_SHAPES:
        match = pattern.fullmatch(name) if kind == shaped_kind else None
        if match:
            return {"prefix": match.group("prefix"), "region": match.group("region")}
    prefix = name.split(KIT_MARKER, 1)[0] if KIT_MARKER in name else None
    return {"prefix": prefix, "region": region_in_use}


def _key_of_arn(arn: str) -> tuple[str, str] | None:
    """(kind, name or id) for the ARN of a kind this kit creates, the way leftovers() keys its entries."""
    if arn.startswith("arn:aws:s3:::"):
        return "buckets", arn.split(":::", 1)[1]
    for marker, kind in ((":role/", "roles"), (":knowledge-base/", "knowledge_bases"), (":guardrail/", "guardrails")):
        if marker in arn:
            return kind, arn.split(marker, 1)[1].split("/")[0]
    if ":s3vectors:" in arn and "bucket/" in arn:
        return "vector_buckets", arn.split("bucket/", 1)[1].split("/")[0]
    return None


def leftovers(aws: api.Aws, settings: config.Settings) -> dict:
    """What a fresh listing shows after a teardown, in the account and Region in use.

    "kit": every bucket, role, knowledge base, guardrail and vector bucket whose name contains
    "-fedrag-", WHATEVER prefix is in front and whatever Region a bucket or role name carries, plus
    everything tagged project=aws-kits that is of a kind this kit creates. Each entry says where its
    name points. "other_tagged": tagged resources of other kinds (another kit's). "errors": listings
    that failed; a teardown that could not list cannot say that nothing is left. "stale_tagged":
    tagged ARNs of this kit's kinds that the service's own listing no longer holds (just deleted).
    """
    found = discover(aws, "", children=False)
    kit: dict[tuple[str, str], dict] = {}
    labels = {"buckets": "S3 bucket", "roles": "IAM role", "knowledge_bases": "knowledge base",
              "guardrails": "guardrail", "vector_buckets": "S3 vector bucket"}
    for kind, label in labels.items():
        for entry in found[kind]:
            name = entry if isinstance(entry, str) else (entry.get("name") or "")
            if KIT_MARKER not in name:
                continue
            identity = entry.get("id") if isinstance(entry, dict) and entry.get("id") else name
            kit[(kind, identity)] = {"kind": label, "name": name, "id": identity,
                                     **place_of(kind, name, settings.region)}
    tagged = _try(found, "tagged resources",
                  lambda: api.get_tagged_resources(aws, config.TAG_KEY, config.TAG_VALUE))
    # What each service's own listing holds right now, by the same keys the tagged ARNs are turned into.
    present = {(kind, (entry if isinstance(entry, str) else entry.get("id") or entry.get("name") or ""))
               for kind in labels for entry in found[kind]}
    present |= {(kind, entry.get("name") or "") for kind in labels for entry in found[kind] if isinstance(entry, dict)}
    listed_kinds = {kind for kind in labels if ("vectors" if kind == "vector_buckets" else kind) in found["listed"]}
    other_tagged, stale_tagged = [], []
    for entry in tagged or []:
        arn = entry.get("ResourceARN") or ""
        key = _key_of_arn(arn)
        if key in kit:
            continue
        if key and (KIT_MARKER in arn or any(marker in arn for marker in KIT_B_ARN_MARKERS)):
            if key[0] in listed_kinds and key not in present:
                # UNVERIFIED: how long the tagging API goes on returning a resource that was just deleted.
                # The service's own listing, made a moment ago, does not hold it, so it is not counted as left.
                stale_tagged.append(arn)
                continue
            kit[key] = {"kind": labels[key[0]] + " (found by its tag)", "name": arn, "id": key[1],
                        "prefix": None, "region": settings.region}
        elif arn:
            other_tagged.append(arn)
    return {"kit": list(kit.values()), "other_tagged": other_tagged, "stale_tagged": stale_tagged,
            "errors": found["errors"]}


def verify(aws: api.Aws, settings: config.Settings, state: dict | None = None) -> dict:
    """Read-only look for anything left, in the Region and account in use.

    A resource counts as kit B's when its name contains "-fedrag-" (whatever the prefix in
    front of it), or when .state.json records its id. Lists every bucket, role, knowledge
    base, guardrail and vector bucket of the account to find them, plus everything in the
    Region tagged project=aws-kits and every OpenSearch Serverless collection.
    """
    state = state or {}
    found = discover(aws, "", children=False)
    recorded_ids = {str(state.get(key)) for key in ("knowledge_base_id", "guardrail_id") if state.get(key)}
    recorded_names = {str(state.get(key)) for key in ("bucket", "role_name", "vector_bucket") if state.get(key)}

    def name_of(entry) -> str:
        return entry if isinstance(entry, str) else (entry.get("name") or "")

    def is_kit(entry) -> bool:
        name = name_of(entry)
        if KIT_MARKER in name or name in recorded_names:
            return True
        return isinstance(entry, dict) and str(entry.get("id")) in recorded_ids

    kit: dict = {}
    other: dict = {}
    for kind in ("buckets", "roles", "knowledge_bases", "guardrails", "vector_buckets"):
        kit[kind] = [entry for entry in found[kind] if is_kit(entry)]
        other[kind] = [entry for entry in found[kind]
                       if not is_kit(entry) and name_of(entry).startswith(settings.prefix + "-")]
    kit["data_sources"] = []
    for kb in kit["knowledge_bases"]:
        kit["data_sources"] += data_sources_of(aws, kb["id"], found) or []
    kit["vector_indexes"] = []
    for vb in kit["vector_buckets"]:
        kit["vector_indexes"] += vector_indexes_of(aws, vb["name"], found) or []

    errors = found["errors"]
    tagged = _try(found, "tagged resources",
                  lambda: api.get_tagged_resources(aws, config.TAG_KEY, config.TAG_VALUE)) or []
    collections = _try(found, "OpenSearch Serverless collections",
                       lambda: api.list_opensearch_serverless_collections(aws)) or []
    return {
        "kit_resources": kit,
        "kit_resource_count": sum(len(v) for v in kit.values()),
        "other_prefix_resources": other,
        "tagged_resources": [t.get("ResourceARN") for t in tagged if t.get("ResourceARN")],
        "opensearch_serverless_collections": collections,
        "errors": errors,
    }


def dry_run_present_fixture(names: config.Names, kb_type: str) -> dict:
    """Canned list responses that pretend every kit resource exists.

    Used only by `90_teardown.py --dry-run`, so the dry run can show every delete
    call it would make. Nothing here is read from AWS.
    """
    account = api.DRY_ACCOUNT
    fixture = {
        ("s3", "list_buckets"): {"Buckets": [{"Name": names.bucket}]},
        ("s3", "list_objects_v2"): {"IsTruncated": False, "KeyCount": 2, "Contents": [
            {"Key": names.corpus_prefix + "uc-0000.txt"},
            {"Key": names.corpus_prefix + "uc-0000.txt.metadata.json"}]},
        ("s3", "list_object_versions"): {"IsTruncated": False, "Versions": [
            {"Key": names.corpus_prefix + "uc-0000.txt", "VersionId": "null"},
            {"Key": names.corpus_prefix + "uc-0000.txt.metadata.json", "VersionId": "null"}]},
        ("iam", "list_roles"): {"IsTruncated": False, "Roles": [
            {"RoleName": names.role, "Arn": f"arn:aws:iam::{account}:role/{names.role}"}]},
        ("iam", "list_role_policies"): {"PolicyNames": [names.role_policy]},
        ("bedrock-agent", "list_knowledge_bases"): {"knowledgeBaseSummaries": [
            {"knowledgeBaseId": "DRYRUNKB01", "name": names.knowledge_base, "status": "ACTIVE"}]},
        ("bedrock-agent", "list_data_sources"): {"dataSourceSummaries": [
            {"knowledgeBaseId": "DRYRUNKB01", "dataSourceId": "DRYRUNDS01",
             "name": names.data_source, "status": "AVAILABLE"}]},
        ("bedrock", "list_guardrails"): {"guardrails": [
            {"id": "dryrunguardrail", "name": names.guardrail, "status": "READY", "version": "DRAFT"}]},
    }
    if kb_type == "s3vectors":
        fixture[("s3vectors", "list_vector_buckets")] = {"vectorBuckets": [
            {"vectorBucketName": names.vector_bucket,
             "vectorBucketArn": f"arn:aws:s3vectors:{names.region}:{account}:bucket/{names.vector_bucket}"}]}
        fixture[("s3vectors", "list_indexes")] = {"indexes": [
            {"vectorBucketName": names.vector_bucket, "indexName": names.vector_index,
             "indexArn": f"arn:aws:s3vectors:{names.region}:{account}:bucket/{names.vector_bucket}"
                         f"/index/{names.vector_index}"}]}
    return fixture
