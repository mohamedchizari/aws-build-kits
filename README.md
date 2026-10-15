# aws-build-kits

Three small, hands-on AWS builds for one person to run alone in their own AWS account. Each kit builds one thing, measures it, tears it down and then checks that nothing is still billing.

| Folder | What it builds |
| --- | --- |
| `kit_a_gpu_endpoint/` | A small open-weights model (Qwen3-4B) on one single-GPU Amazon SageMaker AI real-time endpoint: deploy, call it three ways, load-test it, change one serving setting, measure again, delete. |
| `kit_b_federal_rag_eval/` | Question answering over 400 public documents from the OMB 2025 federal AI use case inventory in an Amazon Bedrock knowledge base, with a grounding guardrail and a fixed 120-question evaluation scored by exact match and by a judge model. |
| `kit_c_langgraph_agentcore/` | A small LangGraph agent with two Federal Register tools, run locally against a model on Amazon Bedrock, then hosted on Amazon Bedrock AgentCore Runtime. |
| `common/` | Two safety scripts shared by the kits: a monthly budget alarm, and a read-only audit of what is still running and billing. |

`SPINE.md` is the set of rules every kit follows: the folder layout, the README sections, the script names and the `--dry-run` and `--i-understand-this-bills` flags.

## Status: never run against AWS

- Nothing in this repository has been run against a real AWS account. Kit A's model has never been deployed, and the default models of kits B and C (Amazon Nova) have never been called. Expect to debug the first deploy of each kit.
- Each kit's README, section 8 ("What was and was not tested"), lists the AWS calls that have never run and marks UNVERIFIED every API shape that was not confirmed in a current AWS document.
- Running a kit costs money. Each README quotes its prices with the page, the Region and the date they were read (7 October 2026). Prices change: check them again before you run. A budget alarm sends e-mail and stops nothing; only the kit's own teardown, run by you, stops a bill.
- Kit A cannot start until AWS approves a SageMaker GPU endpoint quota, which is 0 by default.

## Run a kit

You need your own AWS account, the AWS CLI version 2 with a sign-in (for example `aws configure sso`), and Python 3.11 or newer. Kit C also needs `uv`.

1. Set the budget alarm first: `common/README.md`.
2. Open the kit's `START_HERE.md` and follow its commands in order. The `README.md` in the same folder is the reference.
3. The scripts take `--dry-run`, which prints the calls they would make and makes none, and a script that creates something billable refuses to run without `--i-understand-this-bills` (the rules in `SPINE.md`).
4. Finish in the same sitting: run the kit's `90_teardown.py`, then these three, and read the `RESULT:` line of each, not only the exit code.

```
python 99_verify_clean.py                               # in the kit folder
python ../common/whats_running.py                       # the independent audit
python ../common/whats_running.py --after-teardown a    # or b, or c
```

Write your own numbers into the kit's `RESULTS_TEMPLATE.md` as you go.

## Offline tests

The tests need no AWS account and no credentials. In each of the four folders:

```
python -m venv .venv && . .venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
```

Last run on 15 October 2026 on macOS (Apple silicon), Python 3.14.7, in one virtualenv built from the four `requirements.txt` files: `common/` 434 passed, `kit_a_gpu_endpoint/` 349 passed, `kit_b_federal_rag_eval/` 1,981 passed, `kit_c_langgraph_agentcore/` 1,031 passed.

## How it was checked

Five review rounds, each by Claude agents that had not written the code they read:

- Rounds 1 and 2: independent readers of the code; each finding was fixed with a test that failed first.
- Round 3: two models wrote answers for kits B and C from pre-chosen inputs, and separate readers labelled them blind.
- Round 4: three more independent reads, a local emulator run of every script, fixes, and a held-out run in which the models chose their own tool calls on questions nobody who changed code had seen.
- Round 5: three fresh readers of the round 4 fixes, and their fixes.

Every round found defects the round before had missed, and no independent reader has read the round 5 fixes. The emulator was moto plus hand-written fakes for the Bedrock, AgentCore and SageMaker runtime calls moto does not implement: a pass there shows that a request is well formed and that the code reads a response of the documented shape. It does not show what AWS answers.

The summaries of rounds 4 and 5 are in `_review_reports/`. Each kit's `REVIEW_NOTES_r4.md` and `REVIEW_NOTES_r5.md` list its findings and what changed. The readers' reports, attack suites, transcripts and the emulator harness are kept privately and are not in this repository.

## Data

Kit B downloads the OMB inventory CSV from its public GitHub repository at a pinned commit, and ships five rows of it and its 41 agency names as test fixtures (kit B README, section 2, item 13). Kit C calls the public Federal Register API. Neither kit is endorsed by OMB or by any agency.

## Who built it

Built by Claude (Anthropic's AI model) with the repository's owner. Claude agents wrote the code, the tests and the documents, and separate Claude agents did the reviews above.

## License

MIT. See `LICENSE`.
