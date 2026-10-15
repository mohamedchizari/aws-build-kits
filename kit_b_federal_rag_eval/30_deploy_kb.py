#!/usr/bin/env python3
"""Step 30. Create the knowledge base and load the corpus into it.

Creates, in this order: an S3 bucket, the documents and metadata sidecars in
it, an IAM role, (only for KB_TYPE=s3vectors: an S3 vector bucket and index),
the Bedrock knowledge base, its S3 data source, and one ingestion job. Waits
for each to finish, records every id in .state.json, then runs two Retrieve
calls so you can see retrieval and a metadata filter working.

This script NEVER creates an OpenSearch Serverless collection.
Re-running it in the same account, Region and prefix is safe: existing resources
are found by name and reused, and the bucket is made to hold exactly the local
corpus (objects left from an earlier corpus build are removed before the sync).
If .state.json records a deploy somewhere else, or with another KB_TYPE, this
script stops and changes nothing: tear the recorded deploy down first.
"""
from __future__ import annotations

import sys
import time

from kitlib import aws as api
from kitlib import config, pricing, resources
from kitlib import state as state_mod
from kitlib.cli import banner, make_parser, require_bills_flag, stop
from kitlib.redact import protect_output


def price_lines(settings: config.Settings, corpus_bytes: int, n_objects: int) -> list[str]:
    gb = corpus_bytes / 1e9
    src = f"us-east-1, read {pricing.READ_DATE}"
    lines = [
        f"S3 Standard storage ${pricing.S3_STANDARD_PER_GB_MONTH} per GB-month and "
        f"${pricing.S3_PUT_PER_1K} per 1,000 PUT requests (AWS Price List AmazonS3, {src}). "
        f"This corpus: {n_objects} PUTs = ${n_objects * pricing.S3_PUT_PER_1K / 1000:.4f}.",
    ]
    if settings.kb_type == "managed":
        lines += [
            f"Managed Knowledge Base index storage ${pricing.MANAGED_KB_STORAGE_PER_GB_MONTH:.2f} per GB of raw "
            f"data per month; Retrieve API ${pricing.MANAGED_KB_RETRIEVE_PER_1K_CALLS:.2f} per 1,000 calls; managed "
            f"parsing and embeddings $0 (aws.amazon.com/bedrock/pricing/, no Region stated, read {pricing.READ_DATE}). "
            f"This corpus is {corpus_bytes / 1e6:.2f} MB = ${gb * pricing.MANAGED_KB_STORAGE_PER_GB_MONTH:.4f} a month "
            "IF storage is billed pro rata. The page states no Region and no minimum; proration is unconfirmed.",
            "The storage charge runs until the knowledge base is deleted. Run 90_teardown.py when you are done.",
        ]
    else:
        embed = pricing.EMBED_PRICE_PER_1M.get(settings.embed_model_id)
        tokens = pricing.estimate_tokens(corpus_bytes)
        embed_text = (f"${embed} per 1M input tokens, about ${tokens * embed / 1e6:.4f} for this corpus "
                      "(4 characters per token assumed)") if embed else "price not in this kit's table"
        lines += [
            f"Embedding model {settings.embed_model_id}: {embed_text} (AWS Price List AmazonBedrock, {src}).",
            f"S3 Vectors storage ${pricing.S3_VECTORS_STORAGE_PER_GB_MONTH:.2f} per GB-month, PUT "
            f"${pricing.S3_VECTORS_PUT_PER_GB:.2f} per GB, queries "
            f"${pricing.S3_VECTORS_QUERY_PER_REQUEST * 1000:.4f} per 1,000 "
            f"(AWS Price List AmazonS3, {src}).",
            "The vector bucket and index are NOT deleted with the knowledge base. 90_teardown.py deletes them.",
        ]
    lines.append(f"2 Retrieve calls for the smoke test: ${pricing.retrieve_cost(2, settings.kb_type):.4f}.")
    return lines


@protect_output
def main(argv: list[str] | None = None) -> int:
    started = time.monotonic()
    settings = config.Settings.load()
    parser = make_parser(__doc__, bills=True)
    parser.add_argument("--skip-smoke-test", action="store_true", help="do not run the two Retrieve calls")
    args = parser.parse_args(argv)

    corpus_dir = config.build_dir() / "corpus"
    files = resources.corpus_files(corpus_dir)
    corpus_bytes = sum(p.stat().st_size for p in files if p.name.endswith(".txt"))

    banner(f"Kit B deploy: knowledge base type '{settings.kb_type}' in {settings.region}")
    if settings.kb_type == "managed" and settings.region not in config.MANAGED_KB_REGIONS:
        print(f"WARNING: {settings.region} is not in the Managed Knowledge Base Region list read on "
              f"{api.DOCS_READ}. Supported then: {', '.join(config.MANAGED_KB_REGIONS)}.")
    require_bills_flag(args, price_lines(settings, corpus_bytes, len(files)))
    if not files and not args.dry_run:
        print(f"ERROR: no corpus in {corpus_dir}. Run 10_build_corpus.py first.", file=sys.stderr)
        return 1

    aws = api.Aws(settings.region, dry_run=args.dry_run)
    try:
        state = resources.deploy(aws, settings, corpus_dir)
        minutes_to_complete = (time.monotonic() - started) / 60.0     # deploy() returns when ingestion is COMPLETE
        if not args.skip_smoke_test:
            print("Smoke test: two Retrieve calls")
            resources.smoke_retrieve(aws, settings, state["knowledge_base_id"])
    except state_mod.StopHere as error:
        return stop(error)
    except KeyboardInterrupt:
        print("\nInterrupted. Whatever was created so far is recorded in .state.json, with its account, Region "
              "and prefix. Run this script again to finish, or python 90_teardown.py to remove it.", file=sys.stderr)
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("Whatever was created so far is recorded in .state.json. Fix the cause and re-run this "
              "script (it reuses what exists), or run 90_teardown.py to remove it.", file=sys.stderr)
        return 1

    banner("Done")
    if args.dry_run:
        print("DRY-RUN: every call above was checked against the SDK's API model. None was sent.")
        return 0
    stats = (state.get("ingestion") or {}).get("statistics") or {}
    print(f"Knowledge base id : {state.get('knowledge_base_id')}")
    print(f"Data source id    : {state.get('data_source_id')}")
    print(f"Minutes from the start of this script to ingestion COMPLETE: {minutes_to_complete:.1f} "
          "(this computer's clock)")
    print(f"Knowledge base created at (UTC, this computer's clock): "
          f"{state.get('knowledge_base_created_at') or 'not known: it existed before this run'}. "
          "90_teardown.py prints the hours it existed.")
    print(f"Documents indexed : {stats.get('numberOfNewDocumentsIndexed')} new, "
          f"{stats.get('numberOfDocumentsFailed')} failed, {stats.get('numberOfDocumentsScanned')} scanned")
    if stats.get("numberOfDocumentsFailed"):
        print(f"WARNING: {stats['numberOfDocumentsFailed']} document(s) failed to ingest. The knowledge base "
              "is missing part of the corpus, so the retrieval hit rate will be lower for that reason alone. "
              "Find out why (Bedrock console, knowledge base, data source, sync history) before you evaluate.")
    expected = len([f for f in files if f.name.endswith(".txt")])
    print(f"Local corpus      : {expected} documents; the bucket was checked to hold exactly these "
          f"(fingerprint {str(state.get('corpus_fingerprint'))[:12]})")
    if state.get("stale_objects_removed"):
        print(f"Stale objects     : {state['stale_objects_removed']} removed from the bucket before the sync; "
              f"the job reports {stats.get('numberOfDocumentsDeleted')} document(s) deleted from the index. "
              "If that number is lower than the number of stale documents, the knowledge base still holds "
              "old documents: do not evaluate, tear down and deploy again.")
    scanned = stats.get("numberOfDocumentsScanned")
    if scanned not in (None, expected):
        # UNVERIFIED: exactly what numberOfDocumentsScanned counts (documents only, or metadata files too).
        print(f"WARNING: the ingestion job scanned {scanned} document(s) but the local corpus has {expected}. "
              "Check the data source in the Bedrock console before you evaluate: a knowledge base that holds "
              "other documents than the local corpus makes the unanswerable questions meaningless.")
    if stats.get("numberOfNewDocumentsIndexed") not in (None, expected):
        print(f"NOTE: {stats.get('numberOfNewDocumentsIndexed')} document(s) are reported as newly indexed, "
              f"{stats.get('numberOfModifiedDocumentsIndexed')} as modified. A re-run skips unchanged files, "
              "so a number below the corpus size is expected only on a re-run.")
    print("Write these numbers into RESULTS_TEMPLATE.md. Next: python 40_create_guardrail.py "
          "--i-understand-this-bills")
    return 0


if __name__ == "__main__":
    sys.exit(main())
