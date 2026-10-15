# Kit C: start here

## What this is
A small LangGraph agent with two Federal Register tools, supplied by the kit.
You run it on your laptop against a model on Amazon Bedrock, then host the same graph on Amazon Bedrock AgentCore Runtime.
Then you read what each session used, delete everything, and check that nothing is left. This page is the order of work; `README.md` is the reference.

## What it costs, and the one thing that stops the bill
Cents, at prices read 2026-10-07: model tokens for every question (Nova Micro: $0.035 per 1M input tokens and $0.14 per 1M output tokens), and each hosted session while it exists, memory also while idle. A session that is never stopped costs at most $0.064 at the kit's settings. None of this was measured on a bill.
The one thing that stops the bill is `python 90_teardown.py`, run by you. A budget alarm (`../common/budget_alarm.py`) sends email; it stops nothing.

## Before you start
1. An AWS account on the Paid plan (an account on the Free plan cannot run the hosted half) and a role or user that is not the root user: README section 3, step 1.
2. AWS CLI version 2, and a sign-in. With IAM Identity Center:
```
aws configure sso                         # once: asks for your start URL, Region, account and role
aws sso login --profile <profile name>    # each day, or when the session has expired
export AWS_PROFILE=<profile name>         # so the kit's scripts use that sign-in
aws sts get-caller-identity               # check: the account shown must be the one you mean
```
3. No quota request is needed. Run `echo $AWS_REGION`: if your shell already exports a Region, that value wins over `config.env`.
4. Python 3.11 or newer and `uv`, then:
```
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp config.example.env config.env      # then edit if you need to
```

## Problems first
1. Nothing in this kit has been run against AWS, and the kit has never called a model: expect to fix something on first contact.
2. The answer check compares identifiers and figures and does not read meaning: a returned document presented as the thing you asked for passes with no warning.
3. A warning means "not found in the tool results of this run", not "false", and a number the model worked out correctly can draw one.
4. What was measured used stand-in models, not the kit's default, so how often your model misleads is not known until you count it.
5. A session bills while it exists, and Transaction Search, if you turn it on for traces, is account-wide and stays on after teardown.
6. Never delete, edit, move or rename `.state.json` while anything may be deployed: it may be the only record of where a runtime is billing.

## The commands, in order
Every script takes `--dry-run`, which prints the AWS calls and makes none. The first three commands need no AWS. The fifth is the first that bills. Under the commands: the last line of each.
```
python -m pytest -q
python 10_run_local.py "final rules about energy storage" --fake-model
python 12_serve_local.py --fake-model --self-test
python 00_check.py
python 10_run_local.py "What final rules mentioning artificial intelligence were published in the last 30 days, and by which agencies?" --i-understand-this-bills
python 20_package.py
python 30_deploy.py --dry-run
python 30_deploy.py --i-understand-this-bills
python 40_enable_observability.py --dry-run
python 40_enable_observability.py --i-understand-this-bills
python 50_invoke_hosted.py --dry-run
python 50_invoke_hosted.py --i-understand-this-bills
python 60_read_usage.py --show-logs
```
- `pytest`: a count followed by `passed`, with no `failed`. `12_serve_local.py`: `SELF-TEST PASSED`. `00_check.py`: `PREFLIGHT OK with N warning(s).`
- Both `10_run_local.py` runs: `Wall-clock seconds: ...`, and under it one more line with the words `(repeated from above` when the check warned or withheld the model's text.
- `20_package.py`: `Next: python 30_deploy.py --dry-run`. Each `--dry-run` after it: a line that starts `DRY-RUN complete: no AWS call was made`. `30_deploy.py`: a line that starts `Next:` and one more command under it, below a line that starts `Deployed at`. `40_enable_observability.py`: a line that ends `Next: python 50_invoke_hosted.py --dry-run`.
- `50_invoke_hosted.py`: `teardown deletes the log group that holds the usage records.` Exit code 1 means a call failed or its answer was warned or replaced: read the lines marked `FLAGGED`.
- `60_read_usage.py`: a line that starts `RESULT:`. Run now, it says `RESULT: NOT CROSS-CHECKED`, because usage data can arrive up to 60 minutes late. Run it again after 60 minutes, until it starts `RESULT: CROSS-CHECKED`, unless it says that cannot change however long you wait; then go on. Leave the runtime deployed while you wait.

## Tear down and prove it
```
python 90_teardown.py --dry-run
python 90_teardown.py
python 99_verify_clean.py
python ../common/whats_running.py --region <the AWS_REGION in your config.env> --prefix <your KIT_PREFIX>
```
- The dry run ends with a line that starts `Exit code 3, not 0`. The teardown ends `Now prove it: python 99_verify_clean.py`, and the line above that must start `Teardown finished without errors.`, or `Teardown finished.` when a first call to stop a session failed and a second one was answered (it says so).
- The clean check must end with a line that starts `RESULT: CLEAN` and names the account (last four digits), the Region and the prefix you deployed with. The shared audit's `RESULT:` line must say `nothing that bills while idle was found, and every check ran (exit 0)`.
- Exit code 0 is not enough: read each of those lines. Then check Billing and Cost Management the next day.

## If something goes wrong
- The file never to touch: `.state.json`. No script of the kit moves, renames, deletes or rewrites one it could not read.
- The script to run, whatever failed: `python 90_teardown.py`, then `python 99_verify_clean.py`. Teardown is safe to run twice. Any ending other than `Teardown finished without errors.` says what is left or what failed.
- A script that prints `STOPPED` and exits with code 4 found another Region, prefix or account in `.state.json` than the one in use (run the command its message gives), or could not read the file. Then, to tear down anyway, name the place: `python 90_teardown.py --region <Region> --prefix <prefix>`. That run says `TEARDOWN INCOMPLETE` and exits with code 5 even when every delete worked; README section 5 says what to check next.

## What to write down
`RESULTS_TEMPLATE.md`, as you go: copy each figure from the line a script prints, and do not time anything by hand. Then read ten answers by hand against the block (README section 6).

## Where the rest is
README section 2: what can go wrong, and the prices. Section 3: before you start, in full. Sections 4 and 5: every command explained, and every ending of teardown and the clean check. Section 6: what to record. Section 7: what you can and cannot say afterwards. Section 8: what was and was not tested, and 17 unverified details with what to do about each.
