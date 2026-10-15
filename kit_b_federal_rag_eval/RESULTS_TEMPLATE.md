# Kit B results (fill in with your own numbers)

Leave a cell blank rather than guess. Every number here should be one you saw on your own screen or bill.

## Run record

| Item | Your value |
|---|---|
| Date of the run | |
| AWS Region | |
| Service | Amazon Bedrock Knowledge Bases, type: managed / s3vectors |
| Retrieval (the "Retrieval" line of summary.md) | managed type: hybrid search with the service-managed re-ranker, sent as `rerankingModelType=MANAGED`. s3vectors type: vector search, no re-ranking model configured |
| boto3 version (`pip show boto3`) | |
| OMB repository commit | 06c7ebeef5b376524211042bd9673b2a7fefd3e3 |
| Corpus: documents, seed | |
| Evaluation set: the "Evaluation set" line of summary.md ("all 120 questions", or "first N of 120 questions (--limit N)": a run with --limit is a smoke test, not a result) | |
| Generation model id | |
| Judge model id | |
| Judge and generator from the same model family? (the "Judge and generator" line of summary.md: SAME FAMILY, SAME PROVIDER, different families, or COULD NOT TELL) | With the defaults: YES, an Amazon Nova judge (Nova Pro) grading an Amazon Nova generator (Nova Lite) |
| Top k | |
| Guardrail thresholds (grounding / relevance) | |

## Deploy (from the output of 30_deploy_kb.py)

| Measurement | Your value |
|---|---|
| Objects uploaded to S3 | |
| Ingestion: documents scanned | |
| Ingestion: new documents indexed | |
| Ingestion: documents failed | |
| Ingestion: metadata documents scanned | |
| Minutes from the start of 30_deploy_kb.py to ingestion COMPLETE (printed by the script) | |
| Knowledge base created at (UTC, printed by the script) | |
| Smoke test: document ids returned without a filter | |
| Smoke test: document ids returned with the development_stage filter | |
| Anything in the script you had to change to make it work | |

## Evaluation (paste the table from results/run-.../summary.md)

What this table is, so that nobody reading it later has to guess. Change the wording only if your `summary.md` says otherwise.

- The retrieval rows measure the knowledge base as queried by the kit: on the managed type that is hybrid search plus the service-managed re-ranking model. They do not measure plain vector search.
- "Correct as judged" is the verdict of a language model. With the default models it is an Amazon Nova judge grading an Amazon Nova generator, and a judge can favour answers in its own family's style.
- "Correct by exact match" gives credit only when the answer is the expected value plus words from a short fixed list. Any other word, a question mark, a hedge or a second, different value makes the answer "unclear", which is counted as not correct and has a row of its own. So this rate can undercount, by at most the unclear row. It was built not to credit a wrong answer; README section 8 says on what that was measured.
- "Correct as judged" counts only replies with one clear verdict whose reason is made of words the reader has on its lists and passes its rules about what the reason says of the candidate (README section 2, item 9). Those are word lists and sentence shapes, not meaning: a reason that takes the verdict back in a shape they do not know is still counted, and a clear reply they cannot read is in the "could not be parsed" count below, so this rate can undercount too. It can be wrong in either direction; read the replies in `raw.jsonl` if it matters.
- The two columns are the same answers. "Guardrail on" differs from "off" only by the blocked answers counted in the lower rows. A block is the grounding filter or the relevance filter (both are set to BLOCK); the table does not say which.
- If the run used `--no-guardrail`, every cell of the "Guardrail on" column says "not applied". Do not fill it in from another run.
- If `summary.md` starts with a line in capitals (INCOMPLETE RUN, or a WARNING about document ids), copy that line here too and do not quote the numbers it concerns.

| Measure | Guardrail off | Guardrail on |
|---|---|---|
| Answerable questions scored | | |
| Retrieval hit rate, source document in top k | | same retrieval |
| Retrieval hit rate, source document ranked first | | same retrieval |
| Answerable: correct by exact match | | |
| Answerable: unclear to exact match (counted as not correct) | | |
| Answerable: another value, read cleanly by exact match | | |
| Answerable: correct as judged | | |
| Answerable: refused or blocked | | |
| Unanswerable questions scored | | |
| Unanswerable: refused or blocked (exact: the fixed sentence alone) | | |
| Unanswerable: refused or blocked (judged DECLINED) | | |
| Unanswerable: answered anyway (judged INCORRECT) | | |
| Unanswerable: judge verdict unclear (CORRECT or unparseable) | | |
| Guardrail blocks (grounding or relevance filter), total | not applied | |
| ... blocks of answers judged correct | not applied | |
| ... blocks of answers not judged correct (answerable) | not applied | |
| ... blocks of invented answers to unanswerable questions | not applied | |
| ... blocks of refusals in other words (unanswerable) | not applied | |
| ... blocks where the judge verdict was unclear (unanswerable) | not applied | |
| ... blocks of the fixed refusal sentence | not applied | |

| Check | Your value |
|---|---|
| Exact match and judge agree on (count / n) | |
| Judge replies that could not be parsed | |
| Judge verdict CORRECT on a question that has no answer | |
| Retrieved passages without a readable document id (the hit rate is not a measurement if not 0) | |
| Questions that hit an error (the run is incomplete if not 0) | |
| Earlier failed or interrupted attempts included in the usage (after --resume) | |
| Answers and judge replies that ended at the token limit (the WARNING line of summary.md, if there is one) | |
| Rows you read by hand where exact match and judge disagree, and what you found | |
| Unclear rows you read by hand (`exact_unclear` is True; `exact_note` and `exact_unread` say why): how many were in fact correct, how many wrong | |
| Unparseable judge replies you read by hand (`judge_note` says why; the reply is in raw.jsonl): how many were in fact a clear verdict | |

## Usage and money

| Item | Your value |
|---|---|
| Retrieve calls | |
| Generation tokens (input / output) | |
| Judge tokens (input / output) | |
| Guardrail text units | |
| Cost of the evaluation run at list price (from summary.md) | |
| Anything the usage line of summary.md says is NOT COUNTED (copy the sentence) | |
| Dollars actually billed, Amazon Bedrock (Billing console, a day later) | |
| Dollars actually billed, Amazon S3 | |
| Dollars actually billed, anything else | |
| Hours the knowledge base existed (printed by 90_teardown.py) | |

## Teardown

| Item | Your value |
|---|---|
| Date and time 90_teardown.py finished (UTC, printed by the script) | |
| 90_teardown.py exit code (0 = every delete succeeded and its own listing shows no kit B resource; 1 = not finished; 5 = dry run) and its RESULT line, copied | |
| 99_verify_clean.py exit code (0 = clean; 1 not clean; 3 OpenSearch collections; 4 incomplete; 5 dry run) | |
| The RESULT line of 99_verify_clean.py, copied (it names the account ending, the Region and the prefix checked, and says whether a state file told it where to look) | |
| `../common/whats_running.py` exit code, with the Region and prefix you gave it | |
| OpenSearch Serverless collections listed by 99_verify_clean.py | |
| Billing console checked the next day, new charges after teardown | |

## Notes in your own words

What surprised you, what failed first, what you would change for a real customer.
