# Kit B: start here

## What this is
Question answering over 400 public documents from the OMB 2025 federal AI use case inventory, in an Amazon Bedrock knowledge base, with a grounding guardrail.
You run 120 fixed questions through it and get one table: retrieval hit rate, correctness by exact match and by a judge model, what the guardrail blocked, and the cost.
Then you delete everything and check that nothing is left. Unofficial: not endorsed by OMB or by any agency. This page is the order of work; `README.md` is the reference.

## What it costs, and the one thing that stops the bill
About $0.25 for one full run of the 120 questions, at list prices read 2026-10-07 for us-east-1, by the kit's own estimate; the bill is the only real number. Managed knowledge base storage bills until you delete it: about $0.002 a month for the default corpus, if it is billed pro rata.
The one thing that stops the bill is `python 90_teardown.py`, run by you. A budget alarm (`../common/budget_alarm.py`) sends e-mail; it does not stop anything.

## Before you start
1. A personal AWS account and a sign-in that is not the root user: set up credentials for the AWS SDK the way you normally do (README section 3, steps 1 and 3).
2. No quota increase is known to be needed, and the default Amazon models should need no access request.
3. Run `echo $AWS_REGION`: if your shell exports a Region, that is the Region the scripts use, whatever `config.env` says.
4. Python 3.11 or newer, then:
```
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp config.example.env config.env        # then edit it if you want other models or a prefix
python -m pytest -q                     # offline; should pass before you touch AWS
```

## Problems first
1. Nothing here has been run against AWS: run every script with `--dry-run` first, then `50_run_eval.py --limit 5` before the full set.
2. Never give this kit's knowledge base an OpenSearch Serverless vector store: a collection can bill $11.52 a day with zero queries.
3. Exact match can miss a correct answer and counts every answer it could not read as not correct, so quote the unclear row with the correct row.
4. The judge is a model from the same family as the generator, and its reply is read by words, not by meaning.
5. 100 questions is a small sample (roughly plus or minus 8 points on a rate near 80%), and the guardrail off and on columns are the same answers.
6. The account, the Region and the prefix decide where the scripts act, and a `.state.json` that cannot be read stops everything until you deal with it: do not delete it to get past the message.

## The commands, in order
A script that bills refuses to run without `--i-understand-this-bills`. Any script takes `--dry-run`, which prints every AWS call and sends none.
```
python 00_check.py --dry-run
python 00_check.py
python 00_check.py --invoke-test --i-understand-this-bills    # one tiny request per model; the real proof of access
python 10_build_corpus.py
python 20_build_eval_set.py
python 30_deploy_kb.py --dry-run
python 30_deploy_kb.py --i-understand-this-bills
python 40_create_guardrail.py --i-understand-this-bills
python 50_run_eval.py --limit 5 --i-understand-this-bills
python 50_run_eval.py --i-understand-this-bills
```
The last line of each, in that order:
1. `DRY-RUN: the API calls above were printed and checked against the SDK's API model. None was sent.`
2. and 3. `No problem found. This does not prove model access unless you ran --invoke-test.` A line that starts `PROBLEM:` means stop and fix it.
4. `Next: python 20_build_eval_set.py`
5. `Read a dozen of the questions yourself before spending money on them.` Do that.
6. `DRY-RUN: every call above was checked against the SDK's API model. None was sent.`
7. `Write these numbers into RESULTS_TEMPLATE.md. Next: python 40_create_guardrail.py --i-understand-this-bills`. Read any `WARNING:` above it about documents scanned or failed.
8. `Next: python 50_run_eval.py --limit 5 --i-understand-this-bills`
9. and 10. `Copy the table into RESULTS_TEMPLATE.md. When you are finished: python 90_teardown.py`. A last line that starts `INCOMPLETE:` gives the `--resume` command to finish with. Step 9 is a smoke test of five agency questions, not a result: read all five rows of `per_question.csv` before step 10.

## Tear down and prove it
```
python 90_teardown.py --dry-run     # shows every delete call; exit code 5, never 0
python 90_teardown.py               # asks once, then deletes each resource separately
python 99_verify_clean.py           # exit code 0 means clean in the place named on its RESULT line
```
- The dry run ends with a line that starts `RESULT: NOTHING WAS DELETED (--dry-run)`.
- The teardown must print a line that starts `RESULT: every recorded resource was deleted or confirmed absent in`, with exit code 0. Its last line is `That is not proof. Now run: python 99_verify_clean.py`.
- The clean check must print a line that starts `RESULT: CLEAN in`, naming the account (last four digits), the Region and the prefix you deployed with, and saying "This is the place .state.json names". Exit code 0 is not enough: if the line says `NO STATE FILE`, nothing but your own memory told the script where to look.
- Then the shared audit, `python ../common/whats_running.py --region <the AWS_REGION in your config.env> --prefix <your KIT_PREFIX>`: its `RESULT:` line must say `nothing that bills while idle was found, and every check ran (exit 0)`. Look at the Billing console the next day.

## If something goes wrong
- The file never to touch: `.state.json`. It may be the only record of where the kit was deployed, and no script deletes or overwrites it.
- The script to run: `python 90_teardown.py`, then `python 99_verify_clean.py`. If step 10 is interrupted or questions fail, finish first with the `--resume` command the script prints.
- If every script stops because `.state.json` cannot be read, name the place yourself: `python 90_teardown.py --region <Region> --prefix <prefix>`. Its RESULT line will say `NOT CONFIRMED`, with exit code 1 on purpose: README section 5, "If `.state.json` cannot be read", has the four steps.
- If the managed knowledge base type fails in a way you cannot fix, the last paragraph of README section 4 has the fallback (`KB_TYPE=s3vectors`, after a teardown).

## What to write down
`RESULTS_TEMPLATE.md`, as you go. Leave a cell blank rather than guess. README section 6 lists each number and the file or line it comes from.

## Where the rest is
README section 2: twenty problems, with every price. Section 3: before you start, in full. Section 4: what to look at after each step. Section 5: every exit code of teardown and the clean check. Section 6: what to record. Section 7: what you can and cannot say afterwards. Section 8: what was and was not tested.
