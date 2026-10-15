# Spine for the three AWS build kits (pinned before any kit was written)

Purpose: three small, cheap, hands-on AWS builds that one person runs alone in their own AWS account, so that what they later say about the work is first-hand. The kits are written WITHOUT an AWS account: nothing here has been run against AWS. Every kit must say so, and say exactly what was and was not tested.

## Layout (one writer per folder; never write outside your own folder)
- common/                      shared safety scripts (budget alarm, "what is running and billing" audit)
- kit_a_gpu_endpoint/          open-weights model on one SageMaker AI GPU endpoint, invoked, load-tested, deleted
- kit_b_federal_rag_eval/      retrieval over the OMB federal AI use case inventory, guardrail, judged evaluation
- kit_c_langgraph_agentcore/   a LangGraph agent with a Federal Register tool, run locally, then on AgentCore Runtime

## Every kit folder contains
- README.md with exactly these headings, in this order:
  1. What this is
  2. Problems first            (billing traps, quotas, anything that can go wrong; each price with its source page, Region and the date read)
  3. Before you start          (the steps only the account owner can do: sign-in, quota request, model access, budget)
  4. Run it                    (numbered commands)
  5. Tear it down and prove it (teardown command, then the command that proves nothing is left)
  6. What to record            (the numbers to write into RESULTS_TEMPLATE.md)
  7. What you can truthfully say afterwards, and what you cannot
  8. What was and was not tested (SAFE: what ran here offline, as a count. NOT RUN: every AWS call. UNVERIFIED: every API shape not confirmed in a current AWS doc)
  9. Sources                   (each URL with the date read)
- requirements.txt (pinned to versions that exist today; say how you checked)
- config.example.env
- scripts named NN_verb.py in run order: 00_check.py (read-only preflight: identity, Region, quota, model access), 10_... deploy steps, 50_... use/measure steps, 90_teardown.py, 99_verify_clean.py
- RESULTS_TEMPLATE.md (blank table for the owner's real numbers: date, Region, instance or service, model, measurements, dollars billed, hours run, teardown verified)
- tests/ runnable offline with `python -m pytest -q` and no AWS credentials (botocore Stubber or plain fakes; no network)

## Rules for every script
- Python 3.11+, boto3. Region from AWS_REGION (default us-east-1). Resource names start with KIT_PREFIX (default "kitdemo"); every resource is tagged project=aws-kits where the API takes tags.
- Any script that creates a billable resource refuses to run without the flag --i-understand-this-bills, and prints the hourly or per-unit price it expects (with the source and date) before acting.
- Every script takes --dry-run, which prints the API calls it would make and makes none.
- Created resource names and ARNs go into .state.json in the kit folder; teardown reads it; 99_verify_clean.py lists by prefix and tag as well, so a lost state file does not hide a resource.
- Every AWS API call in code carries a comment: the doc URL and the date it was read. A parameter or API shape you could not confirm in a current AWS doc is marked `# UNVERIFIED:` and repeated in README section 8. Do not guess silently.
- No credentials, account ids, names of people, or personal information anywhere. No secrets in files. No em dashes in prose.
- Prices: only as quoted from an AWS page or price file read today, with Region and date. Never from memory.
- Plain, short prose. Problems before good news.
