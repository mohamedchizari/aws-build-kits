# Kit A results: one open-weights model on one SageMaker AI GPU endpoint

Fill this in from your own run. Copy numbers from the terminal and from the CSV files in `results/`.
Leave a cell empty rather than estimate it. Every number here should be one you watched appear.

## The run

| Item | Your value |
| --- | --- |
| Date of the run (UTC): the line `CreateEndpoint was called at ...` of `10_deploy.py` | |
| Region (as printed by `10_deploy.py`, not as you remember it) | |
| Account, last four digits only (as printed by `10_deploy.py`) | |
| Name prefix (`KIT_PREFIX`) | |
| Instance type and count | |
| GPU on that instance | |
| Model (Hugging Face id) and precision | |
| Container image (full URI with tag) | |
| Host AMI version (`InferenceAmiVersion`) | |
| Where the load-test client ran (city or network, and how it was connected) | |
| Quota: date requested, date granted | |

## Deployment

| Item | Your value |
| --- | --- |
| Minutes from CreateEndpoint to InService (the line `InService after ... minutes` of `10_deploy.py`, which also has both UTC times) | |
| Did the first deploy work? If not, the FailureReason and the log line that explained it | |
| Number of deploy attempts | |

## Memory: what you predicted and what the container said

| Item | Predicted (README section 2) | Observed (`55_observe.py`) |
| --- | --- | --- |
| Weights in GPU memory, GiB | | |
| "Available KV cache memory", GiB | | |
| "Maximum concurrency for N tokens per request" | | |
| GPUMemoryUtilization, percent, idle | | |
| GPUMemoryUtilization, percent, during the load test | | |

## Three ways to call it (`50_invoke.py`)

Each timed call follows one 1-token warm-up request on the same client that is not timed, so none of these
times should include opening the connection. Time to first token means the first generated text of any
kind in both streaming modes.

| Mode | Worked? | Time to first token, s | Total, s | Output tokens |
| --- | --- | --- | --- | --- |
| plain (InvokeEndpoint) | | not applicable | | |
| stream (InvokeEndpointWithResponseStream) | | | | |
| openai (`/openai/v1` with the OpenAI SDK) | | | | |

Was a WARNING about reasoning text printed (yes or no)? If yes, the times above are to the first reasoning token:

## Load test, baseline (`results/loadtest_baseline_*_summary.csv`)

Settings: `SM_VLLM_MAX_NUM_SEQS` = ____ , `SM_VLLM_MAX_MODEL_LEN` = ____ , max_tokens = ____ , requests per level = ____

"Sent" counts recorded requests only. Before each level the script also sends one request per worker that
is not recorded (the `warmup_requests` column), so that recorded requests reuse an open connection.
A request whose stream stops without a finish reason counts as failed, not OK.
TTFT p95: the script shows `-` for a level with fewer than 20 successful requests. Write the `-`.
Output tokens per request: the line `Level N: ... output tokens per request: mean, min, max`. Requests stop
where the model stops, so they are "up to" max_tokens, not max_tokens, unless you passed `--ignore-eos`.
Decode chunks/s: stream chunks per second after the first chunk. It is tokens per second only if no
`NOTE: decode ...` line was printed (that note means the server's token count and the chunk count differed).

| Concurrency | OK / sent | TTFT p50, s | TTFT p95, s | Request tokens/s p50 | Decode chunks/s p50 | Aggregate output tokens/s | Output tokens per request: mean (min to max) | Tokens counted from | Requests with reasoning text |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | | | |
| | | | | | | | | | |
| | | | | | | | | | |

## The one setting you changed (`70_change_one_setting.py`)

| Item | Your value |
| --- | --- |
| Setting, old value, new value | |
| What you expected to happen, written before you ran the second load test | |
| Minutes of downtime while the endpoint was recreated (the `Downtime:` line of `70_change_one_setting.py`, with both UTC times) | |
| Hours of the endpoint it replaced (the line `The endpoint it replaced:`; write "at most" if it says AT MOST) | |

## Load test, after the change (`results/loadtest_changed_*_summary.csv`)

| Concurrency | OK / sent | TTFT p50, s | TTFT p95, s | Request tokens/s p50 | Decode chunks/s p50 | Aggregate output tokens/s | Output tokens per request: mean (min to max) | Tokens counted from | Requests with reasoning text |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| | | | | | | | | | |
| | | | | | | | | | |
| | | | | | | | | | |

What changed, in one or two sentences of your own:

## Money and time

| Item | Your value |
| --- | --- |
| Hours of the endpoint that teardown deleted (the `This run:` line of `90_teardown.py`; write "at most" if it says AT MOST) | |
| Hours in this sitting: that line plus the replaced endpoint above, if you changed a setting | |
| For reference only: the line `All N finished runs ...`, if printed (N, the dates, the total). It can include other days and is not this sitting | |
| Price per hour you expected, and its source | |
| Estimated instance charge (hours x price) | |
| Dollars billed for Amazon SageMaker, read from Billing and Cost Management, and the date you read it | |
| Any other line on the bill caused by this kit (CloudWatch, data transfer) | |
| Difference between the estimate and the bill, and your explanation | |

## Teardown

| Item | Your value |
| --- | --- |
| Time `90_teardown.py` finished (UTC): its last line, `Teardown done at ...` | |
| `99_verify_clean.py` result line, copied exactly (it names the account, Region and prefix it checked) | |
| Do that account, Region and prefix match the three rows at the top of this file? | |
| Does the line say NO USABLE STATE FILE or LOGS KEPT? If yes it is not the plain `RESULT: CLEAN.`: README section 5 says what it is worth | |
| Its exit code (`echo $?`; 0 is the only clean one, and a `--dry-run` gives 3) | |
| Time of that check (UTC): in the first line the script prints, `Verify clean: ... checked at ...` | |
| Checked again the next day? Result | |
| Execution role deleted afterwards? (optional, it is free) | |

## What surprised you

Write three things that reading would not have taught you.

1.
2.
3.
