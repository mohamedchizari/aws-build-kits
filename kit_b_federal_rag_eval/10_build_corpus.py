#!/usr/bin/env python3
"""Step 10. Download the OMB 2025 federal AI use case inventory at a pinned
commit and turn a seeded sample of it into small text documents, each with a
metadata sidecar for Bedrock Knowledge Bases.

No AWS call is made here. The only network call is one HTTPS GET to
raw.githubusercontent.com. Output goes to build/ (git-ignored).

Unofficial demonstration. Not endorsed by OMB or by any agency.
"""
from __future__ import annotations

import http.client
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from kitlib import config, corpus
from kitlib.cli import make_parser


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "aws-kits-kit-b"})
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 (fixed https URL)
        return response.read()


def main(argv: list[str] | None = None) -> int:
    settings = config.Settings.load()
    parser = make_parser(__doc__)
    parser.add_argument("--sample-size", type=int, default=settings.corpus_sample_size,
                        help="documents to build; 0 means every eligible row (default %(default)s)")
    parser.add_argument("--seed", type=int, default=settings.seed, help="sampling seed (default %(default)s)")
    parser.add_argument("--metadata-format", choices=("typed", "simple"), default="typed",
                        help="sidecar format; both are shown in the AWS docs (default %(default)s)")
    parser.add_argument("--csv", type=Path, default=None,
                        help="use this local CSV instead of downloading (offline use and tests)")
    parser.add_argument("--skip-sha-check", action="store_true",
                        help="accept a CSV whose SHA-256 differs from the pinned one (recorded in the manifest)")
    args = parser.parse_args(argv)

    build = config.build_dir()
    raw_path = build / "raw" / Path(config.OMB_CSV_PATH).name
    corpus_dir = build / "corpus"
    manifest_path = build / "corpus_manifest.json"

    print(f"Source repository : github.com/{config.OMB_REPO}")
    print(f"Pinned commit     : {config.OMB_COMMIT}")
    print(f"CSV               : {config.OMB_CSV_PATH}")
    print(f"Sample size / seed: {args.sample_size} / {args.seed}")
    print(f"Output folder     : {build}")

    if args.dry_run:
        source = f"read {args.csv}" if args.csv else f"HTTPS GET {config.OMB_CSV_URL}"
        print(f"DRY-RUN would {source}")
        print(f"DRY-RUN would check SHA-256 == {config.OMB_CSV_SHA256}")
        print(f"DRY-RUN would write {raw_path}, {corpus_dir}/uc-NNNN.txt (+ .metadata.json) and {manifest_path}")
        print("DRY-RUN no AWS API call is made by this script in any mode.")
        return 0

    if args.csv:
        try:
            data = args.csv.read_bytes()
        except OSError as exc:
            print(f"ERROR: could not read {args.csv} ({type(exc).__name__}: {exc.strerror or exc}). "
                  "Nothing was built.", file=sys.stderr)
            return 1
        print(f"Read {len(data):,} bytes from {args.csv}")
    else:
        try:
            data = download(config.OMB_CSV_URL)
        # no network, a proxy, a timeout, GitHub answering with an error, and (round 5) a connection closed before the
        # whole file arrived: http.client.IncompleteRead is an HTTPException, which is neither of the other two.
        except (urllib.error.URLError, http.client.HTTPException, OSError) as exc:
            print(f"ERROR: could not download the inventory CSV ({type(exc).__name__}: {exc}).\n"
                  f"  URL: {config.OMB_CSV_URL}\n"
                  "  Check the network and run this script again, or fetch that URL another way and pass the file:\n"
                  "    python 10_build_corpus.py --csv <the file you saved>\n"
                  "  The SHA-256 of the file is checked against the pinned one either way. Nothing was built.",
                  file=sys.stderr)
            return 1
        print(f"Downloaded {len(data):,} bytes")

    digest = corpus.sha256_bytes(data)
    sha_ok = digest == config.OMB_CSV_SHA256
    if not sha_ok and not args.skip_sha_check:
        print(f"ERROR: SHA-256 {digest} does not match the pinned {config.OMB_CSV_SHA256}.\n"
              "The file is not the one this kit was built and tested against. Nothing was written.",
              file=sys.stderr)
        return 1

    rows = corpus.parse_csv(data)
    files, manifest = corpus.build_corpus(rows, args.sample_size, args.seed, config.OMB_COMMIT,
                                          args.metadata_format)
    manifest.update({
        "source_repo": f"github.com/{config.OMB_REPO}",
        "csv_path": config.OMB_CSV_PATH,
        "csv_sha256": digest,
        "csv_sha256_matches_pin": sha_ok,
        "raw_csv": str(raw_path),
    })

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(data)
    corpus_dir.mkdir(parents=True, exist_ok=True)
    for stale in list(corpus_dir.glob("uc-*.txt")) + list(corpus_dir.glob("uc-*.txt.metadata.json")):
        stale.unlink()
    for name, content in files.items():
        # Written as bytes so the files on disk are exactly what the fingerprint was computed from.
        (corpus_dir / name).write_bytes(content.encode("utf-8"))
    manifest_path.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")

    print(f"CSV rows read          : {manifest['csv_rows']:,}")
    print(f"Eligible rows          : {manifest['eligible_rows']:,}")
    print(f"Documents written      : {manifest['documents']:,} (plus the same number of sidecars)")
    print(f"Mean / max doc length  : {manifest['mean_document_chars']} / {manifest['max_document_chars']} characters")
    print(f"Total document text    : {manifest['total_document_chars']:,} characters")
    print(f"SHA-256 matches the pin: {sha_ok}")
    replaced = manifest["contact_details_replaced"]
    print(f"Contact details replaced: {replaced['e_mail_addresses']} e-mail address(es), "
          f"{replaced['phone_shaped_strings']} phone-shaped string(s) (the contact_email column is never read)")
    print(f"Corpus fingerprint     : {manifest['corpus_fingerprint'][:12]} (30_deploy_kb.py and 50_run_eval.py "
          "compare it)")
    print(f"Manifest               : {manifest_path}")
    print("Next: python 20_build_eval_set.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
