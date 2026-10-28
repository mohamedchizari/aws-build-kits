# Kit C: a LangGraph agent with Federal Register tools, run locally, then on Amazon Bedrock AgentCore Runtime

First run: read `START_HERE.md`, one page with every command in order.

## 1. What this is

A small LangGraph agent with two tools over the public Federal Register API
(search documents; fetch one document by number). You run it on your own
machine against a model on Amazon Bedrock, then host the same graph on Amazon
Bedrock AgentCore Runtime, call it in several sessions, read back what each
session used and cost, delete everything, and check that nothing is left.

It is for one person working alone in their own AWS account who already builds
agents with LangGraph and has not used AgentCore. The agent code is ordinary
LangGraph and is supplied by the kit. The new part, and the part you do, is
the AWS part.

Why AgentCore and not Bedrock Agents: Amazon Bedrock Agents is now "Amazon
Bedrock Agents Classic" and has been closed to new customers since 30 July
2026, and AWS recommends AgentCore in its place (source 1 in section 9).

What is in the folder:

| Path | What it is |
|---|---|
| `agent/fr_tools.py` | the two tools as plain functions: validation, timeouts, a User-Agent, small result caps, "the last N days" worked out in code, a mark on every field that was cut short, an error when a response lacks the fields it should have, a fixed sentence in every search result that its total counts matches of the search words, and for each result a count of how many of the search words stand in its title and its abstract (the words of the search term other than a, about, an, and, as, at, by, for, from, in, of, on, or, the, to, with) |
| `agent/graph.py` | the graph: model, tools (at most three tool calls per model turn), and a `finalize` node with no model in it. It builds the first part of every answer from the tool results in code, and compares the numbers, dates, URLs and counts in the model's text with those results. It does not check the model's wording, and it does not check whether a document the model lists is what you asked for (section 2) |
| `agent/model.py` | the Bedrock binding: `langchain_aws.ChatBedrockConverse`, model id from `MODEL_ID` |
| `agent/fake_model.py` | fake chat models for offline runs |
| `agentcore_app.py` | the hosted entrypoint: `BedrockAgentCoreApp` and one `@app.entrypoint` function |
| `00_check.py` | read-only preflight: identity, Region, model access, AgentCore reachable |
| `10_run_local.py` | one question through the graph on your machine |
| `12_serve_local.py` | the hosted entrypoint served on localhost:8080 (the documented local test) |
| `20_package.py` | builds the arm64 zip from a lock file and makes it portable. No AWS call |
| `30_deploy.py` | S3 bucket and zip, IAM role, AgentCore runtime |
| `40_enable_observability.py` | usage logs, application logs and traces to CloudWatch |
| `50_invoke_hosted.py` | several sessions, whole-call time per call, every warned or replaced answer flagged, every session stopped afterwards |
| `60_read_usage.py` | vCPU-hours and GB-hours per session, cross-checked against CloudWatch metrics no earlier than 60 minutes after the last session, and the cost |
| `90_teardown.py` | deletes what the kit created in the Region and under the prefix in use, found by name prefix and not only from the state file. Exit code 0 only when nothing of the kit was seen left over |
| `99_verify_clean.py` | read-only check: `RESULT: CLEAN` and exit code 0 only when nothing is left where it looked, and it says where it looked |
| `kitlib.py`, `kit_resources.py` | shared plumbing: config, the state file, dry-run, prices, discovery and deletion |
| `requirements-runtime.lock.txt`, `requirements-runtime-no-otel.lock.txt` | every package in the hosted zip, pinned (Python 3.13) |
| `optional_gateway/` | extra: one Federal Register endpoint as an MCP tool behind AgentCore Gateway |
| `tests/` | 1033 offline tests and four recorded Federal Register responses |
| `START_HERE.md` | the one-page order of work: every command, and the last line to expect from each |
| `RECORD_OF_REVIEWS.md`, `REVIEW_NOTES_r4.md`, `REVIEW_NOTES_r5.md` | the history: the four review rounds, what this README said before it was shortened, and rounds 4 and 5 finding by finding |

How the hosting works, in three sentences. AgentCore Runtime runs your code
in a microVM per session and expects an HTTP server on port 8080 with
`POST /invocations` and `GET /ping`; the `bedrock-agentcore` package provides
that server. This kit uses "direct code deployment": a zip of your code and
its arm64 dependencies in S3, one IAM role, and one `CreateAgentRuntime` call
through boto3, which is the route AWS's own current LangGraph sample takes.
There is no Docker image, no ECR repository and no CodeBuild project.

One difference from that sample: it starts the agent as plain `agent.py`. This
kit's default start command is `opentelemetry-instrument agentcore_app.py`,
the example on AWS's direct code deployment page, which is what makes traces
exist. Section 8, item 1, has what can go wrong with it and the fallback.

## 2. Problems first

**Nothing in this kit has been run against AWS, and the kit has never called a
model.** Every AWS call was written from AWS documentation, AWS's sample code
and the SDK's request definitions. The default model, Amazon Nova Micro, has
never seen the prompt or the tools. Expect to fix something on first contact.

**The answer check compares identifiers and figures. It does not read
meaning.** Every answer starts with a block built by code, headed `FROM THE
FEDERAL REGISTER API`. Then come `WARNING:` lines for the checks that failed,
`NOTE:` lines, and the model's text under the label `MODEL'S SUMMARY`.
Compared with the tool results: document numbers, Federal Register citations,
other numbers of two or more digits, dates, URLs, counts of documents, and
phrases of two or more words in quotation marks. Not checked: wording, titles
and descriptions unless quoted, which agency did what, whether a document it
lists is about what you asked, single digits, numbers written as words, a
two-digit ordinal, two digits after letters ("FY27"), and anything else with
no digits in it.

So these pass with no warning: a returned document presented as the thing you
asked for when its title says otherwise, "the newest" that is not, "nothing
else was published", a wrong agency, a real number attached to the wrong
document, an invented rule with no number. A warning means "not found in the
tool results of this run". It does not mean "false", and no warning does not
mean "true". Open each URL in the block before you rely on an answer.

**What was measured on real model text, limits first.** The writers were
stand-in models (Claude Haiku and Claude Sonnet), not the kit's default. Each
ran inside its own agent harness, read the prompt as a text file, called the
tools from a shell, took ten questions in one context, and knew it was a test.
What the check catches in a misleading answer that a model wrote with its own
tool calls has not been measured: the 88 answers below held none. Blind
readers labelled each answer. Claude Haiku, on the same 30 questions:

| Who chose the tool calls | System prompt | clean | minor | misleading | answers |
|---|---|---|---|---|---|
| the preparing agent | as before round 3 | 10 | 7 | 13 | 30 |
| the preparing agent | rewritten in round 3 | 11 | 7 | 12 | 30 |
| the model itself | as before round 3 | 21 | 8 | 1 | 30 |
| the model itself | rewritten in round 3 | 22 | 7 | 0 | 29 (1 conversation ended at the kit's step limit) |

An earlier version of this README gave the first two rows as the smaller
model's own error rate, and said that rewriting the system prompt did not fix
it and that the choice of model mattered more than the prompt or the check.
That was wrong. Those rows are the round 3 rehearsal, whose tool calls were
chosen in advance by the agent that prepared it: the model was handed the
results of searches it had not written, often a single search whose matches
were mostly off topic. In the kit the model writes its own searches and can
search again. When it did, in round 4, through the kit's real tools against
the live Federal Register API, it misled in 0 or 1 of 30 answers, not 12 or
13. The rewritten prompt made little difference in either condition (13
against 12; 1 against 0). The last two rows had one reader per answer. The
readers did not get easier: a fresh reader gave 27 of 30 rehearsal answers the
label they had before, and called 5 misleading where 5 had been.

On 30 new questions, with the model's own tool calls and the rewritten prompt,
two readers each: Claude Haiku 23 or 24 clean, 7 or 6 minor, 0 misleading of
30; Claude Sonnet 25 clean, 4 minor, 0 misleading of 29 (1 conversation ended
at the step limit). The readers agreed on 58 of 59 answers. How often your
model misleads is not known until you count it (section 6).

**The check on 88 answers it had not seen** (the 59 and the 29 above). Bad
news first: none of the 88 was misleading, so this set says nothing about what
the check catches. The only misleading real answers the check has met are the
rehearsal's 25, and it passes 15 of those 25 with no warning.

| Reader's label | passed | warned | replaced |
|---|---|---|---|
| clean (70) | 59 | 6 | 5 |
| minor (18) | 16 | 2 | 0 |
| misleading (0) | 0 | 0 | 0 |

Of the 8 warnings, 4 say a tool call failed, and one did; 1 flags a date and a
time taken from the visible part of a field the tool had cut short; 3 flag
"number(s) that appear in no complete field of a tool result" which the model
had worked out correctly. The warning says they "may be invented, worked out
by the model, or taken from a field the tool cut short", but on a correct
figure it reads as an accusation: 3 of 88, about 1 time in 30. The 5 replaced
answers each followed a search that returned nothing, after which the kit
always shows fixed text. And the step limit can end a conversation with no
answer: 2 of 90 stand-in conversations under the current prompt ended at the
kit's limit of 12 graph steps with "No answer was produced."

**What can cost money.** Prices read 2026-10-07 (sources 2, 25, 40); the
AgentCore pricing page gives one Runtime price with no Region column. The risk
is something left running. No quota request is needed (source 12).

| What bills | Price, or the most it can cost |
|---|---|
| A session, while it exists; memory also while idle | Platform version V1, the default: $0.0895 per vCPU-hour and $0.00945 per GB-hour. V2, if enabled for your account and Region: $0.1276 and $0.0169. The kit sets 120 seconds idle and 900 of life, and stops every session it opens |
| A session that is never stopped | At most 900 / 3600 x (2 x $0.0895 + 8 x $0.00945) = $0.064 on V1 ($0.098 on V2). At the service defaults of 900 and 28,800 seconds the same sum over 8 hours is $2.04 ($3.12) |
| Model tokens, a separate Bedrock charge, local runs included | In us-east-1, us-east-2 and us-west-2: Nova Micro $0.035 per 1M input tokens and $0.14 per 1M output tokens; Nova 2 Lite $0.33 and $2.75 (`global.` profile: $0.30 per 1M input tokens and $2.50 per 1M output tokens; none held for Nova Micro). What a question costs was not measured |
| CloudWatch logs, spans and metrics | CloudWatch's own rates, not quoted here. Application logs store your questions and the answers; they are skipped unless you pass `--include-app-logs`. An existing application-log delivery remains enabled until teardown. Transaction Search is account-wide and stays on after teardown |

**State.** Never delete, edit, move or rename `.state.json` while anything may
be deployed: it may be the only record of where a runtime is billing, and
without it teardown and the clean check look in one Region under one prefix
only. An exported AWS_REGION overrides `config.env`. In round 4, on a fake
account, the three kits and the shared audit said "clean" wrongly in 34 of 377
sequences; with the state file intact, in 1 of 244.

**Things that can go wrong** on the first run. Section 8 has each with its
switch: the start command and `ENABLE_OTEL=false` (item 1), the role and
`EXECUTION_ROLE_S3_READ=true` (item 11), the model and `MODEL_ID` (item 12).
Anthropic models need a one-time use-case form; the default needs none.
`RECORD_OF_REVIEWS.md` has the full list, and every rule of the check.

## 3. Before you start

Only the account owner can do these.

1. Have an AWS account on the Paid plan: the AWS Free Tier offers list marks
   Amazon Bedrock AgentCore "Paid plan exclusive" (source 3, read 2026-10-07),
   so an account on the Free plan cannot run the hosted half. You need a role
   or user that may create and delete IAM roles, S3 buckets, CloudWatch log
   groups and deliveries, and AgentCore runtimes, and may invoke Bedrock
   models. An administrator role through IAM Identity Center is the simple
   choice for a personal sandbox account. Do not use the root user. AWS's
   managed policy for the AgentCore part is `BedrockAgentCoreFullAccess`.
2. Install the AWS CLI, version 2, and sign in on your machine. With IAM
   Identity Center the documented steps are (source 36):

       aws --version
       aws configure sso                         # once: asks for your start URL, Region, account and role
       aws sso login --profile <profile name>    # each day, or when the session has expired
       export AWS_PROFILE=<profile name>         # so the kit's scripts use that sign-in
       aws sts get-caller-identity               # check: the account shown must be the one you mean

   The kit reads credentials the way every AWS SDK does. It never asks for
   them and no secret goes in any file.
3. Set a budget alarm first with `../common/budget_alarm.py` (see
   `../common/README.md`; an alarm sends email, it does not stop anything).
4. Decide the Region (default us-east-1). Run `echo $AWS_REGION`: if your
   shell already exports one, that value wins over `config.env`. Check the
   model's access state in the Bedrock console's model catalog if you change
   the model.
5. If you change the model or the Region, look up the model's token prices on
   https://aws.amazon.com/bedrock/pricing/ (they are per 1M tokens) and note
   them with the date. For the default model in us-east-1, us-east-2 or
   us-west-2 the prices are in section 2 and built into `60_read_usage.py`.
6. Optional, for traces only: turn on CloudWatch Transaction Search. In the
   CloudWatch console open Application Signals (APM), Transaction search,
   choose Enable Transaction Search, tick the box to ingest spans as
   structured logs, and save. It is account-wide, stays on after teardown, and
   spans can take 10 minutes to appear.
7. On your machine: Python 3.11 or newer (3.13 is what the hosted runtime
   uses), `uv` (https://docs.astral.sh/uv/getting-started/installation/), then

       python -m venv .venv && . .venv/bin/activate
       pip install -r requirements.txt
       cp config.example.env config.env      # then edit if you need to

No quota request is needed.

## 4. Run it

Every script takes `--dry-run` (prints the AWS calls, makes none) and `--help`.
Every script that bills refuses to run without `--i-understand-this-bills` and
prints the price it expects first.

1. Offline tests. No AWS, no network.

       python -m pytest -q

2. The graph with the fake model. No AWS; the Federal Register call is real.
   Look at the parts of the answer: the block built by code, with its `Search
   words` line under each document, then the model's text under its label.

       python 10_run_local.py "final rules about energy storage" --fake-model

3. The hosted entrypoint on localhost, fake model. No AWS.

       python 12_serve_local.py --fake-model --self-test

4. Preflight. Read-only.

       python 00_check.py

5. The graph against Bedrock, on your machine. Bills model tokens. Read the
   line "Check of the model's text against the tool results" and any
   `WARNING:`. The last line printed repeats the warnings when there are any.

       python 10_run_local.py "What final rules mentioning artificial intelligence were published in the last 30 days, and by which agencies?" --i-understand-this-bills

6. Build the arm64 zip. No AWS.

       python 20_package.py

7. Deploy. Look at the dry run first.

       python 30_deploy.py --dry-run
       python 30_deploy.py --i-understand-this-bills

8. Send usage logs and (if Transaction Search is on) traces to CloudWatch. Application logs, which contain prompts and answers, are an explicit opt-in. Safe to run again if it stops half way.

       python 40_enable_observability.py --dry-run
       python 40_enable_observability.py --i-understand-this-bills
       python 40_enable_observability.py --i-understand-this-bills --include-app-logs

9. Call the hosted agent: five sessions, the same question twice in each,
   every session stopped afterwards. A call whose answer was warned or
   replaced, or that reports a tool error, is listed with its warnings first
   and counted as failed, and the script then exits 1. The script prints when
   it started and finished (UTC) and the earliest time a usage read can be
   final.

       python 50_invoke_hosted.py --dry-run
       python 50_invoke_hosted.py --i-understand-this-bills

10. Read usage and cost. Makes no change in AWS. Usage data can arrive up to
    60 minutes after a session ends. Run this now to see that records arrive;
    it will say `RESULT: NOT CROSS-CHECKED` because it is early. Run it again
    once 60 minutes have passed since the last session, and repeat until its
    last line starts `RESULT: CROSS-CHECKED`. For a model other than the two
    this kit names, add `--input-usd-per-1m <price> --output-usd-per-1m
    <price>` with its prices per 1M tokens.

        python 60_read_usage.py --show-logs

    Leave the runtime deployed while you wait. Do not go on to section 5 while
    the last line says `RESULT: NOT CROSS-CHECKED`, unless it says that cannot
    change however long you wait (step 8 skipped, a session with no end time).

11. Look at the same sessions in the console: CloudWatch, GenAI Observability,
    the Bedrock AgentCore tab (Agents, Sessions, Traces views), at
    https://console.aws.amazon.com/cloudwatch/home#gen-ai-observability . The
    runtime's own output is in the log group
    `/aws/bedrock-agentcore/runtimes/<runtime id>-DEFAULT`.

12. Optional: the gateway step. See `optional_gateway/README.md`.

## 5. Tear it down and prove it

Read your usage first (step 10): teardown deletes the log groups that hold it.

    python 90_teardown.py --dry-run
    python 90_teardown.py
    python 99_verify_clean.py

What teardown will not do, first.

- It works in one place: the Region and the name prefix in use, in the
  account you are signed in to. It does not go looking in other Regions.
- It deletes only the S3 bucket named exactly for this account and this
  Region (`<prefix>-kitc-code-<account>-<Region>`). `ListBuckets` shows the
  buckets of every Region; a bucket with the kit's name for another Region is
  printed with its Region and left alone, because a deploy may be live there
  and reads its code from it.
- One IAM role name serves every Region. The role is deleted only when no
  bucket of this kit exists for another Region and no runtime or gateway of
  this kit is found in any other Region the script can name: the Regions in
  the role's own trust policy and in `.state.json`'s history. If one of those
  Regions cannot be checked, the role is kept. It cannot see a Region that
  none of those three sources name.
- It never moves, renames, deletes or rewrites a `.state.json` it could not
  read.
- `--dry-run` deletes nothing and exits 3, not 0.

`90_teardown.py` first compares `.state.json` with the settings in use. If the
file records a deploy in another Region, under another prefix or in another
account, cannot be read, or names resources without saying where they are, it
stops with exit code 4 and deletes nothing; remember that an exported
AWS_REGION overrides config.env. If it records another place, run the command
the `STOPPED` message gives. If it cannot be used, name the place, both values:

    python 90_teardown.py --region <Region> --prefix <prefix>

That run works by name only, in that one Region, and leaves the file exactly
as it is. Its verdict line starts `TEARDOWN INCOMPLETE` and its exit code is
5, not 0, even when every delete worked: the file that would say where else
the kit was deployed could not be used. The clean check stays `RESULT:
INCOMPLETE` until you have checked every Region you used and moved the file
out of the kit folder yourself.

Otherwise it finds resources by this kit's name prefix in every service the
kit touches, so it also works when `.state.json` is lost, in the Region and
under the prefix in use. It stops any session still recorded as open, then
deletes log deliveries, the gateway and its target if you made them, the
runtime, any workload identity left behind, the log groups, the bucket with
its objects (every version and delete marker), and the IAM roles. It is safe
to run twice. It ends with a verdict line and then `Now prove it: python
99_verify_clean.py`. The verdict also says "this is not proof for any other
Region, prefix or account" when no deploy was recorded in a usable state file:

| Verdict line starts | Exit code | What it means |
|---|---|---|
| "Teardown finished without errors", or "Teardown finished." with "The first call to stop" | 0 | everything recorded or named here was deleted or confirmed absent, and the listing by name showed nothing else of this kit. So did the listing by tag, unless a `NOTE:` line above says it could not be read (then 99_verify_clean.py says NOT VERIFIED). The second form: a session's first stop call failed; asked again once the runtime was gone, the service answered that it is stopped or does not exist |
| "Teardown finished, BUT n resource(s) of this kit remain" | 1 | a listing showed something of this kit that this run did not delete, for example another Region's bucket. Each is listed, with the command to run for it |
| "Teardown finished, BUT it cannot say this kit is gone" | 1 | there was no record of a deploy and the tag listing could not be read |
| "Teardown finished WITH ERRORS" | 1 | a call failed, and `.state.json` was left as it was. A session that could not be stopped counts, and a line starting `NOT STOPPED` says what it can cost |
| `TEARDOWN INCOMPLETE` | 5 | every delete worked, but the state file could not be used, so the run cannot say where else the kit was deployed (see above) |

`99_verify_clean.py` is the check. It lists by name prefix and, separately, by
the tags `project=aws-kits` and `kit=kit-c`, in the Region and prefix in use
and in every other Region and prefix that `.state.json`'s history names for
the account you are signed in to. A runtime or gateway that the file records
as live is also asked for by id. Its last line starts `RESULT:`, names the
account (last four digits), the Regions and the prefixes it checked, and ends
with the time of the check in UTC and the exit code. With `--dry-run` it exits
3, not 0, because a dry run proves nothing.

| Last line starts | Exit code | What it means |
|---|---|---|
| `RESULT: CLEAN` | 0 | nothing found anywhere it looked, and nothing it could not look at. Every such line says it is not proof for any other Region, prefix or account |
| `RESULT: NOT CLEAN` | 1 | something is left, listed above the line with where it is and the command that removes it |
| `RESULT: NOT VERIFIED` | 1 | a lookup failed, so a permissions error cannot pass for a clean account |
| `RESULT: INCOMPLETE` | 5 | nothing found where it looked, but the state file names another account, cannot be read or does not say where its resources are, or a `.state.json.damaged-*` file is still in the folder |
| `RESULT: INCOMPLETE` | 4 | nothing was checked: the file records a live deploy somewhere other than the settings in use |

What `RESULT: CLEAN` does not cover: a Region or prefix that this machine's
`.state.json` never recorded, for example a deploy made from another computer
or before the state file was deleted. If you deployed anywhere like that,
run the check there too: `AWS_REGION=us-west-2 python 99_verify_clean.py`.

What teardown leaves: Transaction Search and the `aws/spans` log group if you
turned them on, CloudWatch metrics already published, your model access, and
the local zip in `.build/` (`--clean-local` removes it).

For a second check that does not depend on this kit's code, run the shared
audit with the same Region and prefix:

    python ../common/whats_running.py --region <the AWS_REGION in your config.env> --prefix <your KIT_PREFIX>

The bill is the final word. Check Billing and Cost Management the next day.

## 6. What to record

Write these into `RESULTS_TEMPLATE.md` as you go. Every row there that asks
for a time or a duration quotes the words of the line a script prints, so
copy the figure from that line; do not time anything by hand.

| When | What to write down |
|---|---|
| Before | Date, Region, the account's last four digits, model id, the platform version (reported by the service, or assumed), package versions and zip size |
| Local run | The question, the tool calls, every `WARNING:` line, tokens and seconds, and one thing you checked by opening a URL from the block |
| Deployment | The two `[timing]` lines, and whether the OpenTelemetry start command worked |
| Hosted calls | When the run started and finished, the whole-call time of each first call and of each repeated call, and every failed or flagged call with its warnings |
| Usage | The last line of `60_read_usage.py` word for word, the line that starts "This read:", whether `--accept-early-read` was used, and the runtime cost if and only if it was cross-checked and not read early |
| Teardown | Its verdict line and exit code, the line "The runtime existed for", the last line of `99_verify_clean.py` word for word, and what the shared audit listed |
| A day later | From the bill: dollars for AgentCore, for Bedrock model use, for CloudWatch and S3. And which UNVERIFIED items in section 8 turned out right or wrong |

Ten answers read by hand against the block. No script does this. Ask 10
different questions of your own with `10_run_local.py` (each is one more model
run, billed per token). Read each answer against the block above it and write
down how many made a claim of one of three kinds that the block does not
support: that a document is about what you asked, that a document is "the
newest", "the latest" or "the most recent" of its kind, or that nothing else
exists ("only", "no other"). Write down how many of those answers carried a
`WARNING:` line, and how many carried a `WARNING:` that was wrong. Section 2
has such figures for two stand-in models; yours are the first for the model
you ran.

## 7. What you can truthfully say afterwards, and what you cannot

After a complete run with your own numbers recorded, you can say:

- You deployed and operated an agent that the kit supplied: a LangGraph
  tool-calling graph that you read and ran against a model on Amazon Bedrock
  through the Converse API, and then hosted on AgentCore Runtime using direct
  code deployment with boto3. If you changed the graph or the tools, say what
  you changed.
- You ran a script that created an execution role based on AWS's documented policy.
- You served the hosted entrypoint on your own machine and saw the contract it
  serves (`POST /invocations` and `GET /ping` on port 8080; the self-test of
  step 3 makes both calls for you), you built and uploaded an arm64 zip, and
  you worked with sessions: one microVM per session, a session id of at least
  33 characters, the idle timeout and maximum lifetime you set, and what
  `StopRuntimeSession` is for. The SDK hides the rest of the contract from
  you.
- You timed first and later calls end to end from your machine, for this
  agent, in your Region, on the date you ran it, over a handful of sessions.
  That figure includes the network, the model and the Federal Register. It is
  not a measured cold start.
- You read per-session vCPU-hours and GB-hours from the usage logs and, if
  the script's last line said `CROSS-CHECKED` without the words "read early",
  turned them into a cost that agreed with the CloudWatch metrics within 10%,
  read at least 60 minutes after the last session. Quote it with the
  platform version, and say so if that version was assumed. If the line did
  not say that, you have no session cost to quote.
- You tore the deployment down and ran a check that found nothing under your
  prefix in the Regions and the account its result line names. If that line
  says no state file was found, say that too.
- If you did the optional step: you put an OpenAPI operation behind AgentCore
  Gateway and called it as an MCP tool.

You cannot say, on the strength of this kit:

- That you designed or wrote the agent. The kit did.
- That you ran an agent in production, at scale or under load. This is a
  handful of sessions.
- That the agent's answers are correct, or were evaluated. What you can say is
  narrower: each answer began with a list of documents built by code from the
  API's own fields, and the model's text was compared with the tool results
  for document numbers, Federal Register citations, other numbers of two or
  more digits, dates, URLs, counts of documents and phrases in quotation
  marks. Its wording, which agency did what, single digits and anything else
  with no digits in it were not checked, nor were numbers in words, two-digit
  ordinals and two digits that follow letters. Before your run the check had
  met real answers from two stand-in models only, not from the model you ran.
  Of 120 written from tool calls an agent had chosen for them, readers called
  25 misleading, and the check as it is now passes 15 of those 25 with no
  warning. Of 88 written with the models' own tool calls, readers called none
  misleading, so those say nothing about what the check catches.
- That an answer the check passed is right. A pass means that the numbers and
  identifiers in the model's text were found in the tool results. It says
  nothing about relevance, about "the newest", or about completeness.
- That a document the agent listed is about what you asked, that "the newest
  rule on X" in an answer is that, or that nothing else was published. No rule
  in the kit checks these. The block gives you each title and a count of
  search words to look at; the looking is yours. What you can say is what you
  counted by hand (section 6): of the 10 answers you read, how many made such
  a claim that the block does not support.
- That the prompt or the check makes a model safe to use. The kit's default
  model has never been called.
- That the choice of model matters more than the prompt or the check, or that
  rewriting the prompt failed to fix a smaller model. An earlier version of
  this README said both, from a rehearsal in which the tool calls were chosen
  for the model in advance. What you can say: with tool calls chosen in
  advance a stand-in model (Claude Haiku) misled in 12 or 13 of 30 answers,
  with its own in 0 or 1 of 30 on the same questions, and the rewritten prompt
  made little difference in either condition. Say with it: a stand-in in its
  own harness, one reader per answer where it chose its own tool calls, not
  the model you ran.
- That the warnings are reliable on your model's text. On 88 stand-in answers
  the check had not seen it warned 8: 4 for a tool call that did fail, 1 for a
  date and a time taken from the visible part of a cut field, and 3 for a
  number the model had worked out correctly.
- That a count in an answer is a count of documents on a topic. A total from
  the search is a count of documents that match the search words.
- That the agent cannot invent a document or a claim. It can, in words.
- That you measured a cold start, or a latency distribution.
- That your account is clean beyond what the check's result line names. It
  looks under one prefix, in the Regions and the account it lists, and
  without a state file that is one Region.
- That you used the AgentCore CLI, the managed harness, a container
  deployment, AgentCore Memory, Identity with OAuth, Policy, Evaluations,
  Code Interpreter or Browser. None is in this kit.
- That you ran in a VPC, behind PrivateLink, in AWS GovCloud, or under any
  compliance boundary. The runtime here uses network mode PUBLIC in a
  commercial Region.
- That your latency or cost figures hold for other agents, models, Regions or
  dates. Quote them with their date and conditions.
- Anything about Bedrock Agents Classic from experience.
- Before you have run it: anything first-hand at all. Until then this is a
  kit that was written from documentation.

## 8. What was and was not tested

Everything here was done on 2026-10-07 in Linux workspaces with no AWS account
and no credentials of the owner's. Not done, first:

- Nothing has run against AWS, and the kit's default model has never been
  called. Stand-in models wrote answers in their own harness (section 2).
- Nobody independent has read the round 5 fix code. Each round so far has
  found defects in the round before (round 5 found 3 MAJOR here, all fixed).
- The answer check was corrected a fourth time on text it had just been shown.
  The 88 answers of section 2 are the only unseen evidence there is.
- One question can send up to 18 Federal Register requests (six tool turns
  of three before the step limit stops a model that never finishes). The
  comment in `agent/graph.py` said 15 until 7 Oct 2026; measured, then fixed.

**SAFE: what ran here**

- `python -m pytest -q`: 1033 passed, 0 failed on 2026-10-23 after the scoped-permission and log opt-in changes; the previous recorded run had 1031 passes. The network is blocked in tests.
  and AWS variables removed, on Python 3.13.16 and again on Python 3.14.6,
  each in a clean environment built from `requirements.txt` alone. 22
  test files. On the Mac (Python 3.14.7), before round 5: 993 passed; a
  first run there showed 2 tests that assumed `uv` was installed (changed).
- The graph ran end to end with scripted fake models, through the hosted
  entrypoint, the hosted caller and the local script, with the answer check,
  the cap of three tool calls per turn and the step limit. The entrypoint ran
  as an HTTP server on 127.0.0.1:8080: `GET /ping` and `POST /invocations`
  returned 200.
- `20_package.py` ran from the lock file: 119 pinned packages for arm64 Linux,
  54.0 MB zipped and 149.8 MB unzipped (44.3 MB with `ENABLE_OTEL=false`).
  Neither zip was started on arm64 or uploaded.
- The two tools ran against the live Federal Register API: in round 4 the
  stand-in models made 82 tool calls for 30 questions, and 99 and 105 for 30
  new questions.
- 14 of 14 scripts answer `--help` and `--dry-run` with the exit code they
  document, with no credentials and the network blocked. 7 of 7 billing
  scripts refuse to run without `--i-understand-this-bills`.
- Every AWS request the scripts build is checked against the service
  definitions in botocore 1.43.108. That shows a valid request, not what AWS
  answers.

**NOT RUN: every AWS call.** No request was sent to AWS by any script, test or
tool: not STS GetCallerIdentity; the Bedrock model lookups or Converse
(through `langchain-aws`, so the tool schemas have not met a model through
Bedrock); the S3, IAM and AgentCore create, get, list and delete calls; the
CloudWatch Logs delivery calls; InvokeAgentRuntime and StopRuntimeSession;
FilterLogEvents and GetMetricStatistics; the Resource Groups Tagging API; or
the gateway calls. The record names each, script by script.

**UNVERIFIED: details not confirmed in a current AWS document.** Each is also
marked `# UNVERIFIED:` in the code, and the record has each in full.

| Item | Not confirmed | What the kit does, or what to do |
|---|---|---|
| 1 | That the hosted runtime starts `opentelemetry-instrument` from the zip's `bin/` folder once its first line is `#!/usr/bin/env python3`. Not run on AgentCore | If the runtime fails to initialise: `ENABLE_OTEL=false`, `20_package.py` again, tear down, redeploy. You lose traces, not logs or usage |
| 2 | The JSON layout of a `USAGE_LOGS` record: the field names are documented, whether they are nested is not | The parser looks at any depth |
| 3 | That the log delivery source for a runtime takes the runtime ARN; whether a usage record is an increment or a running total; how often one is written | `60_read_usage.py` says `CROSS-CHECKED` only for a read at least 60 minutes after the last session, when the CloudWatch metric total agrees within 10% and the records cover at least 90% of each session. Otherwise you have no session cost to quote |
| 4 | Whether a span record carries the runtime session id as plain text | Either span count may read zero when traces exist; the console is the fallback |
| 5 | Whether AgentCore deletes a runtime's or a gateway's workload identity with its parent, and whether deleting a runtime ends its open sessions | Teardown lists again and deletes any identity left, and stops the sessions first |
| 6 | Which AgentCore resource types the Resource Groups Tagging API returns | The by-name checks do not depend on it |
| 7 | That a direct-code runtime reaches the server on 0.0.0.0:8080 | The kit passes that host through `KIT_BIND_HOST`; AWS's samples pass none |
| 8 | Optional gateway: that a service role with no permissions policy is enough for a public OpenAPI target; the SigV4 signing name `bedrock-agentcore`; that a new gateway accepts `MCP-Protocol-Version: 2025-11-25` without an `initialize` call; the tool name `federal-register___getAgency` | Nothing: the gateway step is optional |
| 9 | What a deployed runtime with no session really bills. The pricing page says its code bills at S3 Standard rates ($0.0023 a month for 100 MB); whether that adds to the copy in your bucket, and how "system overhead" shows in a session's usage, has not been seen on a bill | Tear down when you have your usage figure, and read the bill |
| 10 | CloudWatch's and S3's own rate tables: not read, not quoted. Token prices are held for Nova Micro and Nova 2 Lite only, in three US Regions | For another model give `60_read_usage.py` the two prices |
| 11 | Whether the execution role needs S3 access to the deployment package (two AWS pages disagree), and whether the narrowed model resources are sufficient for each runtime/profile | If the runtime cannot read the package: `EXECUTION_ROLE_S3_READ=true` in `config.env`, `90_teardown.py`, deploy again; if invocation is denied, inspect the exact resource ARNs and AWS's current runtime policy requirements |
| 12 | Whether Amazon Nova accepts the search tool's optional arguments as LangChain sends them, and whether Nova Micro fills them in well | If not: `MODEL_ID=us.amazon.nova-2-lite-v1:0` |
| 13 | That `GetAgentRuntime` echoes `platformVersion` and the lifecycle settings | Where it does not, every rates line says the version is ASSUMED |
| 14 | What the spans hold with `TRACELOOP_TRACE_CONTENT` set to `false`. The setting was read in the instrumentor's source; no span was produced here | Look at one trace before you rely on it |
| 15 | The error code AgentCore gives for a runtime or gateway that does not exist | For anything but `ResourceNotFoundException`, a recorded one that the listing did not show keeps its record, teardown exits 1 and the clean check says NOT VERIFIED; the list call decides only for one this run listed and deleted |
| 16 | That S3 `DeleteObjects` accepts the version id "null" for an object written before versioning was switched on | Sent only from the second round of emptying a bucket on |
| 17 | That the Federal Register API caps a search total at 10,000. Two live searches reported exactly that; its documentation states no ceiling | The tool passes such a total on with a note |

**The four rounds**, each under its own heading in `RECORD_OF_REVIEWS.md`:
"Round 1", the first independent review; "Round 2", the second, by three
readers; "Round 3", the rehearsal of the answer check on stand-in models'
text; "Round 4", the third review and the stand-in runs with the model's own
tool calls (`REVIEW_NOTES_r4.md` has it finding by finding).

## 9. Sources

Read on 2026-10-07. These are the sources this README cites, under their
numbers in the full list of 42 in `RECORD_OF_REVIEWS.md`.

| Source | What | Where |
|---|---|---|
| 1 | Bedrock Agents Classic maintenance mode | https://docs.aws.amazon.com/bedrock/latest/userguide/agents-classic-maintenance-mode.html |
| 2 | AgentCore pricing | https://aws.amazon.com/bedrock/agentcore/pricing/ |
| 3 | AWS Free Tier offers list | https://aws.amazon.com/free/ |
| 12 | AgentCore quotas | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html |
| 25 | Bedrock pricing, and the price file its tables are filled from (published 2026-10-06) | https://aws.amazon.com/bedrock/pricing/ and https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/bedrock/USD/current/bedrock.json |
| 36 | AWS CLI, configuring IAM Identity Center sign-in | https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html |
| 40 | AWS Price List file for Amazon Bedrock, us-east-1 (published 2026-10-06) | https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/current/us-east-1/index.json |
| 43 | Round 4 of the review, for the figures on stand-in models and the check (added after round 4) | `../_review_reports/round4/FINDINGS_round4.md` |
