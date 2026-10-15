# Results: kit C, LangGraph agent on Amazon Bedrock AgentCore Runtime

Fill this in from your own run. Leave a cell empty rather than estimate it.
Every number here should be one you can point to in a script's output, the
CloudWatch console or the bill.

Every row that asks for a time or a duration quotes, in double quotes, words
from the line a script prints. Copy the figure from that line. Do not time
anything by hand. All printed times are UTC.

## The run

| Item | Your value |
|---|---|
| Date of the run | |
| Region | |
| Account, last four digits only | |
| Service | Amazon Bedrock AgentCore Runtime, direct code deployment |
| Platform version: the one the service reported, or "ASSUMED" if the rates line of 30_deploy.py says so | |
| Idle timeout and maximum lifetime the runtime was deployed with, seconds | |
| Model id | |
| Kit prefix | |
| Zip size, MB zipped and unzipped (20_package.py) | |
| Versions pinned from a lock file (yes, and which file / no) | |
| Packages: langgraph, langchain-aws, bedrock-agentcore versions | |

## Local run (10_run_local.py)

| Measurement | Your value |
|---|---|
| Question asked | |
| Tool calls made (names and count) | |
| The searches as the block shows them (term, type, dates, and who chose the dates: the tool or the model) | |
| Total the API reported for each search, and how many documents it returned | |
| Check result printed (ok / warned / replaced / stopped) and its reasons | |
| Every WARNING line, word for word | |
| Every NOTE line, word for word (information, not a failed check) | |
| Did the model word each search total as a count of matches ("N matched the search"), yes / no | |
| Documents in the block that the model's text cites | |
| Of those, the ones whose "Search words" line shows few or none of the search words, and whether each is about your question (your own reading of title and abstract) | |
| Any document the model's text calls "the newest", "the most recent" or "the" one on a subject: does its own title and abstract show that (yes / no) | |
| Numbers, dates, URLs, references or quoted phrases listed as not found in the tool results | |
| Tool errors | |
| One URL from the block that you opened, and whether the model's text agreed with the page | |
| Anything in the model's text that was wrong and drew no warning | |
| Did the model pass last_n_days for a "last N days" question (yes / no) | |
| Model turns | |
| Input tokens / output tokens | |
| Wall-clock seconds, from the line "Wall-clock seconds" | |

## Ten answers read by hand against the block

No script fills this in. Ask 10 different questions of your own (10_run_local.py,
one model run each), or use answers you already have to 10 different questions.
Read each answer against the block that code built above it.

| Count | Your value |
|---|---|
| Answers read (10 if you can), and the model that wrote them | |
| Answers that list or describe a document as being about what you asked when its title in the block does not show that (open its URL when the title leaves that open) | |
| Answers that call a document "the newest", "the latest" or "the most recent" of its kind when the block does not show that | |
| Answers that say nothing else exists ("only", "no other", "nothing was published") when the block does not show that (a search that returned fewer documents than matched cannot show it) | |
| Answers counted in at least one of the three rows above | |
| Of those, answers that carried a WARNING line | |
| Answers with a WARNING line that was wrong: the block supports what the warning questions | |
| Answers with a NOTE line, and whether any NOTE told you something you used | |

## Deployment (30_deploy.py)

| Measurement | Your value |
|---|---|
| UTC of the create call, from the line "Deployed at" | |
| Minutes to runtime READY, from the [timing] line "create call to runtime READY" | |
| Minutes to endpoint READY, from the [timing] line "create call to DEFAULT endpoint READY" | |
| Did the opentelemetry-instrument entry point start (yes / had to set ENABLE_OTEL=false) | |
| Did the runtime answer with KIT_BIND_HOST=0.0.0.0 (yes / no) | |
| Did you need EXECUTION_ROLE_S3_READ=true (yes / no) | |

## Hosted calls (50_invoke_hosted.py)

These are whole-call figures measured on your machine: network, AgentCore, the
model and the Federal Register requests together. Record the values, not a
percentile. The gap between the two latency rows is not a measured cold start.

| Measurement | Your value |
|---|---|
| UTC start and end of the run, from the lines "Started at" and "Finished at" | |
| Sessions opened, and calls per session | |
| Question asked in every call | |
| First call in a new session, ms, end to end: the individual values | |
| Same question again in the same session, ms, end to end: the individual values | |
| Calls left out of both lines because an earlier call in their session failed | |
| Failed or flagged calls, with the reason and the WARNING lines for each | |
| Numbers, dates, URLs, references or quoted phrases the runtime reported as not found in the tool results | |
| Sessions stopped by the script (should equal sessions opened) | |
| Earliest UTC at which a usage read can be final, from the line after "Usage arrives late" | |

## Usage and cost (60_read_usage.py, then the bill)

| Measurement | Your value |
|---|---|
| UTC of the read you are recording and Minutes after the last session, from the line "This read:" | |
| Was the read early (the line "That is EARLY") and was --accept-early-read given (yes / no) | |
| Last line of 60_read_usage.py (RESULT: CROSS-CHECKED or NOT CROSS-CHECKED), word for word; it ends with "Read at" and its UTC | |
| Tolerance in that line (10% unless you passed --tolerance-percent) and how far apart the two sources were | |
| vCPU-hours and GB-hours, sum of per-session sums (usage logs) | |
| vCPU-hours and GB-hours, sum of per-session maxima (usage logs) | |
| What the records look like (increments / running totals / unknown) | |
| vCPU-hours and GB-hours, runtime total (CloudWatch metrics) | |
| Runtime cost, USD, only if the result was CROSS-CHECKED and not read early; give the range if the line gives one | |
| Platform version behind that cost: reported by the service, or ASSUMED (and the cost at the other version's rates, which the line then gives) | |
| Cost of the dearest single session, USD, same condition | |
| Model tokens in / out across all hosted calls | |
| Model token price used, USD per 1M input tokens / per 1M output tokens, with the page and the date | |
| Token cost, USD | |
| Hours the runtime existed, from the line "The runtime existed for" that 90_teardown.py prints | |
| Dollars billed for AgentCore (Billing and Cost Management, next day) | |
| Dollars billed for Bedrock model use | |
| Dollars billed for CloudWatch and S3 | |

## Traces and logs

| Measurement | Your value |
|---|---|
| Transaction Search on in this account (yes / no) | |
| Spans found per session, in the runtime's own log group / in aws/spans (60_read_usage.py or the console) | |
| Did any span hold a prompt or model text although TRACELOOP_TRACE_CONTENT was false (yes / no / did not look) | |
| One thing a trace showed you that the logs did not | |

## Optional gateway step

| Measurement | Your value |
|---|---|
| Done (yes / no) | |
| Minutes and Seconds to READY, from the [timing] lines "create call to gateway READY" and "create call to gateway and target READY" | |
| Tool names returned by tools/list | |
| Latency of one tools/call, ms | |

## Teardown

| Measurement | Your value |
|---|---|
| Last line of 90_teardown.py, word for word, and its exit code (0 is the only pass) | |
| UTC start and end of the teardown, from the lines "Tearing down kit C in" and "minute(s) after the start" | |
| Anything it listed as NOT deleted, with the Region | |
| Last line of 99_verify_clean.py (RESULT: ...), word for word; it ends with "Checked at", its UTC and "Exit code" | |
| Account (last four digits), Regions and prefixes that line says were checked | |
| Did that line say no state file was found, or that a teardown ran without a record (yes / no) | |
| ../common/whats_running.py run for the same Region and prefix (yes / no), and what it listed | |
| Anything left on purpose (for example Transaction Search) | |

## Notes

What surprised you, what failed, what you changed in the kit to make it work,
and which UNVERIFIED items from README section 8 turned out right or wrong.
