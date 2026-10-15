#!/usr/bin/env python3
"""Step 20. Build the fixed evaluation set from the CSV fields.

About 100 questions whose answers can be checked against a CSV cell (agency,
stage of development, high-impact determination) plus about 20 questions that
have no answer in the corpus. No language model writes anything here: questions
are filled-in templates and expected answers are copied from the CSV.

No AWS call and no network call is made. Reads build/, writes build/eval/.
"""
from __future__ import annotations

import json
import sys

from kitlib import config, corpus, evalset, jsonl, scoring
from kitlib.cli import make_parser


def main(argv: list[str] | None = None) -> int:
    settings = config.Settings.load()
    parser = make_parser(__doc__)
    parser.add_argument("--seed", type=int, default=settings.seed, help="selection seed (default %(default)s)")
    for kind, default in evalset.DEFAULT_COUNTS.items():
        parser.add_argument(f"--n-{kind.replace('_', '-')}", type=int, default=default, dest=f"n_{kind}",
                            help=f"number of {kind} questions (default %(default)s)")
    parser.add_argument("--allow-shortfall", action="store_true",
                        help="write the set even if a question type could not be filled")
    args = parser.parse_args(argv)

    build = config.build_dir()
    manifest_path = build / "corpus_manifest.json"
    out_dir = build / "eval"
    set_path = out_dir / "eval_set.jsonl"
    meta_path = out_dir / "eval_set_meta.json"
    counts = {kind: getattr(args, f"n_{kind}") for kind in evalset.DEFAULT_COUNTS}

    if args.dry_run:
        print(f"DRY-RUN would read {manifest_path} and the raw CSV it points to")
        print(f"DRY-RUN would build questions {counts} with seed {args.seed}")
        print(f"DRY-RUN would write {set_path} and {meta_path}")
        print("DRY-RUN no AWS API call and no network call is made by this script in any mode.")
        return 0

    if not manifest_path.is_file():
        print(f"ERROR: {manifest_path} not found. Run 10_build_corpus.py first.", file=sys.stderr)
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = corpus.parse_csv(open(manifest["raw_csv"], "rb").read())
    corpus_rows = {d["row_number"] for d in manifest["docs"]}

    items, meta = evalset.build_eval_set(rows, corpus_rows, args.seed, counts)
    meta.update({
        "commit": manifest["commit"],
        "csv_sha256": manifest["csv_sha256"],
        "corpus_documents": manifest["documents"],
        "corpus_seed": manifest["seed"],
        "corpus_fingerprint": manifest.get("corpus_fingerprint"),
    })

    print(f"Corpus documents : {manifest['documents']:,}")
    for kind in evalset.DEFAULT_COUNTS:
        print(f"  {kind:<28}: {meta['built'].get(kind, 0)} of {counts[kind]} requested")
    print(f"Answerable       : {meta['answerable']}")
    print(f"Unanswerable     : {meta['unanswerable']}")
    print(f"Total            : {meta['total']}")
    for kind, labels in meta["expected_answer_counts"].items():
        if kind != "agency":
            print(f"  {kind} expected answers: {labels}")
    print(f"  agency expected answers: {len(meta['expected_answer_counts']['agency'])} different agencies")
    near = meta["near_duplicates"]
    print("Near-duplicate use cases (rule and thresholds are in eval_set_meta.json):")
    for kind, excluded in near["excluded_rows"].items():
        print(f"  {kind:<28}: {len(excluded)} candidate(s) not used")
    print(f"  In all: {sum(len(v) for v in near['excluded_rows'].values())} candidate(s) not used, which are "
          f"{near['excluded_rows_distinct']} different CSV row(s) (one row can be turned down for more than "
          "one question type)")
    print(f"  questions kept but flagged (a similar name with ANOTHER value is in the corpus): "
          f"{near['flagged_questions']}")

    # What exact match will accept as a spelling of each agency, checked for collisions against every
    # agency of the CSV, not only the ones a question asks about. Written into the meta file to be read;
    # 50_run_eval.py derives the same list again from the label set when it scores.
    short_names, dropped = scoring.agency_short_names(meta["label_sets"]["agency"])
    abbreviations = [alias["text"] for entry in meta["label_sets"]["agency"] for alias in entry["aliases"]
                     if alias.get("text")]
    not_alone = sorted(a for a in abbreviations if not scoring.abbreviation_stands_alone(a))
    meta["exact_match"] = {
        "scoring_version": scoring.SCORING_VERSION,
        "accepted_spellings": {kind: scoring.accepted_spellings(meta["label_sets"], kind)
                               for kind in ("agency", "stage", "high_impact")},
        "agency_short_names_dropped_for_a_collision": dropped,
        "abbreviations_not_accepted_alone": not_alone,
    }
    print(f"Exact match, agency spellings: {len(meta['label_sets']['agency'])} agencies in the CSV; "
          f"{sum(len(v) for v in short_names.values())} short names accepted, {len(dropped)} dropped for a "
          "collision with another agency's name")
    print(f"  abbreviations accepted only next to the full name (a US state code or an ordinary word): "
          f"{', '.join(not_alone) or 'none'}")

    if meta["shortfalls"] and not args.allow_shortfall:
        print(f"ERROR: could not fill {meta['shortfalls']}. Build a larger corpus, lower the counts, "
              "or pass --allow-shortfall. Nothing was written.", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    # One question per physical line, whatever a use case name holds (kitlib/jsonl.py). For the
    # inventory at the pinned commit this writes the same bytes as json.dumps(..., ensure_ascii=False).
    with set_path.open("w", encoding="utf-8", newline="\n") as handle:
        for item in items:
            handle.write(jsonl.dumps_line(item))
    meta_path.write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {set_path}")
    print(f"Wrote {meta_path}")
    print("Read a dozen of the questions yourself before spending money on them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
