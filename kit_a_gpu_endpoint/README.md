# Kit A: one open-weights model on one SageMaker AI GPU endpoint

First run: read `START_HERE.md`, one page with every command in order.

## 1. What this is

A set of small scripts that you run yourself, in your own AWS account, to host a small open-weights
language model on one single-GPU Amazon SageMaker AI real-time endpoint, call it three ways, load-test it,
change one setting, measure again, delete everything, and prove nothing is left.

It is for someone who knows Python and machine learning, has used hosted model APIs, and has never
hosted a model on a GPU. The point is that you do each step and watch each number appear, so that what
you say about it afterwards is first-hand.

**This kit was written without an AWS account. No script in it has ever been run against AWS.**
Section 8 says exactly what was tested (offline only) and what was not. Expect to debug the first deploy.
It was reviewed in three rounds by independent readers (rounds 1, 2 and 4 of the kits' review), also
offline; section 8 and `REVIEW_NOTES_r4.md` say what that changed and what is still limited.

The defaults:

| Choice | Value | Why |
| --- | --- | --- |
| Model | `Qwen/Qwen3-4B`, 4.02 billion parameters, BF16 | Apache-2.0, not gated, and the model AWS's own documentation deploys in its OpenAI-compatible endpoint example |
| Container | AWS vLLM Deep Learning Container for SageMaker, tag `0.30.0-gpu-py312-cu130-ubuntu24.04-sagemaker` | It is the container AWS lists as supported for the `/openai/v1` path; the tag is the newest on the AWS image list on the day of writing |
| Instance | 1 x `ml.g6.2xlarge` (one NVIDIA L4, 8 vCPU, 32 GiB RAM) | The instance type that AWS example uses for this model |
| Region | `us-east-1` | The only Region for which this kit read prices |

Files:

| File | What it does | Bills? |
| --- | --- | --- |
| `00_check.py` | Read-only preflight: identity, Region, quota, execution role, leftovers, model is open | No |
| `10_deploy.py` | Creates the model, endpoint configuration and endpoint; waits; writes `.state.json` (resource names, plus the Region, prefix and account id of the deploy) | **Yes** |
| `50_invoke.py` | Calls the endpoint: plain, streaming, and through `/openai/v1` | No new resource |
| `55_observe.py` | Read-only: endpoint status, CloudWatch GPU and latency metrics, the container log lines that matter | No new resource |
| `60_loadtest.py` | Measures time to first token and output tokens per second at several concurrency levels; writes CSV | No new resource |
| `70_change_one_setting.py` | Recreates the endpoint with exactly one vLLM setting changed | **Yes** |
| `90_teardown.py` | Deletes endpoint, endpoint configuration, model and log group; waits; checks. Stops, deleting nothing, if the shell points at another Region, account or prefix than the deploy, or if `.state.json` is damaged and you did not name the place with `--region` and `--prefix` | Stops the bill |
| `99_verify_clean.py` | Lists by name prefix and by tag; says which account, Region and prefix it checked; exits 0 only when nothing remains there, and says in its `RESULT:` line when it had no state file to go by | No |
| `kitlib.py`, `streamstats.py` | Shared code; `streamstats.py` is the measuring and parsing logic | |
| `iam/` | The two policy documents for the execution role you create in section 3 | |
| `tests/`, `pytest.ini` | Offline tests. No credentials, no network | |
| `config.example.env`, `requirements.txt`, `RESULTS_TEMPLATE.md`, `.gitignore` | Settings to copy, pinned packages, the table for your numbers, and what not to commit | |
| `REVIEW_NOTES_r4.md` | The record of the round 4 review: each finding, what changed, what is stated as a limit | |

## 2. Problems first

### It costs money every hour it exists, traffic or not

Prices below are quoted from the AWS Price List file for Amazon SageMaker, Region US East (N. Virginia),
`https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonSageMaker/current/us-east-1/index.json`,
publication date 2026-10-06T23:47:07Z, row effective date 2026-10-01, read on 2026-10-07.

| What | Price as written in the file | Usage type |
| --- | --- | --- |
| The endpoint instance (default) | "$1.222 per Hosting ml.g6.2xlarge hour in US East (N. Virginia)" | `USE1-Host:ml.g6.2xlarge` |
| Alternative | "$1.1267 per Hosting ml.g6.xlarge hour in US East (N. Virginia)" | `USE1-Host:ml.g6.xlarge` |
| Alternative | "$1.408 per Hosting ml.g5.xlarge hour in US East (N. Virginia)" | `USE1-Host:ml.g5.xlarge` |
| Alternative | "$1.515 per Hosting ml.g5.2xlarge hour in US East (N. Virginia)" | `USE1-Host:ml.g5.2xlarge` |
| Endpoint storage | "$0.14 per GB-Mo of Endpoint ML storage" | `USE1-Host:VolumeUsage.gp2` |
| Data in and out | "$0.016 per GB for Endpoint Data IN", "$0.016 per GB for Endpoint Data OUT" | `USE1-Hst:Data-Bytes-In`, `-Out` |

Arithmetic on $1.222 per hour: a 3-hour sitting is about $3.67. Forgotten for 24 hours: about $29.33.
Forgotten for 30 days (720 hours): about $879.84.

- **Nothing in this kit shuts the endpoint down for you.** The deadline that `10_deploy.py` records is a
  reminder that later scripts enforce by refusing to run. It deletes nothing. The control is: tear down in
  the same sitting, then see `99_verify_clean.py` exit 0 with a `RESULT: CLEAN` line that names the account,
  Region and prefix you deployed in.
- A budget alarm (`../common/budget_alarm.py`) is a backstop, not a stop. It cannot stop an endpoint, and
  this kit did not verify how fast one fires. Read `../common/README.md`.
- Not verified: whether billing is per second or per hour, the exact moment billing starts (at
  CreateEndpoint or at InService), and whether an endpoint in status Failed bills. The SageMaker AI
  pricing page read on 2026-10-07 does not say. **Assume it bills from CreateEndpoint until the endpoint
  is deleted, whatever its status.** The scripts estimate on that basis; your bill is the real number.
- Prices for other Regions were not read. Outside `us-east-1` the scripts refuse to deploy until you pass
  a price you read yourself with `--price-per-hour`.
- Not priced by this kit: CloudWatch Logs storage for the container logs (if you keep them), CloudWatch
  API requests made by `55_observe.py`. Expected to be cents; not read from a price page.

### The wrong Region or account looks exactly like "nothing there"

- **An exported `AWS_REGION` overrides `config.env`.** So does an exported `KIT_PREFIX`. The account comes
  from your credentials (`AWS_PROFILE`). Open a new terminal a day later with a different Region exported,
  and every delete and every list answers "not found" or "none", which reads as success while the endpoint
  bills in the Region you deployed in.
- What the kit does about it: `10_deploy.py` writes the Region, the prefix and the account id of the deploy
  into `.state.json`. Every script that reads that file first asks AWS which account you are signed in to
  and compares the three with the shell it runs in. All but the clean check stop on a difference, naming
  both values, before they create, delete, invoke or rewrite anything. The clean check does not stop; it
  looks in more places: `99_verify_clean.py` prints the account (last four digits), Region and prefix it
  checked in its `RESULT:` line, also checks every Region and prefix the state file names, and says
  `INCOMPLETE` when the file names an account it could not check.
- What the kit cannot do: if `.state.json` is lost, nothing remembers where you deployed. The two last
  scripts then check one place and say `NO USABLE STATE FILE WAS FOUND` in the line you read; exit code 0
  next to those words is not proof. Write the Region and the last four digits of the account into
  `RESULTS_TEMPLATE.md` at deploy time. Section 5 has the way back.
- `.state.json` is local and git-ignored. It holds your full account id and your resource ARNs. Do not
  commit it or paste it anywhere. No script prints more than the last four digits of the account id:
  since round 4 everything a script prints, AWS error text and tracebacks included, passes a filter that
  cuts a 12-digit number to its last four digits and hides the user or session name of a caller ARN
  (AWS's public registry account in the image address stays readable). Every file named `.state.json*`
  in this folder is git-ignored; a copy under another name or in another folder is not.

### You cannot deploy on day one: the quota is 0

The AWS General Reference page for SageMaker AI quotas (read 2026-10-07) lists, for each of these, a
default of "Each supported Region: 0", adjustable "Yes":

| Quota name | Quota code |
| --- | --- |
| ml.g6.2xlarge for endpoint usage (default in this kit) | `L-98BDE811` |
| ml.g6.xlarge for endpoint usage | `L-D470D954` |
| ml.g5.xlarge for endpoint usage | `L-1928E07B` |
| ml.g5.2xlarge for endpoint usage | `L-9614C779` |

On that page 268 of the 271 "for endpoint usage" rows have a default of 0. You must request an increase
to 1 (section 3). The kit prints the command; you file it. No AWS page read for this kit says how long
approval takes. File it before anything else.

### Quota is not capacity

Even with quota, AWS may have no free instance of that type in the Region at that moment. The endpoint
then goes to Failed with: "Unable to provision requested ML compute capacity due to
InsufficientInstanceCapacity error. Please retry using a different ML instance type or after some time."
AWS: "Insufficient capacity errors aren't related to resource quotas" (AWS re:Post Knowledge Center, read
2026-10-07). Tear down, wait, try again. A different instance type needs its own quota request.

### AWS sources disagree on the host AMI

The container image is built for CUDA 13.0. The SageMaker host needs a matching NVIDIA driver, chosen by
`InferenceAmiVersion` in the endpoint configuration. On 2026-10-07:

- The SageMaker API reference lists `al2023-ami-sagemaker-inference-gpu-4-1` as "NVIDIA driver version:
  580, CUDA version: 13.0". AWS's own endpoint test for this container uses it for CUDA 13 images, and so
  do three AWS sample notebooks with `cu130` vLLM tags. **This kit uses it.**
- The AWS container docs page says "GPU deployments require `inference_ami_version`" but its example
  shows `al2-ami-sagemaker-inference-gpu-3-1` (driver 550, CUDA 12.4).
- The AWS developer guide page on OpenAI-compatible endpoints, and the AWS blog of 20 May 2026, deploy
  `vllm:0.20.2-gpu-py312-cu130-ubuntu22.04-sagemaker` with no `InferenceAmiVersion` at all.

If the container fails at start with a driver or CUDA error in the logs, tear down and try, in this order:

1. The exact AWS documentation configuration: in `config.env` set
   `VLLM_IMAGE_TAG=0.20.2-gpu-py312-cu130-ubuntu22.04-sagemaker` and `INFERENCE_AMI_VERSION=` (empty).
   That tag is older than the ones on the AWS image list read today (0.26.0 to 0.30.0); this kit did not
   check that it can still be pulled.
2. The default tag with `INFERENCE_AMI_VERSION=al2-ami-sagemaker-inference-gpu-3-1`.

### Other things that can go wrong

- **First start is slow.** The instance pulls a large image and the container downloads about 8 GB of
  weights from huggingface.co before it reports healthy. The kit allows 900 seconds for the health check
  (`STARTUP_HEALTH_CHECK_TIMEOUT_SECONDS`, valid range 60 to 3600). If it fails on the health check,
  raise it to 1800 and deploy again.
- **The endpoint must reach huggingface.co.** The kit sets no VPC configuration and no network isolation,
  which is what the AWS examples do. If your account forces endpoints into a VPC without internet access,
  the download fails.
- **Image tag.** `0.30.0-...-ubuntu24.04-sagemaker` is the newest tag on the AWS image list read today.
  The kit did not pull it. The environment-variable behaviour (`SM_VLLM_*`) was confirmed in the AWS
  container repository at its head commit, not for that exact tag. If the tag is missing in your Region,
  pick another SageMaker vLLM tag from the image list and set `VLLM_IMAGE_TAG`.
- **Why not the cheaper `ml.g6.xlarge`?** Same GPU, half the host RAM (16 GiB). It probably works and saves
  9.5 cents an hour. It was not chosen because the AWS documentation example for this model on this
  container uses `ml.g6.2xlarge`, and a kit nobody has run should copy what AWS shows working.
  To use it, set `INSTANCE_TYPE=ml.g6.xlarge` and request that quota instead.
- **Qwen3 "thinks" by default.** Without the switch, answers start with reasoning text. The kit sends
  `chat_template_kwargs: {"enable_thinking": false}` with every request (`CHAT_TEMPLATE_KWARGS_JSON`).
  Whether that switch works on this container was not run (section 8, unverified item 7). Time to first
  token counts reasoning text as text in every mode, so if thinking is still on, the number is the time
  to the first reasoning token. `50_invoke.py` and `60_loadtest.py` print a WARNING when they see reasoning
  text, and the CSV files count it (`reasoning_seen`, `reasoning_requests`).
- **Changing a setting means downtime here.** The normal way to change a live endpoint is UpdateEndpoint,
  which "provisions a new fleet" next to the old one. With a quota of 1 instance there is no room for a
  second fleet (this kit's inference from the AWS page, not a quoted statement). So `70_change_one_setting.py`
  deletes the endpoint and creates a new one.
- **Deleting the endpoint leaves two things behind.** AWS: "Deleting an endpoint will not delete the
  endpoint configuration or the SageMaker AI model." Teardown deletes all three. The CloudWatch log group
  also stays unless deleted; teardown deletes it unless you pass `--keep-logs`.
- **Do not delete the execution role right after teardown.** AWS: after DeleteEndpoint, SageMaker
  "asynchronously deletes associated endpoint resources" and "Do not delete or revoke the permissions for
  your ExecutionRoleArn, otherwise SageMaker cannot delete these resources." Wait at least 15 minutes.
- **The bearer token for `/openai/v1` is a credential.** It is made locally from your AWS credentials.
  The kit asks for a 5-minute token and never prints or stores it. Do not paste one anywhere.
- **Your identity needs these permissions.** `servicequotas:GetServiceQuota`,
  `servicequotas:GetAWSDefaultServiceQuota`; `iam:GetRole` and `iam:PassRole` on the execution role;
  `sagemaker:CreateModel`, `CreateEndpointConfig`, `CreateEndpoint`, `DescribeEndpoint`, `DeleteEndpoint`,
  `DeleteEndpointConfig`, `DeleteModel`, `ListEndpoints`, `ListEndpointConfigs`, `ListModels`, `ListTags`,
  `InvokeEndpoint`, `InvokeEndpointWithResponseStream`, `CallWithBearerToken`; `logs:DescribeLogGroups`,
  `FilterLogEvents`, `DeleteLogGroup`; `cloudwatch:GetMetricStatistics`.
  `sagemaker:InvokeEndpointWithResponseStream` is its own IAM action, separate from `InvokeEndpoint`
  (the AWS service authorization reference file for SageMaker lists both, read 2026-10-07). Without it the
  stream mode of `50_invoke.py` and all of `60_loadtest.py` get AccessDenied.
  `sts:GetCallerIdentity`, which every script calls, needs no grant: "No permissions are required to
  perform this operation" (STS API reference, read 2026-10-07). Probably also `sagemaker:AddTags`, because
  the kit tags at creation (not confirmed on an AWS page). An administrator in a personal account has all
  of these.
- **The numbers are small-sample numbers.** One prompt, a few dozen requests per level, one client. Time
  to first token is measured on your machine, so it includes your network path to the Region.
- **Time to first token and connection setup.** A request that has to open its connection carries a TCP
  and TLS handshake inside its time to first token. To keep that out of the recorded numbers,
  `60_loadtest.py` sends requests that are not recorded: one at the start, and before each concurrency
  level as many as the level has workers, all at once. `50_invoke.py` sends one 1-token request per client
  before it times anything, so its three modes can be compared. This rests on the HTTP client keeping
  those connections open, which it did against a local test server and which was not checked against AWS
  (section 8, unverified item 17). If your p95 at a level is far above the median for the first few
  requests only, suspect a connection that was reopened.

### Will it fit: the memory arithmetic

GPU: `ml.g6.2xlarge` has "1 x NVIDIA L4 GPU", accelerator memory "22 GiB (1 x 22 GiB)" (EC2 accelerated
computing specifications, read 2026-10-07). The SageMaker price list labels the same GPU "24" (GB).

Model facts, read 2026-10-07 from the model's Hugging Face metadata and `config.json`: 4,022,468,096
parameters stored as BF16; 36 layers; hidden size 2560; 32 attention heads, 8 key/value heads, head
dimension 128.

**Weights.** AWS's Large Model Inference guide: half precision "Size in GB = Number of Parameters * 2
(bytes / param)". 4,022,468,096 x 2 = 8.04 GB = **7.49 GiB**.

**KV cache per token.** Same guide: "KV-Cache Size (bytes / token) = 2 * n_dtype * n_layers *
n_hidden_size". 2 x 2 x 36 x 2560 = 368,640 bytes per token. That formula assumes every attention head
stores its own keys and values. This model shares them across 8 key/value heads (grouped-query
attention), so the cache holds 8 x 128 = 1,024 values per layer, not 2,560: 2 x 2 x 36 x 1,024 = 147,456
bytes per token. The second figure is this kit's own arithmetic from `config.json`, not an AWS formula.
Treat the first as an upper bound.

| At `MAX_MODEL_LEN` 8192 | AWS LMI formula | Adjusted for 8 key/value heads |
| --- | --- | --- |
| One full-length sequence | 2.81 GiB | 1.13 GiB |
| 4 full-length sequences (`MAX_NUM_SEQS` 4, the baseline) | 11.25 GiB | 4.50 GiB |
| 16 full-length sequences (after step 70) | 45.00 GiB | 18.00 GiB |
| What the load test really holds: 16 requests of about 300 tokens | 1.65 GiB | 0.66 GiB |

**Against the GPU.** vLLM does not allocate per request. It takes a fixed share of GPU memory at start
("vLLM pre-allocates GPU cache using this percentage of memory") and uses what is left after the weights
as one KV cache pool. vLLM 0.30.0's source default for that share is 0.92; the AWS container docs table
says 0.9. At 0.92: 22 GiB x 0.92 = 20.24 GiB, minus 7.49 GiB of weights = **about 12.7 GiB for the KV
cache**, less some overhead this kit cannot predict. That pool holds about 4.5 full-length sequences by
the AWS formula or about 11.3 by the adjusted one.

So: the weights fit with room to spare. Four full-length sequences fit by either formula. Sixteen
full-length sequences do not fit by either. The load test still works at concurrency 16 because its
requests are about 300 tokens, not 8,192. If real traffic sent sixteen 8,192-token requests at once, vLLM
would preempt some ("there is not enough KV cache space") and they would be slower, not fail.

`00_check.py` prints this arithmetic for your settings. `55_observe.py` shows the container's own
answer: the log lines "Available KV cache memory: N GiB" and "Maximum concurrency for 8,192 tokens per
request: Nx". Write your prediction down first, then compare. Also expect `GPUMemoryUtilization` to sit
near 90 percent while idle: that is the reservation, not need.

## 3. Before you start

Only you can do these. Do them in this order.

1. **Create a non-root identity, then sign in with it.** A new account has only the root user, and
   `aws configure sso` has nothing to sign in to until an IAM Identity Center user exists. If you have none:
   sign in to the console once as the root user, enable IAM Identity Center (the tutorial below needs an
   organization instance), and follow the AWS tutorial "Configure user access with the default IAM Identity
   Center directory" (read 2026-10-07). It has you add a user, add a group, create the predefined
   `AdministratorAccess` permission set and assign it to your account, then accept the invitation email and
   set the user's password. After that, do not use the root user for this kit.
   Then, with AWS CLI v2: `aws configure sso` once (it asks for your IAM Identity Center start URL or issuer
   URL and the Region that hosts it), and `aws sso login` each session.
   Check: `aws sts get-caller-identity`. The Arn must not end in `:root`. Set `AWS_PROFILE` if you use a
   named profile. `00_check.py` warns if you are signed in as root.
   These console steps were read on the AWS pages, not performed, by the author of this kit.

2. **Set a budget alarm.** Use `../common/budget_alarm.py`; its commands are in `../common/README.md`.
   It will not stop an endpoint. It tells you later that you forgot one.

3. **Request the quota. This is the long wait.** Service Quotas console, Amazon SageMaker, search
   "ml.g6.2xlarge for endpoint usage", Request increase, new value 1. Or:

   ```
   aws service-quotas request-service-quota-increase --service-code sagemaker --quota-code L-98BDE811 --desired-value 1 --region us-east-1
   ```

   Ask for 1. Note the date. The request shows as pending in the Service Quotas dashboard until AWS decides.

4. **Create the execution role** that SageMaker assumes to pull the image and write logs. It is free.
   From this folder:

   ```
   aws iam create-role --role-name kitdemo-kita-sagemaker-execution --assume-role-policy-document file://iam/execution_role_trust.json --tags Key=project,Value=aws-kits Key=kit,Value=kit-a-gpu-endpoint
   aws iam put-role-policy --role-name kitdemo-kita-sagemaker-execution --policy-name kita-pull-image-write-logs --policy-document file://iam/execution_role_permissions.json
   ```

   The permissions are the list on the AWS "SageMaker AI roles" page for CreateModel, without the two S3
   actions, because this kit stores nothing in S3. That trimmed policy has not been run. If the endpoint
   fails with an access error, attach the managed policy `AmazonSageMakerFullAccess` instead, which is
   what the AWS examples use.

5. **Set up Python.** Python 3.11 or newer.

   ```
   python -m venv .venv
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   cp config.example.env config.env
   ```

   Edit `config.env` only if you change the prefix, instance type or role name. `.venv/`, `config.env`,
   `.state.json` and `results/` are in `.gitignore`.

   Check that nothing in your shell overrides it: `echo $AWS_REGION $KIT_PREFIX`. Both should be empty or
   equal to what `config.env` says. An exported value wins over the file.

6. **Run the offline tests and the preflight.**

   ```
   python -m pytest -q
   python 00_check.py
   ```

   Do not go on until `00_check.py` prints `0 FAIL`.

## 4. Run it

Every script takes `--dry-run`, which prints the AWS calls it would make and makes none. Use it first.
(`90_teardown.py --dry-run` and `99_verify_clean.py --dry-run` exit 3, not 0. For those two scripts exit
code 0 means "nothing remains", and a dry run deleted nothing and checked nothing.)
Do steps 2 to 9 in one sitting, in one terminal. Set a timer for the time you intend to stop.

1. **See what deploy will do.** `python 10_deploy.py --dry-run`
   Read the three create calls and the price.

2. **Deploy. Billing starts here.** `python 10_deploy.py --i-understand-this-bills`
   Its first lines say where it deploys: Region, account (last four digits) and prefix. Write the Region and
   those four digits into `RESULTS_TEMPLATE.md` now. Watch the status lines. Note the minutes to InService.
   If it ends in Failed, do what it prints: read the logs, tear down, then fix the cause. If it stops with
   "CreateEndpoint did not come back with a clear answer", the endpoint may exist: run
   `python 99_verify_clean.py`, then `python 90_teardown.py`. If it stops with "CreateEndpoint was refused
   ... and an endpoint named ... EXISTS", AWS answered "already exists": you see that when the answer to
   this run's own request was lost and the SDK sent it again, and when an endpoint of that name was there
   before. Either way it is billing and stays in `.state.json`: run `python 90_teardown.py`, then
   `python 99_verify_clean.py`, then deploy again. Exit code 2 means it stopped before it created
   anything; once a create call was sent, every stop is exit code 1, or 130 for Ctrl-C, and the last
   line names the calls.

3. **Call it three ways.** `python 50_invoke.py`
   Each client first sends one 1-token request that is not timed. Then notice that the plain call shows
   nothing until the whole answer exists, and the streaming call shows the first token much sooner. Note
   which modes worked: a line near the end says "Invocation modes that worked: N of 3". A mode that AWS
   refuses prints its own FAILED line with the reason and does not stop the others. If a WARNING about reasoning text
   appears, thinking is still on; note it, because it changes what "time to first token" means.

4. **Look inside.** `python 55_observe.py`
   Find "Available KV cache memory" and "Maximum concurrency". Compare with your prediction from section 2.
   Metrics lag by a few minutes.

5. **Predict, then measure the baseline.** Before running, write down what you expect at concurrency 16
   when the server will only decode 4 requests at once.
   `python 60_loadtest.py --label baseline`
   Three levels (1, 4, 16), 32 recorded requests each, up to 200 output tokens each. A few minutes.
   For each level it prints the output tokens per request (mean, min, max): requests stop where the model
   stops, so they are not all 200.
   Before each level it sends one request per worker that is not recorded (22 in all with these levels),
   so that recorded requests do not include opening a connection.
   Ctrl-C stops it: no further request is sent, the requests already on their way are waited for (60
   seconds at most), and what was measured goes into two files with `INTERRUPTED` in their names. A level
   that was cut has its finished requests in the per-request file and no row in the summary file.
   Run it in the foreground of a Terminal window. Started in the background with `&` from a script (a
   shell that is not interactive), the process is started with the interrupt signal ignored and Ctrl-C
   does not reach it: the load runs to its end (seen in a test run on macOS on 7 Oct 2026, when the two tests of
   this were started in the background and the load exited 0). `nohup` alone does not do this: it
   ignores only the hang-up signal (measured: `nohup python3 ...` in the foreground keeps the default
   Ctrl-C handler, `bash -c 'python3 ... &'` starts with it ignored).

6. **Change one setting.** `python 70_change_one_setting.py --set SM_VLLM_MAX_NUM_SEQS=16 --i-understand-this-bills`
   The endpoint is deleted and recreated. Several minutes of downtime; the script prints how many
   (`Downtime:`) and the hours of the endpoint it replaced. Your deadline does not move.
   Do not edit `config.env` between deploy and this step: the script refuses if the instance type, model,
   image or host AMI in your settings differ from what was deployed.
   (Other settings you may change instead are listed by `python 70_change_one_setting.py --help`.)

7. **Look inside again.** `python 55_observe.py`

8. **Predict, then measure again.** `python 60_loadtest.py --label changed`
   Compare the two `results/loadtest_*_summary.csv` files line by line.

9. **Tear down and prove it.** Section 5. Do not leave this for later.

Useful options: `60_loadtest.py --concurrency 1,8,32 --requests-per-level 64 --ignore-eos` (the last
makes every request generate exactly `--max-tokens` tokens); `50_invoke.py --mode stream --prompt "..."`;
`55_observe.py --all-logs`.

## 5. Tear it down and prove it

```
python 90_teardown.py
python 99_verify_clean.py
echo $?
```

**The limit, first.** These two scripts learn where you deployed from `.state.json` and from nowhere else.
If that file is gone they look in the one place your shell names. They cannot know that a deploy went to
another Region, and they find nothing there, which looks like success. They say so in the line you read:
`NO USABLE STATE FILE WAS FOUND` and `NOT proof for any other Region`. Exit code 0 next to those words is
not proof that the endpoint is gone. "If the state file is lost or damaged", below, says what to do.

Run both in the terminal you deployed from, or check first that this one points at the same place:
`echo $AWS_REGION $KIT_PREFIX $AWS_PROFILE`. **An exported `AWS_REGION` overrides `config.env`.** In the
wrong Region or account every delete answers "not found", which looks exactly like success. Both scripts
also take `--region` and `--prefix` on the command line, which override the shell and `config.env`.

The guard: `.state.json` records the Region, the name prefix and the account id of the deploy. Every script
that reads it compares all three with the current shell. `90_teardown.py` and every earlier script stop on
a difference. The message names both values. Nothing is deleted and the file is not rewritten. Fix the
shell and run the script again. `--region` and `--prefix` do not get past this guard: a readable state file
decides.

`90_teardown.py` deletes the endpoint, waits until SageMaker says it no longer exists, then deletes the
endpoint configuration, the model and the log group, and lists what remains. It finds resources from
`.state.json`, by the name prefix `<KIT_PREFIX>-kita-`, and by the tags `project=aws-kits` plus
`kit=kit-a-gpu-endpoint`. So in the Region it runs in it finds them without the state file as well; in any
other Region it finds nothing. It deletes the log group of every endpoint it deletes, whatever prefix that
endpoint had, and any log group left under `/aws/sagemaker/Endpoints/` whose name follows this kit's
naming rule (`<any prefix>-kita-...`). It strikes a resource from `.state.json` only after a fresh listing,
in the recorded Region and account, no longer shows it. If the listing it makes before the deletes is
denied or throttled, it still deletes the endpoint (the one on record, or the one with this kit's fixed
name), says so, and then stops on the listing error with exit code 1: the charge stops first.

What it prints for your results table:

- `Endpoint(s) confirmed gone at <UTC time>`.
- `This run:` the hours and the estimated dollars of the endpoint it just deleted, with that run's own
  start and end. If the endpoint was already gone when it looked (deleted in the console, for example) the
  line says `AT MOST`, because it cannot know when the endpoint stopped.
- `All N finished runs recorded in .state.json ...` when the file holds more than one finished run: the
  total, the number of runs, the dates they cover, and one line per run. That total can include another
  day. It is not the number for this sitting.
- Its last line when it succeeded, `Teardown done at <UTC time> (UTC): ...`. Read all of it. It says
  `NO USABLE STATE FILE WAS FOUND` when there was none, `RECORDED NO LIVE DEPLOY` when the file held only
  finished runs (it then acted where the shell points, and names any Region of the history that it did
  not look at), and `LOGS KEPT` when you passed `--keep-logs`.
  Any other last line (`NOT CLEAN`, `TEARDOWN INCOMPLETE`, `TEARDOWN NOT CONFIRMED`, `STOP`, `STOPPED
  BEFORE ANY CHANGE`, `BEFORE IT STOPPED, THIS RUN HAD SENT TO AWS`) comes with a non-zero exit code and
  says what to do. After Ctrl-C (exit code 130) the last line is one of the last two.

Its exit codes: 0 nothing of this kit remains where it acted; 1 something remains, the state file is
damaged and the place could not be confirmed, or it stopped after it had sent a delete call (the last
line names the calls that were sent); 2 it stopped before deleting anything; 3 `--dry-run`.

`99_verify_clean.py` is the proof. It lists every endpoint, endpoint configuration and model and reports
any that match by name or by tag, and the kit's log groups under `/aws/sagemaker/Endpoints/`. It reads the
state file for one thing only: to learn where else to look. Every Region and prefix that the file or its
history names is checked too, in the account you are signed in to. It never takes the file's word that
something is gone. Its `RESULT:` line names what it checked:

```
RESULT: CLEAN. Checked account ending 1234, Region us-east-1, prefix kitdemo: 0 endpoints, 0 endpoint configurations, 0 models, 0 log groups belonging to this kit. Only those places were checked (this shell, plus what .state.json and its history name); this is NOT proof for any other Region or account. Exit code 0.
```

**Exit code 0 and a line that starts `RESULT: CLEAN.` and names the account, Region and prefix you deployed
in are the only acceptable ending.** Read the line; do not only read the exit code. Two other lines also come
with exit code 0 and are weaker. All the endings:

| Exit code | Line | Meaning |
| --- | --- | --- |
| 0 | `RESULT: CLEAN.` | Every place this shell and the state file name was checked and nothing remains there. |
| 0 | `RESULT: CLEAN ONLY WHERE CHECKED. NO USABLE STATE FILE WAS FOUND ...` | There is no `.state.json`. Only the account, Region and prefix in the line were checked. It is proof for that one place and NOT proof for any other Region. If that is not the Region you deployed in, the endpoint may still be billing. |
| 0 | `RESULT: CLEAN EXCEPT FOR THE LOGS YOU KEPT. ... LOGS KEPT: ...` | You passed `--allow-logs`. The log groups named in the line still exist and cost a little storage until you delete them. |
| 1 | `RESULT: NOT CLEAN` | Something remains. The list is printed, with its Region. Run `90_teardown.py` there. |
| 1 | `RESULT: INCOMPLETE` | Nothing was found where it looked, but the check does not cover everything: the state file names an account you are not signed in to, it records a live deploy with no account id or no Region, it is damaged, or the tag lookup limit was reached. It says which, and what to do. |
| 1 | `STOP: AWS returned ...` | A check could not be made, for example a List call was denied. That is not clean. |
| 2 | `STOP: ...` | It could not run, for example no credentials. |
| 3 | `DRY RUN ...` | `python 99_verify_clean.py --dry-run` or `python 90_teardown.py --dry-run`. Nothing was checked and nothing was deleted. For both scripts exit code 0 means "nothing remains", so a dry run of either never exits 0. |

### If the state file is lost or damaged

**Lost** (there is no `.state.json`: deleted, or you are in a fresh copy of this folder). No script can
tell you where the deploy went. You have to know the Region.

1. Find the Region. It is in `RESULTS_TEMPLATE.md` if you wrote it down at deploy time (section 4, step 2).
   Otherwise look at the Endpoints list in the SageMaker AI console, one Region at a time, and run the
   shared audit for every Region you may have used:
   `python ../common/whats_running.py --region <each Region you may have used> --prefix <your KIT_PREFIX>`.
2. Tear down there, naming the place: `python 90_teardown.py --region <the Region you deployed in> --prefix <your KIT_PREFIX>`
3. Check there: `python 99_verify_clean.py --region <the same Region> --prefix <the same prefix>`
   Both lines will say `NO USABLE STATE FILE WAS FOUND`. That is true and it stays true. What makes the
   result worth something is that the Region in the line is the one you deployed in, and you are the only
   one who knows that.

**Damaged** (the file exists but cannot be read as a state file: empty, cut short, or edited into
something else). Every script except the clean check stops with exit code 2 and prints the steps below.
The clean check runs, read-only, and answers `INCOMPLETE` or `NOT CLEAN`. **No script deletes, renames or
rewrites a damaged state file.** It is the only evidence of where the deploy went.

1. `python 90_teardown.py --region <the Region you deployed in> --prefix <your KIT_PREFIX>`
   Both flags are needed. An exported `AWS_REGION` does not count, on purpose: a stale export is the
   mistake this guard exists for. If the file was only cut short, the stop message prints the Region still
   legible in it, as a hint and not as proof. The script deletes what it finds in the place you named,
   leaves the damaged file exactly as it is, and exits 1, not 0, with `TEARDOWN NOT CONFIRMED`: with the
   record unreadable it cannot confirm that the place you named is where the deploy went.
2. `python 99_verify_clean.py --region <the same Region> --prefix <the same prefix>`
   It also looks in every Region still legible in the damaged file. It answers `NOT CLEAN` or
   `INCOMPLETE`, never `CLEAN`, for as long as the damaged file is in this folder.
3. When it lists nothing, move the file out of this folder by hand, for example
   `mv .state.json ~/kit_a_state_damaged.json` (it holds your account id and ARNs: keep it outside any
   git repository and outside the kit folders), and run step 2 once more. The line is then
   `RESULT: CLEAN ONLY WHERE CHECKED. NO USABLE STATE FILE WAS FOUND`, with the weight described above.
4. Run the shared audit, below.

For a second, independent look across services, run the audit in the shared folder as well:
`python ../common/whats_running.py --region <the AWS_REGION in your config.env> --prefix <your KIT_PREFIX>`
(see `../common/README.md`). Add `--region` for any Region you used that this folder's state file may
not name.

What the proof does not cover, so check by hand:

- **A place the state file does not name.** A readable state file can still be ignorant: you deployed, lost
  the file, and deployed again (the new file knows only the second deploy), or you copied an older
  `.state.json` back over a newer one. The scripts cannot detect either. Every `RESULT: CLEAN.` line ends
  "NOT proof for any other Region or account" for this reason. If you ever deployed from this folder in a
  Region the line does not name, run it there too: `python 99_verify_clean.py --region <that Region>`.
- **Two accounts in one state file.** The script can only look in the account you are signed in to. If the
  file or its history names another one, every run ends `INCOMPLETE`, on purpose. Run it once signed in to
  each account and keep both lines.
- **Somebody else's kit A in the same account.** Teardown deletes everything in its Region that carries
  this kit's two tags, and every log group named `<any prefix>-kita-...` under `/aws/sagemaker/Endpoints/`,
  whatever the prefix. In an account you share with another person running this kit, that is their
  endpoint too. The kit is written for one person in their own account.
- **The console.** Open the Endpoints list in the SageMaker AI console, in the Region you deployed in, and see it empty once.
- **The bill.** Look at your bill in Billing and Cost Management the next day. The SageMaker charge should have stopped growing.
- **The execution role** you created by hand. It is free. To remove it, wait 15 minutes after teardown, then:

  ```
  aws iam delete-role-policy --role-name kitdemo-kita-sagemaker-execution --policy-name kita-pull-image-write-logs
  aws iam delete-role --role-name kitdemo-kita-sagemaker-execution
  ```

- **The quota** stays at 1. That costs nothing, and it is what makes the next accidental deploy possible.

## 6. What to record

Write these into `RESULTS_TEMPLATE.md` as you go, not afterwards. Every item below is printed by a script
or is something only you know; none needs a stopwatch.

- Date, Region, the last four digits of the account, instance type, GPU, model, container image tag, host
  AMI version. `10_deploy.py` prints all of them, and the UTC time of the CreateEndpoint call.
- Where your client ran.
- Date the quota was requested and date it was granted.
- Minutes from CreateEndpoint to InService (the `InService after ... minutes` line, with both UTC times).
  Number of deploy attempts and the reason for each failure.
- Predicted and observed: weights in GiB, KV cache in GiB, "Maximum concurrency", idle GPU memory percent.
- For each of the three invocation modes: worked or not, time to first token, total time. Each timed call
  came after one 1-token warm-up request on the same client.
- For the baseline and for the changed setting, at each concurrency level: requests OK out of sent, time to
  first token p50 and p95, request tokens per second p50, aggregate output tokens per second, the output
  tokens per request (the line `Level N: ... output tokens per request: mean, min, max`), whether tokens
  were counted from the server's usage field or from chunks, and how many requests carried reasoning text
  (`reasoning_requests`; it should be 0).
  The p95 column shows `-` for a level with fewer than 20 successful requests; write the `-`, not a number.
  The decode column counts stream chunks. If `NOTE: decode ...` was printed, the chunk count and the
  server's token count differed and the column is not tokens per second.
- The one setting you changed, old value, new value, and what you predicted. The minutes of downtime: the
  `Downtime:` line of `70_change_one_setting.py`.
- Hours the endpoint existed: the `This run:` line of `90_teardown.py`, plus the line `The endpoint it
  replaced:` of `70_change_one_setting.py` if you ran it. Add those two for this sitting. Do not use the
  `All N finished runs` total: it can include another day. The estimated charge, and **the dollars
  actually billed**, read from the bill.
- The UTC time teardown finished: its last line, `Teardown done at ...`.
- The `RESULT:` line of `99_verify_clean.py`, copied whole (it names the account, Region and prefix that were
  checked, and it says so when no state file was found or when logs were kept), its exit code, and the
  time, which is in the first line the script prints.
- Three things that surprised you.

## 7. What you can truthfully say afterwards, and what you cannot

This section is about what YOU did. The scripts, the arithmetic in section 2 and the reading of the AWS
pages are the kit's, not yours. What becomes yours is each step you ran, each number you watched appear,
each prediction you wrote down before you looked, and each thing you had to fix.

After you have run it and filled in your numbers, you can say, with your own figures in the blanks. Each
sentence has a condition; drop the sentence if the condition is not met.

- "I deployed Qwen3-4B, a 4-billion-parameter open-weights model, on a single-GPU SageMaker AI real-time
  endpoint (one ml.g6.2xlarge, one NVIDIA L4) with the AWS vLLM container. The quota for that instance
  type starts at zero, so I had to request it; that took ___."
  (If `10_deploy.py` reached InService for you. Name the instance type and image tag you really used.)
- "First start took ___ minutes."
  (The number `10_deploy.py` printed.)
- "I invoked it ___ ways: ___." Name only the modes that printed a result for you, from these three:
  InvokeEndpoint; InvokeEndpointWithResponseStream; the OpenAI SDK through the endpoint's /openai/v1 path
  with a short-lived bearer token. If `50_invoke.py` said "2 of 3", say two, and say which one failed and
  why if you found out.
- "From a client in ___, at concurrency ___, I measured a median time to first token of ___ seconds and
  ___ output tokens per second in aggregate, over ___ requests of up to ___ output tokens each (___ on
  average), using a load-test script from a build kit."
  (Numbers from your own summary CSV. "Up to" is `--max-tokens`; the average is the mean the load test
  printed for that level. Say "of ___ output tokens each" only if you ran with `--ignore-eos` and min, mean
  and max were equal. If a WARNING about reasoning text was printed, say "time to first reasoning token".
  If tokens were counted from chunks, say "approximately". Quote a p95 only for a level where the table
  shows a number, which needs at least 20 successful requests. Do not quote the decode column as tokens
  per second if `NOTE: decode ...` was printed.)
- "Before I looked, I predicted that the weights would take about ___ GiB of the L4's memory and the KV
  cache about ___ GiB. The container's log reported ___ GiB of KV cache and a maximum concurrency of ___
  for 8,192-token requests."
  (Only if you wrote your prediction into `RESULTS_TEMPLATE.md` before running `55_observe.py`. The method
  is section 2's: vLLM takes a fixed share of GPU memory at start, about 0.9 of it, and what is left of
  that share after the weights and some overhead is the KV cache. Do not say vLLM "reserves the rest".)
- "I changed max-num-seqs from 4 to 16 and measured again: at concurrency 16, time to first token went
  from ___ to ___ and aggregate tokens per second from ___ to ___."
  (Only if both load tests ran and you changed that setting; otherwise name the setting you changed.)
- "The endpoint existed for about ___ hours and cost $___ on my bill."
  (The hours are teardown's `This run:` line, plus the line `The endpoint it replaced:` from step 6 if you
  changed a setting. Not the `All N finished runs` total, which can include another day. The dollars are
  from Billing and Cost Management, not the script's estimate. If a line you used says "AT MOST",
  "UNKNOWN time" or "already exists", you do not know the hours; say so.)
- "I deleted the endpoint, the endpoint configuration and the model, and a script that lists by name and
  by tag found none left in that Region and account."
  (Only if the line starts `RESULT: CLEAN.` and names the account, Region and prefix you deployed in. It
  did not check other Regions or accounts unless its line names them. If it says `CLEAN ONLY WHERE
  CHECKED. NO USABLE STATE FILE WAS FOUND`, the script did not know where you deployed: you may say this
  only if you know from your own notes that the Region in the line is the one you deployed in. If it says
  `LOGS KEPT`, say that you kept the logs.)
- Anything in your "what surprised you" list, and anything you had to fix to make the kit run. It is yours.

You cannot say, on the strength of this kit:

- That you wrote the deploy, load-test, stream-parsing or teardown code, or worked out the memory formulas.
  You ran a kit. Say "I ran" and "I measured", not "I built", unless you changed the code, and then say
  what you changed.
- That you have run GPU inference in production, for customers, or under real traffic.
- That you benchmarked the model, the L4, or vLLM. One prompt, small samples, one client, one Region.
- Anything about autoscaling, scale to zero, inference components, multi-model endpoints, blue/green
  updates, multi-GPU or tensor parallelism, quantisation, LoRA adapters, or other accelerators. The kit
  touches none of them.
- Anything about private networking, VPC endpoints, KMS encryption, or compliance regimes. The endpoint
  used default networking and downloaded weights from the public internet.
- That you tuned vLLM. You changed one setting once.
- A number you did not measure yourself. Do not quote the predictions in section 2 as results.
- That the kit as written was validated by its author or by its reviewer. Neither ran it against AWS. If
  you had to fix it, say so; that is a better story than a clean run.

## 8. What was and was not tested

Reviewed independently on 2026-10-07 (round 1): 18 findings, 18 fixed, 0 left open (listed below).

Reviewed independently a second time on 2026-10-07 (round 2): 11 findings for this kit, 11 fixed, 0 left open (listed below).

Reviewed independently on 2026-10-07 (round 4): 12 findings for this kit, 12 fixed, 0 stated as a limit, 0 not changed (`REVIEW_NOTES_r4.md`). Two of those fixes leave a limit of their own: MAJOR 2 (Ctrl-C in the load test) waits at most 60 seconds (item 13 below), and MINOR 3 was fixed in words only, so the stale state file behind it stays a limit (items 2, 3 and 14).

Reviewed independently on 2026-10-08 (round 5): 9 findings for this kit and `../common/` (all MINOR) and 1 question, 9 fixed, 0 stated as a limit, the question answered in the line above (`REVIEW_NOTES_r5.md`).

"Fixed" means changed in code or text and tested offline. Neither the author nor any reviewer has run
anything against AWS. Round 2 had two readers. One drove the real scripts as processes against a stateful
fake account, 36 sequences for this kit (A00 to A25 with variants): wrong Region, wrong account, lost,
emptied and truncated state files, refused and timed-out calls, killed processes. The other recomputed
every number the scripts print. Their harnesses were run again against the fixed kit; the results are
under SAFE.

**What is still wrong or limited after all three rounds. Bad news first.** Items 11 to 14 are from round 4.

1. **Nothing in this kit has run against AWS.** Every statement about AWS behaviour comes from a page or
   from a fake. Expect to debug the first deploy.
2. **A lost state file cannot be made good.** With no `.state.json`, teardown and the clean check look in
   the one place the shell names. If the deploy went to another Region they find nothing, and they still
   exit 0 with the endpoint billing (the reviewer's sequences A06b and the end of A07). Round 2 changed
   the words, not the exit code: the last line of teardown and the `RESULT:` line now say `NO USABLE STATE
   FILE WAS FOUND`, name the one account, Region and prefix that were checked, and say `NOT proof for any
   other Region`. The owner has to read that line. A script that reads only the exit code is fooled.
3. **A readable state file can be ignorant, and then nothing warns in particular.** Deploy, lose the file,
   deploy again elsewhere, tear the second one down (A05b); or copy an older `.state.json` over a newer
   one (A09b). The clean check prints the ordinary `RESULT: CLEAN.`, exit 0, with the first endpoint
   alive. Every clean line now ends "NOT proof for any other Region or account", and `10_deploy.py` prints
   a NOTE when it starts a new state file. That is all the kit can say: it has no record to go by.
4. **A damaged state file needs the owner to know the Region.** The explicit route (section 5) works only
   if you name the right place. The hint printed from a truncated file is a hint; an emptied file gives
   none. After recovery the best possible result is `CLEAN ONLY WHERE CHECKED`, not `CLEAN`.
5. **Teardown reaches across prefixes.** It deletes everything in its Region that carries this kit's two
   tags, and since round 2 every log group named `<any prefix>-kita-...` under `/aws/sagemaker/Endpoints/`.
   In an account shared with another person running this kit, that is their endpoint and their logs.
6. **The log group search has no upper limit.** Teardown and the clean check now list every log group under
   `/aws/sagemaker/Endpoints/`, 50 per call. In an account with thousands of endpoints that is many
   calls. Not measured, not capped.
7. **Two accounts in one state file never reach exit code 0** (on purpose, since round 1; section 5).
8. **The decode column is a chunk rate.** It is tokens per second only when every stream chunk is one
   token. When the server batches two tokens into a chunk it is half the true rate. The script prints a
   NOTE when its two counts differ; it cannot correct the number.
9. **Hours for a sitting with a setting change are two printed lines that you add yourself** (section 6).
10. **The round 2 fixes were checked against fakes written by the reviewers and by the author.** Real error
    codes, eventual consistency of the List calls, and whether an endpoint in status Deleting bills are
    not known (UNVERIFIED items 3, 10, 18 and 19). The same holds for the round 4 fixes (item 20).
11. **Exit code 1 has one more meaning.** Since round 4 a script that stops after it has sent a create or
    delete call exits 1, not 2 (130 if the stop was Ctrl-C). So 1 can mean "something remains", "AWS
    returned an error" or "stopped half way". The code does not tell them apart; the last line does
    (`BEFORE IT STOPPED, THIS RUN HAD SENT TO AWS:`).
12. **An endpoint kept after "already exists" may be older than its record.** Its hours are counted from this
    run's CreateEndpoint call. If it was there before, they are too low. Every line that prints them says so.
13. **Ctrl-C in the load test gives up on a request that does not come back in 60 seconds**, and a level that
    was cut has no summary row. The files say `INTERRUPTED`; do not quote them as a finished run.
14. **A stale state file still fools both scripts** (limits 2 and 3; round 4 sequences A110 to A115). Round 4
    changed words only: teardown's last line no longer calls the shell's Region "the place .state.json records".

**Round 2 (2026-10-07): 11 findings, 11 fixed, 0 left open.** Six come from the reader who followed the
money (numbered as in that report) and five from the reader who checked the numbers (M3 to M5 and two
minor ones). Every one has tests in `tests/test_review_r2.py` that were written before the fix. Run
against a scratch copy of the code as reviewed, 43 of the 50 tests in that file fail; the 7 that pass
are five controls (named `..._control`) and two cases of damaged-file detection that the reviewed code
already handled.

| Finding (severity; reviewer's sequence) | What changed | Tests |
| --- | --- | --- |
| BLOCKER 2: the endpoint was found by tag under another prefix and deleted, its log group stayed, and the clean check said CLEAN (A17, A25) | `kitlib.find_remaining` lists every log group under `/aws/sagemaker/Endpoints/` and keeps the log group of each endpoint it found and every name of the form `<any prefix>-kita-...`. `90_teardown.py` deletes them; `99_verify_clean.py` counts them | `test_r2_b2_...` |
| BLOCKER 3: a live record with no account id, signed in to another account, gave CLEAN (A09a) | `99_verify_clean.py`: a live record without an account id makes the verdict INCOMPLETE, with what to do | `test_r2_b3_...` |
| MAJOR 4: a damaged state file stopped teardown for good while the endpoint billed, and the two scripts pointed at each other (A07, A08) | `kitlib.load_state` raises `StateFileError` with numbered steps. `90_teardown.py --region R --prefix P` goes on, leaves the file untouched and exits 1. The clean check stays INCOMPLETE while the file is there and also looks in the Regions still legible in it. `kitlib.save_state` refuses to overwrite a damaged file. A JSON value that is not a state object counts as damaged | `test_r2_m4_...` |
| MINOR 9: `90_teardown.py --dry-run` exited 0 (A24) | It exits 3, the code of the clean check's dry run, and says why | `test_r2_n9_...` |
| MINOR 13: nothing was written before CreateModel (A19) | `kitlib.create_stack` writes each resource into the state file before its create call and completes it after. A refused call (4xx) takes the record out; no clear answer keeps it (narrowed in round 4, UNVERIFIED item 18) | `test_r2_n13_...` |
| MINOR 14 and the lost-state limit: the `RESULT:` line never said that no state file was found (A05b, A06b, A09b, end of A07); and with logs kept on request both scripts said clean (A23) | The three `RESULT:` verdicts and the last line of teardown say `NO USABLE STATE FILE WAS FOUND`, what was checked, and `NOT proof for any other Region`. Every clean line says what it is not proof of. `LOGS KEPT` is in both lines when logs were kept | `test_r2_n14_...`, `test_r2_keep_logs_...` |
| M3: teardown printed the sum of every finished run as "the hours" | `kitlib.run_report_lines`: `This run:` on its own line, then `All N finished runs` with count, dates and one line per run. An old run with an unknown end no longer labels today's run AT MOST | `test_r2_m3_...` |
| M4: rows of the results table that no script printed | `70_change_one_setting.py` prints `Downtime:` in minutes with both UTC times and the hours of the endpoint it replaced. `90_teardown.py` prints when the endpoint was confirmed gone and when it finished. `10_deploy.py` prints the UTC time of the create call and of InService | `test_r2_m4n_...` |
| M5: "requests of ___ output tokens" could only be filled with max_tokens | `streamstats.summarise_level` and `60_loadtest.py`: output tokens per request for each level (mean, min, max), in the table and the CSV. Section 7 says "up to" | `test_r2_m5_...` |
| Minor: the decode rate divided the server's token count by chunk timing (12.22 for a true 10.0) | `streamstats.StreamRecorder.result` counts the chunks it timed. The summary counts requests where the two counts differ and the load test prints a NOTE | `test_r2_decode_...` |
| Minor: a p95 was printed for any number of requests | No p95 below 20 successful requests; the table shows `-` and a NOTE says why | `test_r2_p95_...` |

**Round 1 (2026-10-07): 18 findings, 18 fixed, 0 left open.** The reviewer read a frozen copy of this kit,
offline, and reported 1 blocker, 2 major and 15 minor findings. All 18 were changed in code or text the
same day. Five of the fixes rest on behaviour that only a run against AWS can settle; they are in the
UNVERIFIED list below as items 3, 7, 17, 18 and 19. Round 2 changed two of these rows further: row 7
(the rate now counts chunks) and row 11 (teardown's dry run exits 3 as well).

| # | Finding (severity) | What changed |
| --- | --- | --- |
| 1 | Teardown and the clean check said "clean" in the wrong Region or account, and the state file forgot the endpoint (blocker) | The state file records Region, prefix and account id. Every script that reads it stops on a mismatch, except the clean check, which looks in more places instead. Teardown strikes a record only after a listing in the recorded place no longer shows the resource. The clean check names what it checked, also checks every Region and prefix the state file names, and says INCOMPLETE for an account it could not check |
| 2 | Time to first token included opening a connection on some requests (major) | Warm-up requests that are not recorded: one per worker before each load level, one per client in `50_invoke.py`. The summary CSV counts them |
| 3 | An HTTP error on the OpenAI path crashed the error handler (major) | The openai mode reports its own failure and the run goes on; the shared error handler no longer assumes a boto3-shaped error |
| 4 | Permission list lacked `InvokeEndpointWithResponseStream` | Added (section 2) |
| 5 | `70_change_one_setting.py` took the instance type from config and the price from the state file | It refuses when instance type, model, image or host AMI differ from the deploy |
| 6 | A stream that just stops counted as OK | It is a failed request ("truncated") |
| 7 | Decode tokens per second overstated when the first payload part carries several tokens | Those tokens are no longer counted in the rate |
| 8 | Nothing checked that thinking is off; the two streaming modes timed different things | One definition in both modes; a WARNING and a CSV count when reasoning text arrives |
| 9 | A CreateEndpoint that succeeded but timed out on the client left no record | The endpoint is recorded before the call and marked unconfirmed; the script stops with what to do |
| 10 | Any ValidationException counted as "endpoint gone" | Only the known wording, or an unknown wording that ListEndpoints confirms |
| 11 | `99_verify_clean.py --dry-run` exited 0 | It exits 3 and says why |
| 12 | Only the first 50 log groups were read | All pages are read |
| 13 | Hours ran to "now" for an endpoint that was already gone | Printed and stored as "at most" |
| 14 | This section said the API page lists no members for the stream error events | Corrected: `ErrorCode` is listed, `Message` is not (item 4 below) |
| 15 | Price in step 70 had no source page; several vLLM fields had no `# UNVERIFIED:` marker in code | The price source recorded at deploy is printed; markers added (10 in code, all in the list below) |
| 16 | Section 7 overstated | Rewritten: each sentence has its condition, and it is about what you did |
| 17 | Section 3 assumed an IAM Identity Center user exists; `.venv/` not git-ignored | Step added; `.gitignore` updated |
| 18 | A missing-credentials error from the token generator showed as a traceback | Reported in one line; other unexpected errors end with a plain STOP line and exit 1 |

**SAFE: what ran here, offline, on 2026-10-07 and 2026-10-08 (Linux, Python 3.13.16, boto3 1.43.108,
no AWS credentials: the three credential variables were removed from the environment of every command).**
The first six bullets were run again after the round 5 changes. The others are as they stood after round 2
and were not repeated; what rounds 4 and 5 ran on top of them is in `REVIEW_NOTES_r4.md` and `REVIEW_NOTES_r5.md`.

- `python -m pytest -q` on the system Python: **348 passed, 1 skipped, 0 failed.**
  The skipped test builds an error object of the real OpenAI SDK, which is not installed on the system Python.
  33 + 55 + 62 + 9 + 68 + 50 + 40 + 6 + 26 = 349 tests.
  33 tests of the measuring and parsing logic in `streamstats.py` against fake streaming responses
  (events split at every byte position, combined events, missing usage, reasoning text, error events,
  exceptions mid-stream, exact time-to-first-token and rate values against a fake clock).
  55 tests of `kitlib.py`. 62 tests of the numbered scripts. 9 tests of the kit's
  own rules (README headings, pinned requirements, citation comments, the permission list, the audit command).
  68 tests added for the round 1 findings (`tests/test_review_r1.py`), 50 for the round 2 findings
  (`tests/test_review_r2.py`) and 40 for the round 4 findings (`tests/test_review_r4.py`; two older tests were
  changed in round 4, see `REVIEW_NOTES_r4.md`). 6 tests added with `START_HERE.md` after round 4
  (`tests/test_start_here.py`). 26 for the round 5 findings (`tests/test_review_r5.py`; one older test in
  `tests/test_review_r4.py` was changed in round 5, see `REVIEW_NOTES_r5.md`). Eight older tests and one shared test helper were changed in round 2
  because the behaviour they pinned was the finding: the teardown dry run's exit code, the wording of the
  clean line without a state file and with logs kept, the log group request, the wording for a damaged
  state file, the decode rate, and a p95 of fewer than 20 requests.
  AWS is replaced by botocore's Stubber, which validates each request and each canned response against the
  botocore 1.43.108 service model, by a plain fake account with two Regions and two accounts (for "wrong
  Region" and "wrong account"), or by plain fakes for the streaming body. A fixture fails any test that
  opens a socket.
- The same suite in a clean virtual environment built from `requirements.txt` outside this folder, on
  Python 3.13.16 and again on Python 3.14.6: **349 passed, 0 skipped, 0 failed** on each. The 323 tests of
  round 4 passed the same on the Mac (macOS, Python 3.14.7), after a first run there in which the two Ctrl-C
  tests failed because they had been started in the background, where the interrupt signal is ignored; the
  tests changed, the kit did not. The round 5 version was not run on the Mac.
- Every script with `--help`, no credentials, an empty home directory: 8 of 8 exit 0.
- Every script with `--dry-run`, same conditions, with `boto3.client` replaced by a function that aborts:
  6 of 8 exit 0, and `90_teardown.py` and `99_verify_clean.py` exit 3 as designed. 0 AWS calls made;
  56 calls printed.
- Under the same aborting `boto3.client`: `10_deploy.py` with no flag refuses, exit 2, after printing the
  price; `70_change_one_setting.py` with the flag and no state file refuses, exit 2. Neither asked for a
  client. Control: `90_teardown.py` without `--dry-run` did ask for one and was aborted by the stand-in, so
  the stand-in does catch a real run.
- The no-credentials path is a test: `99_verify_clean.py` through real boto3 with no credentials stops
  with "no usable AWS credentials", exit 2, with sockets blocked. It was not run by hand outside the suite.
- **The round 2 money harness, run again against the fixed kit** (a copy of the reviewer's fake account and
  sequence scripts, outside this folder; the real scripts run as processes). All 36 sequences, judged after
  every teardown and every clean check: a sequence fails when one of them exits 0, or prints a clean or
  done verdict, while an endpoint or a log group of this kit still exists in the fake account. On the code
  as reviewed that rule fails 10 of 36. On the fixed kit: **31 pass, 4 are the lost-state
  limit and carry its statement, 1 is the kept-logs request and says LOGS KEPT, 0 fail.**
  The 4 limit sequences are A05b, A06b, A07 (its end) and A09b: both scripts exit 0 with the
  endpoint alive in another Region, as in limits 2 and 3 above. In A06b and A07 the lines say `NO USABLE
  STATE FILE WAS FOUND`. In A05b and A09b a readable state file exists, so the lines cannot say that; they
  say "NOT proof for any other Region or account".
  Four more sequences written for the new route also behave as section 5 says: a damaged file plus
  `--region` and `--prefix` (teardown exits 1, the file's checksum is unchanged, the clean check stays
  INCOMPLETE until the file is moved away, then exits 0 with the no-state-file line); the same with the
  wrong Region named (exit 1, a WARNING names the Region still legible in the file, the clean check finds
  the endpoint); a log group left under another prefix after the endpoint was deleted in the console;
  and a deploy killed after CreateModel followed by a second deploy (refused).
- **The round 2 numbers scripts, run again against the fixed kit** (copies outside this folder).
  20 fake streams: all 20 pass the checks in the reviewer's script; the two inputs of the decode finding now
  give 10.0 for the true 10.0, and 10.0 chunks per second where the true token rate is 20.0 (limit 8).
  A summary of 3 successful requests has no p95. Loopback server through real botocore with event-stream
  framing (127.0.0.1 only, made-up credential strings): 118 requests served, 96 recorded, 0 new connections
  during the three recorded rounds, time to first token 0.102 to 0.104 s against the server's 0.100 s,
  decode 49.1 to 49.3 against 50. `50_invoke.py` stream mode: 0.104 s. The teardown arithmetic in
  8 state scenarios is unchanged; the reviewer's M3 scenario (a 9 h run with an unknown end last week,
  2 h today) now prints `This run: ... 2.00 h ... $2.44` and `All 2 finished runs ... AT MOST 11.00 h`.
- In a scratch copy, 32 deliberate breakages of the round 2 fixes were introduced one at a time (for
  example: the log group pattern never matches, teardown exits 0 with a damaged state file, the state
  file is overwritten, the model is not recorded before CreateModel, the RESULT line drops the no-state
  sentence, the decode rate uses the usage count again, a p95 for any n). The suite failed on 29 of 32 at
  first. Three tests were too loose (a second line carried the same time stamp, two stamps were equal in
  the fake, another part of the message still named the flags). They were tightened, and the suite now
  fails on 32 of 32.
- Raw AWS pages read for what round 2 relies on: the log group name `/aws/sagemaker/Endpoints/[EndpointName]`
  on the SageMaker CloudWatch Logs page, and `logGroupNamePrefix`, `limit` and `nextToken` on
  DescribeLogGroups. Found: 2 of 2. No new API operation and no new request field was added in round 2.
- From round 1, not repeated in round 2: the loopback run with the real OpenAI SDK 3.26.0 (the openai mode
  sent its warm-up and its timed request on 1 connection, did not print the token, and against a 403
  printed `[openai] FAILED: PermissionDeniedError: Error code: 403 ...` and returned normally); the 9 of 9
  raw pages read for the round 1 changes; the one call by hand to the public Hugging Face metadata function
  in `00_check.py` (gated False, licence apache-2.0, 4,022,468,096 parameters); 27 of 27 deliberate
  breakages of the round 1 fixes caught, against the code as it then was; and, from before any review,
  the author's look-up of every parameter and field name on its API reference page (21 of 23 pages), which
  the round 1 reviewer repeated on raw pages (40 of 41 field names; the 41st is item 2 below).

**NOT RUN: every AWS call. None of these has been made by this kit, ever.**

- `sts:GetCallerIdentity`
- `servicequotas:GetServiceQuota`, `servicequotas:GetAWSDefaultServiceQuota`
- `iam:GetRole`
- `sagemaker:CreateModel`, `CreateEndpointConfig`, `CreateEndpoint`, `DescribeEndpoint`, `ListEndpoints`,
  `ListEndpointConfigs`, `ListModels`, `ListTags`, `DeleteEndpoint`, `DeleteEndpointConfig`, `DeleteModel`
- `sagemaker-runtime:InvokeEndpoint`, `InvokeEndpointWithResponseStream`
- The HTTPS POST to `https://runtime.sagemaker.<Region>.amazonaws.com/endpoints/<name>/openai/v1/chat/completions`
- `cloudwatch:GetMetricStatistics`
- `logs:FilterLogEvents`, `logs:DescribeLogGroups`, `logs:DeleteLogGroup`
- The AWS CLI commands in section 3 and section 5 (`iam create-role`, `iam put-role-policy`,
  `iam delete-role-policy`, `iam delete-role`, `service-quotas request-service-quota-increase`,
  `configure sso`, `sso login`, `sts get-caller-identity`). Their option names were checked against the AWS
  CLI reference pages; they were not run.
- The console steps in section 3, step 1 (enable IAM Identity Center, add a user and a permission set).
  Read on the AWS pages, not performed.
- `../common/whats_running.py`, which section 5 tells you to run. It belongs to the shared folder and has
  its own README; this kit's tests do not cover it.
- Also never run: the container, the image pull, the model download, the model itself.

**UNVERIFIED: shapes and behaviours not confirmed in a current AWS doc. Each is marked `# UNVERIFIED:`
in the code where it has code.**

1. `InferenceAmiVersion` = `al2023-ami-sagemaker-inference-gpu-4-1` being right for this image tag. AWS
   sources disagree (section 2). (`kitlib.py`, `create_stack`)
2. `DescribeEndpoint` returning `CreationTime`. It is in the botocore 1.43.108 service model but was not
   on the API reference page read today. The scripts treat it as optional. (`10_deploy.py`)
3. The error text SageMaker returns for a missing resource ("Could not find ..."). The scripts recognise
   `ValidationException` with that wording as "already gone". For a `ValidationException` worded any other
   way they do not guess: they ask the matching List call (`NameContains`, then an exact comparison) and
   treat the resource as gone only when it is no longer listed. Also not confirmed: that a deleted endpoint
   leaves ListEndpoints as soon as DescribeEndpoint stops finding it. (`kitlib.py`, `is_not_found`,
   `listed_by_name`)
4. `ModelStreamError.Message` and `InternalStreamFailure.Message`. Both are in the botocore model; the API
   reference page lists `ErrorCode` for ModelStreamError and no `Message` for either. Only used for error
   text. (`streamstats.py`)
5. That the `0.30.0` image tag exists in the private registry in your Region and contains the
   entrypoint documented at the repository's head commit. Listed on the AWS image page; not pulled.
6. `Qwen/Qwen3-4B` on vLLM 0.30.0 on `ml.g6.2xlarge` starting within 900 seconds. AWS documents this model
   on this instance type with vLLM container 0.20.2; this exact combination was not found in an AWS source.
7. That the AWS container passes the vLLM request fields `stream_options`, `chat_template_kwargs` and
   `ignore_eos` through to vLLM on `/invocations`, and that `chat_template_kwargs: {"enable_thinking": false}`
   switches Qwen3's reasoning off there. The fields exist in vLLM 0.30.0 and an AWS sample passes
   `chat_template_kwargs` in the request body; the Qwen3 model page says the switch is available in vLLM's
   API. Not run. The scripts warn when reasoning text arrives anyway. (`50_invoke.py`, `60_loadtest.py`)
8. Passing the Hugging Face id as `model` on the `/openai/v1` path. AWS examples pass an empty string
   and say the field "is passed through to the container as-is". The AWS container docs example passes
   the model id on InvokeEndpoint. (`50_invoke.py`)
9. That a quota of 1 instance prevents UpdateEndpoint. An inference from "provisions a new fleet".
10. When billing starts and stops, its granularity, and whether a Failed endpoint bills.
11. Whether your identity needs `sagemaker:AddTags` to tag at creation.
12. The trimmed execution-role policy (AWS's CreateModel list without the S3 actions).
13. vLLM's default `gpu_memory_utilization` inside this image: 0.92 in vLLM 0.30.0 source, 0.9 in the AWS
    container docs table. Used only for the arithmetic `00_check.py` prints. (`00_check.py`)
14. The key/value-head adjustment to the KV cache formula. It is this kit's arithmetic, not AWS's.
15. That the log group is not recreated after teardown deletes it. `99_verify_clean.py` would report it.
16. How long a quota request takes. Not published on any page read.
17. That the HTTP client keeps the warm-up connections open and reuses them for the recorded requests when
    the server is SageMaker. It did against a local server (see SAFE). If SageMaker closes idle connections
    quickly, some recorded requests still carry a handshake in their time to first token.
    (`60_loadtest.py`, `50_invoke.py`)
18. That a CreateModel, CreateEndpointConfig or CreateEndpoint which AWS refuses always comes back as an
    HTTP 4xx error. The deploy step relies on it to tell "refused, nothing was created" from "no clear
    answer, it may exist". On anything else it keeps the resource in the state file (the endpoint marked
    unconfirmed), which is the safe side. Since round 4 a 4xx alone is not enough to take a record out:
    the request must have been sent once only (`RetryAttempts` 0 in the answer), the text must not say
    "already exists", and for the endpoint ListEndpoints must no longer list it.
19. That an endpoint, endpoint configuration or model is gone for good once the List call no longer shows
    it. Teardown strikes it from the state file on that evidence. The tags and the name prefix would still
    find it in a later `99_verify_clean.py` if it were not.
20. The text SageMaker returns when a name is taken ("Cannot create already existing endpoint ..."). It is
    from memory of the service, not from an AWS page. The deploy step treats that wording as "the endpoint
    exists", and for any other refusal asks ListEndpoints, so a different wording still keeps the record
    when the endpoint is listed. Also not confirmed: that a new endpoint is listed at once.
    (`kitlib.py`, `says_already_exists`, `create_stack`)

## 9. Sources

All read on 2026-10-07. "Raw" means the page or file was downloaded and parsed directly.

AWS prices and quotas
- AWS Price List, AmazonSageMaker, us-east-1 (raw; publication date 2026-10-06T23:47:07Z): https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonSageMaker/current/us-east-1/index.json
- Amazon SageMaker AI pricing page (no per-instance price or billing granularity found on it): https://aws.amazon.com/sagemaker/ai/pricing/
- AWS General Reference, SageMaker AI endpoints and quotas (raw): https://docs.aws.amazon.com/general/latest/gr/sagemaker.html
- SageMaker AI Regions and quotas: https://docs.aws.amazon.com/sagemaker/latest/dg/regions-quotas.html
- Service Quotas, requesting a quota increase: https://docs.aws.amazon.com/servicequotas/latest/userguide/request-quota-increase.html
- Service Quotas API, GetServiceQuota: https://docs.aws.amazon.com/servicequotas/2019-06-24/apireference/API_GetServiceQuota.html
- Service Quotas API, GetAWSDefaultServiceQuota: https://docs.aws.amazon.com/servicequotas/2019-06-24/apireference/API_GetAWSDefaultServiceQuota.html
- Service Quotas API, RequestServiceQuotaIncrease: https://docs.aws.amazon.com/servicequotas/2019-06-24/apireference/API_RequestServiceQuotaIncrease.html
- AWS CLI, service-quotas request-service-quota-increase: https://docs.aws.amazon.com/cli/latest/reference/service-quotas/request-service-quota-increase.html
- AWS re:Post Knowledge Center, SageMaker insufficient capacity error (page says "last updated 5 months ago"): https://repost.aws/knowledge-center/sagemaker-insufficient-capacity-error
- EC2 accelerated computing instance specifications (raw): https://docs.aws.amazon.com/ec2/latest/instancetypes/ac.html

SageMaker AI hosting
- Delete endpoints and resources: https://docs.aws.amazon.com/sagemaker/latest/dg/realtime-endpoints-delete-resources.html
- Invoke models for real-time inference (streaming, split payload parts, no CLI streaming): https://docs.aws.amazon.com/sagemaker/latest/dg/realtime-endpoints-test-endpoints.html
- Invoke endpoints with OpenAI-compatible APIs (raw; supported containers table, token, IAM actions, the Qwen3-4B example): https://docs.aws.amazon.com/sagemaker/latest/dg/realtime-endpoints-openai-compatible.html
- AWS blog, 20 May 2026, "Announcing OpenAI-compatible API support for Amazon SageMaker AI endpoints": https://aws.amazon.com/blogs/machine-learning/announcing-openai-compatible-api-support-for-amazon-sagemaker-ai-endpoints/
- Blue/green deployments: https://docs.aws.amazon.com/sagemaker/latest/dg/deployment-guardrails-blue-green.html
- CloudWatch metrics for SageMaker AI (raw): https://docs.aws.amazon.com/sagemaker/latest/dg/monitoring-cloudwatch.html
- CloudWatch Logs for SageMaker AI: https://docs.aws.amazon.com/sagemaker/latest/dg/logging-cloudwatch.html
- SageMaker AI roles (CreateModel execution role): https://docs.aws.amazon.com/sagemaker/latest/dg/sagemaker-roles.html
- SageMaker AI API permissions reference (raw): https://docs.aws.amazon.com/sagemaker/latest/dg/api-permissions-reference.html
- AWS service authorization reference, machine-readable file for SageMaker (raw; lists `InvokeEndpoint` and `InvokeEndpointWithResponseStream` as separate actions): https://servicereference.us-east-1.amazonaws.com/v1/sagemaker/sagemaker.json

API references (raw; request and response names checked)
- https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_CreateModel.html
- https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ContainerDefinition.html
- https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_CreateEndpointConfig.html
- https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ProductionVariant.html
- https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_CreateEndpoint.html
- https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_DescribeEndpoint.html
- https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListEndpoints.html
- https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListEndpointConfigs.html
- https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListModels.html
- https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListTags.html
- https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_DeleteEndpoint.html
- https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_DeleteEndpointConfig.html
- https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_DeleteModel.html
- https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_runtime_InvokeEndpoint.html
- https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_runtime_InvokeEndpointWithResponseStream.html
- https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html
- https://docs.aws.amazon.com/IAM/latest/APIReference/API_GetRole.html
- https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_GetMetricStatistics.html
- https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DescribeLogGroups.html
- https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_FilterLogEvents.html
- https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DeleteLogGroup.html
- AWS CLI: https://docs.aws.amazon.com/cli/latest/reference/iam/create-role.html , https://docs.aws.amazon.com/cli/latest/reference/iam/put-role-policy.html , https://docs.aws.amazon.com/cli/latest/reference/iam/delete-role-policy.html , https://docs.aws.amazon.com/cli/latest/reference/iam/delete-role.html
- AWS CLI, IAM Identity Center sign-in (raw): https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html
- IAM Identity Center, enabling it, and the tutorial "Configure user access with the default IAM Identity Center directory" (raw): https://docs.aws.amazon.com/singlesignon/latest/userguide/enable-identity-center.html , https://docs.aws.amazon.com/singlesignon/latest/userguide/quick-start-default-idc.html

The container
- AWS Deep Learning Containers, available images (vLLM and DJL/LMI tables, registry account): https://aws.github.io/deep-learning-containers/reference/available_images/
- AWS Deep Learning Containers, Region availability (registry account per Region): https://aws.github.io/deep-learning-containers/reference/region_availability/
- AWS vLLM container, SageMaker deployment: https://aws.github.io/deep-learning-containers/vllm/deployment/sagemaker/
- AWS vLLM container, configuration (`SM_VLLM_*`): https://aws.github.io/deep-learning-containers/vllm/configuration/
- AWS vLLM container, overview and tested models: https://aws.github.io/deep-learning-containers/vllm/ , https://aws.github.io/deep-learning-containers/vllm/models/
- Repository `aws/deep-learning-containers` at commit `e72722a` (6 October 2026): `docs/vllm/deployment/sagemaker.md`, `docs/vllm/configuration.md`, `scripts/docker/vllm/sagemaker_entrypoint.sh`, `scripts/docker/vllm/sagemaker_args.py`, `docker/vllm/Dockerfile`, `test/vllm/sagemaker/test_sm_endpoint.py`, `test/test_utils/constants.py`: https://github.com/aws/deep-learning-containers
- Repository `aws/model-hosting-container-standards`, `docs/sagemaker/01_quickstart.md`: https://github.com/aws/model-hosting-container-standards/blob/main/docs/sagemaker/01_quickstart.md
- vLLM at tag `v0.30.0`: `vllm/entrypoints/serve/sagemaker/api_router.py`, `vllm/entrypoints/openai/chat_completion/protocol.py`, `vllm/entrypoints/generate/base/protocol.py`, `vllm/config/cache.py`, `vllm/config/scheduler.py`, `vllm/v1/core/kv_cache_utils.py`, `vllm/v1/worker/gpu_worker.py`, `docs/configuration/optimization.md`, `docs/configuration/conserving_memory.md`: https://github.com/vllm-project/vllm/tree/v0.30.0

AWS samples (read for patterns; nothing was copied)
- Repository `aws-samples/sagemaker-genai-hosting-examples` at commit `e6bda8e` (7 October 2026): https://github.com/aws-samples/sagemaker-genai-hosting-examples
  - `03-features/openai/sagemaker-inference-openai-api.ipynb` (vLLM container, Qwen3-4B, ml.g6.2xlarge, bearer token, `/openai/v1`, cleanup order)
  - `01-models/Qwen/Qwen3.6/Qwen3.6-27B.ipynb` (streaming through InvokeEndpointWithResponseStream, `chat_template_kwargs` in the body)
  - `03-features/prefix-aware-routing/prefix_aware_routing.ipynb`, `05-agents/strands/sagemaker-open-ai-compatible-endpoints-agentcore-runtime/Lab1/Lab1-sagemaker-endpoint-qwen3.5-9B.ipynb` and `01-models/NVIDIA/Nemotron-3.5-Lightning-30B-A3B/Nemotron-3.5-Lightning-30B-A3B-NVFP4.ipynb` (`cu130` vLLM image with `al2023-ami-sagemaker-inference-gpu-4-1`)
  - `02-engines/vLLM/README.md`, `02-engines/LMI/LMIv18/LMI_v18.ipynb` (the LMI alternative, not used)

The model and the arithmetic
- Model page: https://huggingface.co/Qwen/Qwen3-4B
- Model metadata (raw; `gated: false`, licence `apache-2.0`, parameter count): https://huggingface.co/api/models/Qwen/Qwen3-4B
- Model configuration (raw; layers, hidden size, heads): https://huggingface.co/Qwen/Qwen3-4B/resolve/main/config.json
- AWS Large Model Inference, instance type selection (weights and KV cache formulas; its worked example is Llama 2, so the page is old): https://docs.djl.ai/master/docs/serving/serving/docs/lmi/deployment_guide/instance-type-selection.html

Package versions
- https://pypi.org/pypi/boto3/json , https://pypi.org/pypi/botocore/json , https://pypi.org/pypi/sagemaker-core/json , https://pypi.org/pypi/openai/json , https://pypi.org/pypi/pytest/json
