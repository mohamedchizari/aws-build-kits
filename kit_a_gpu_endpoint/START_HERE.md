# Kit A: start here

## What this is
One small open-weights model (Qwen3-4B) on one single-GPU Amazon SageMaker AI real-time endpoint, in your own AWS account.
You deploy it, call it three ways, load-test it, change one setting, measure again, delete everything and prove nothing is left.
No script in this kit has ever been run against AWS, so expect to debug the first deploy. This page is the order of work; `README.md` is the reference.

## What it costs, and the one thing that stops the bill
$1.222 for every hour the endpoint exists, traffic or not (ml.g6.2xlarge in us-east-1, price read 2026-10-07): about $3.67 for a 3-hour sitting, about $29.33 if forgotten for 24 hours.
The one thing that stops the bill is `python 90_teardown.py`, run by you in the same sitting. Nothing in this kit shuts the endpoint down for you, and a budget alarm cannot stop one.

## Before you start
1. A sign-in that is not the root user, with AWS CLI v2: `aws configure sso` once, `aws sso login` each session, then check with `aws sts get-caller-identity` (README section 3, step 1).
2. A budget alarm from `../common/budget_alarm.py`. It tells you later that you forgot an endpoint; it stops nothing.
3. The quota request. This is the long wait: the default is 0, so you cannot deploy on day one. Ask for 1 and note the date:
```
aws service-quotas request-service-quota-increase --service-code sagemaker --quota-code L-98BDE811 --desired-value 1 --region us-east-1
```
4. The execution role, which is free. If the endpoint later fails with an access error, README section 3, step 4, has the fallback:
```
aws iam create-role --role-name kitdemo-kita-sagemaker-execution --assume-role-policy-document file://iam/execution_role_trust.json --tags Key=project,Value=aws-kits Key=kit,Value=kit-a-gpu-endpoint
aws iam put-role-policy --role-name kitdemo-kita-sagemaker-execution --policy-name kita-pull-image-write-logs --policy-document file://iam/execution_role_permissions.json
```
5. Python 3.11 or newer, then the offline tests and the preflight. Do not go on until `00_check.py` prints `0 FAIL`:
```
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp config.example.env config.env
python -m pytest -q
python 00_check.py
```

## Problems first
1. The endpoint bills for every hour it exists, traffic or not, and nothing in this kit shuts it down for you.
2. Assume it bills from CreateEndpoint until the endpoint is deleted, whatever its status: when billing starts and whether a Failed endpoint bills were not verified.
3. An exported `AWS_REGION` overrides `config.env`, and in the wrong Region or account every delete answers "not found", which looks exactly like success.
4. If `.state.json` is lost, no script knows where you deployed, and exit code 0 next to the words `NO USABLE STATE FILE WAS FOUND` is not proof that the endpoint is gone.
5. Quota is not capacity: with the quota granted, the endpoint can still go to Failed with InsufficientInstanceCapacity, and then you tear down, wait and try again.
6. AWS sources disagree on the host AMI: if the container fails at start with a driver or CUDA error, tear down and try the two settings in README section 2.

## The commands, in order
One sitting, one terminal, a timer set. Every script takes `--dry-run`, which prints the AWS calls and makes none. Billing starts at the second command.
```
python 10_deploy.py --dry-run
python 10_deploy.py --i-understand-this-bills
python 50_invoke.py
python 55_observe.py
python 60_loadtest.py --label baseline
python 70_change_one_setting.py --set SM_VLLM_MAX_NUM_SEQS=16 --i-understand-this-bills
python 55_observe.py
python 60_loadtest.py --label changed
```
What to see at the end of each:
- The dry run: `DRY RUN finished: N AWS call(s) printed, 0 made. Nothing was created. Nothing bills.` The deploy: `Next: python 50_invoke.py`, and above it a line that starts `InService after`. Its first lines say where it deploys: write the Region and the last four digits of the account into `RESULTS_TEMPLATE.md` then.
- While the endpoint exists, every later script that runs to its end closes with a block marked `BILLING:`, between two lines of `=` signs, that holds `To stop the charge: python 90_teardown.py   then   python 99_verify_clean.py`. The line to read stands above that block:
- `50_invoke.py`: `Invocation modes that worked: 3 of 3 (...)`. Fewer than 3 is exit code 1, and each mode that failed has its own `FAILED` line.
- `55_observe.py`: the log lines `Available KV cache memory` and `Maximum concurrency`. Write your prediction down before you run it. `60_loadtest.py`: a table, then `Per-request rows:` and `Summary rows:` with the two file names.
- `70_change_one_setting.py`: `InService with SM_VLLM_MAX_NUM_SEQS=16.`, a line that starts `Downtime:`, and `Next: python 55_observe.py   then   python 60_loadtest.py --label changed`.

## Tear down and prove it
```
python 90_teardown.py
python 99_verify_clean.py
echo $?
```
- Teardown must end with one line that starts `Teardown done at`. Any other last line comes with a non-zero exit code and says what to do.
- The clean check must print a line that starts `RESULT: CLEAN.` and names the account (last four digits), Region and prefix you deployed in. `echo $?` must then print 0. Exit code 0 is not enough: it also comes with `RESULT: CLEAN ONLY WHERE CHECKED. NO USABLE STATE FILE WAS FOUND`, which is proof for one place only. Read the line.
- Then the shared audit, `python ../common/whats_running.py --region <the AWS_REGION in your config.env> --prefix <your KIT_PREFIX>`: its `RESULT:` line must say `nothing that bills while idle was found, and every check ran (exit 0)`. See the Endpoints list empty in the SageMaker AI console once, and look at the bill the next day.

## If something goes wrong
- The file never to touch: `.state.json`. It is the only record of where the endpoint is billing, and no script deletes, renames or rewrites one it cannot read.
- The script to run: `python 90_teardown.py`, then `python 99_verify_clean.py`. If a deploy stops, fails or gives no clear answer, the endpoint may exist and bill: do what the script prints (README section 4, step 2).
- If the state file is lost or damaged, name the place yourself: `python 90_teardown.py --region <the Region you deployed in> --prefix <your KIT_PREFIX>`. With a damaged file the last line will say `TEARDOWN NOT CONFIRMED`, with exit code 1 on purpose: README section 5, "If the state file is lost or damaged".

## What to write down
`RESULTS_TEMPLATE.md`, as you go and not afterwards. README section 6 lists each item and the printed line it comes from; none needs a stopwatch.

## Where the rest is
README section 2: the prices, the quota, capacity, the host AMI and the memory arithmetic. Section 3: before you start, in full. Sections 4 and 5: each step explained, and every ending of teardown and the clean check. Section 6: what to record. Section 7: what you can and cannot say afterwards. Section 8: what was and was not tested.
