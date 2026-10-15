# common: the budget alarm and the "what is still running" audit

Reviewed independently on 2026-10-07 (round 1): 15 findings, 14 fixed, 1 left open (listed below, in section 8).

Reviewed independently a second time on 2026-10-07 (round 2): 8 findings for this folder, 7 fixed, 1 left open (listed below).

Reviewed independently on 2026-10-07 (round 4): 7 findings for this folder, 6 fixed, 1 stated as a limit, 0 not changed (`REVIEW_NOTES_r4.md`). The limit it added is in section 2, "A kit A state file that is an older copy".

Reviewed independently on 2026-10-08 (round 5): 3 findings touch this folder (F1 and F2 in `budget_alarm.py`, F3 in the exit code table), 3 fixed, 0 stated as a limit. One reader read kit A and this folder; the record is `../kit_a_gpu_endpoint/REVIEW_NOTES_r5.md`, the tests are in `tests/test_review_r5.py`.

Left open after round 2, stated first because it is the one that can cost money:
- **A deploy that no file on this machine records.** If a kit's state file is lost and the Region it ran in was only ever exported in a shell, the default audit does not look in that Region and can exit 0 while the endpoint there bills. This cannot be fixed from here: the audit has nothing to read. What it does now: its `RESULT` line names every kit folder that has no state file, before the words "nothing that bills", and `--all-regions` audits every Region that is enabled for the account. Section 2 has the detail, section 8 the full round 2 record.

## 1. What this is

Two small scripts that sit beside the three kits and do not depend on any kit's own teardown.

- `budget_alarm.py` creates one monthly AWS Budgets cost budget that emails you at chosen percentages of a dollar limit. It can also list existing budgets (`--show`) and delete the one it made (`--delete`). It deletes no other budget.
- `whats_running.py` is a read-only audit. It lists the things from the kits' service families that can bill while idle or that a teardown commonly misses. By default it works out where to look from the kit folders beside this one: every Region and every name prefix in each kit's `config.env`, `config.example.env` and state files (`.state.json` and every other file in the kit folder whose name starts with `.state.json`). It exits 0 only when every check ran in every one of those Regions, none was skipped, the account could be named, no state file was unreadable or damaged, and nothing that bills was found (stored data counts as billing unless you pass `--ignore-storage-only`). A kit folder with no state file does not stop exit 0, because a kit that was never deployed looks the same; the `RESULT` line then says, in plain words, that the audit cannot know where that kit was last deployed.

Nothing in this folder has been run against AWS. It was written without an AWS account. Section 8 says exactly what was and was not tested.

This folder is not a kit. It has no teardown of its own and no results table, so sections 5 and 6 hold "what each script does" and the IAM policy where the kits' READMEs have "Tear it down and prove it" and "What to record".

## 2. Problems first

**The audit cannot find a deploy that no file on this machine records.** (Round 2, sequence U01b. Still open.) A kit that was deployed with `AWS_REGION` exported in the shell records that Region only in its `.state.json`. If that file is then lost, nothing on disk names the Region. A default run audits `us-east-1` and whatever the kit folders still name, finds nothing, and exits 0 while the endpoint bills by the hour somewhere else. The audit cannot know. What it does instead: for each kit folder that has no state file, the `RESULT` line says `kit_a_gpu_endpoint: no state file, so this audit cannot know where that kit was last deployed; only the Regions listed here were checked`, before the words "nothing that bills", and ends with the offer to run `--all-regions` (when several kit folders have no state file, each is named and the consequence is said once). A fresh checkout has no state files either, so you will read that sentence before your first deploy too. It is true then as well.

**A kit A state file that is an older copy reads as healthy.** (Round 4, the reader's sequence W045. A limit, not fixed.) If an old `.state.json` of kit A (finished runs only, in `us-east-1`) is copied back over the file of a deploy that is live in another Region, the folder has a state file, it is readable, and it names no live deploy. The audit looks where that file and its history point, finds nothing, exits 0, and does not even print the no-state-file sentence for kit A, because a state file is there. Nothing on disk tells the audit that the file is stale. Kit A's own README says the same of its two scripts (its section 5, "A place the state file does not name"). If you ever copied or restored a state file, run `--all-regions`.

**`--all-regions` is slow, needs one more permission, and can end at exit 2 in an account with nothing in it.** It asks AWS which Regions are enabled for the account (one call, `account:ListRegions`) and then runs every check in each of them. That is 27 read-only calls per Region in an account with nothing in it, so 459 calls for the 17 Regions that the Account Management guide lists as enabled by default ("Regions launched before March 20, 2019 are enabled by default"), made one after another. How long that takes was not measured, because nothing here was run against AWS. Each call waits up to 10 seconds to connect and 30 seconds for an answer and is tried up to 3 times, so allow minutes, and longer when a service does not answer in a Region. If a service has no endpoint in one of your enabled Regions, that check prints `COULD NOT CHECK` there and the run cannot exit 0: the audit does not guess that "no endpoint" means "nothing there". Whether that happens in your account is UNVERIFIED. Read the `PER REGION` lines at the end, which say Region by Region what was found and which checks did not run. If the Regions cannot be listed at all (the permission is missing, or the call is not in your boto3), the `RESULT` line says `could not list Regions` and the exit code is 2.

**A Region you used and then disabled still bills, and `--all-regions` does not look there.** "Disabling an opt-in Region does not delete the resources in that Region and charges for resources (if any) in that disabled opt-in Region continue to accrue at the standard rate." (Enable or disable AWS Regions in your account, raw text read 2026-10-07.) With `--all-regions` the audit names every Region whose status is `DISABLED` and says it did not audit them. A Region that is being enabled or disabled is audited.

**A damaged state file keeps the audit at NOT CLEAN for as long as it sits in the kit folder.** (Round 2, sequence U02d.) That means any file in a kit folder whose name starts with `.state.json` and that is empty, cut short, unreadable, not a regular file, or was set aside as `.state.json.damaged-...` by the earlier version of kit C. The audit takes what a pattern search can still find in it (Regions, prefixes, account ids, and the Regions and accounts inside ARNs, bucket names and AWS host names) and audits those Regions too. It still exits 2 and names the file in the `RESULT` line, because the part that is missing could have named another Region or another account. The audit never deletes, renames or rewrites the file. To get back to exit 0, follow that kit's own README for a damaged state file, and do not move the file out of the kit folder before you have checked the Regions it names and run `--all-regions`.

**A state file whose history names two accounts never reaches exit 0.** (Round 2, sequence U09.) If one kit folder was used with two AWS accounts, its state file names both. Signed in to either one, the audit sees a record for an account it is not looking at and says NOT CLEAN, every time. That is on purpose and it does not clear by itself. Run the audit once per account with `--only --region R --prefix P`, and read the `LIMITED CHECK` line that it then starts with.

**`--only` and `--ignore-storage-only` can exit 0 while something bills.** You asked for less, so less was checked. Since round 2 the `RESULT` line then starts with `LIMITED CHECK:` and the limit in capitals, before any other word: `THE KIT FOLDERS WERE NOT READ (--only)` or `STORAGE-ONLY ITEMS WERE NOT COUNTED (--ignore-storage-only): 5 OF THEM REMAIN`. In the reviewer's sequences U03, U04 and U04b an endpoint, a managed knowledge base and an open AgentCore session were alive while the audit exited 0 under one of these flags. Do not use either flag for the check you write into a results table.

**The one-screen view cannot see everything a kit makes.** `--after-teardown KIT` marks IAM roles, log deliveries, workload identities, gateway targets, ingestion jobs and open sessions as `not checkable by this audit`. With only those left it exits 0 (the reviewer's sequence U08c), and its `RESULT` line says how many of that kit's resource types it cannot check and that it does not replace the kit's own `99_verify_clean.py`.

**A budget is an alarm, not a brake.** A budget with email alerts sends email. It does not stop, pause or delete anything. No AWS page read for this folder says otherwise, and the Budgets pricing page describes what a budget does as "alert you when your budget thresholds are exceeded (or forecasted to exceed)".

**The alarm is late.** "AWS billing data, which Budgets uses to monitor resources, is updated at least once per day. Keep in mind that budget information and associated alerts are updated and sent according to this data refresh cadence." (Budgets best practices, read 2026-10-07.) Something left on in the evening can run all night before the first email. Size the limit with that in mind, and do not treat a quiet inbox as proof that nothing is running.

**Budget actions would not save you either.** This script creates no budget actions, and they could not stop a SageMaker endpoint if it did: "Your available actions include applying an IAM policy or a service control policy (SCP). They also include targeting specific Amazon EC2 or Amazon RDS instances in your account." (Configuring budget actions, read 2026-10-07.) The Budgets API in boto3 1.43.108 agrees: the action types are `APPLY_IAM_POLICY`, `APPLY_SCP_POLICY` and `RUN_SSM_DOCUMENTS`, and the last one can only `STOP_EC2_INSTANCES` or `STOP_RDS_INSTANCES`. An IAM or SCP action can block new calls. It does not stop an endpoint that is already running (that is this folder's reasoning, not a sentence quoted from AWS). For the record, the first two action-enabled budgets are free: "Your first two action-enabled budgets are free (regardless of the number of actions you configure per budget) per month." (AWS Budgets pricing, read 2026-10-07.)

**Credits can hide spend.** By default AWS counts credits and refunds into a cost budget (`IncludeCredit` and `IncludeRefund` default to true), so an account with credits would get no alert while the credits absorb the usage. `budget_alarm.py` turns those two off by sending `CostTypes`. That member is marked deprecated in the API, so whether the live API still accepts it is UNVERIFIED. If `CreateBudget` rejects it, rerun with `--aws-default-cost-types` and remember that the alarm then tracks cost after credits.

**Forecast alerts are useless at first.** "AWS requires approximately 5 weeks of usage data to generate budget forecasts." The default alerts are on actual spend only.

**The audit sees only what it lists, where it looks.** It covers the service families named in section 5, in the Regions it found or was given, in the one account your credentials are for. Without `--all-regions` it is not an all-Regions scan, and with it, it is still not proof that the account is empty. A check that cannot run (no permission, service not in the Region, operation missing from your boto3, a response without its list) is printed as `COULD NOT CHECK` with the reason and forces exit code 2. So does a check you skip with `--skip`. Neither is ever printed as "none found".

**The audit can only look where it knows to look.** A kit that ran in another Region, or under another prefix, or in another account leaves its things there. The audit reads the kit folders to find those places, and the `RESULT` line names every Region and prefix it audited and the last four digits of the account. Read that line. It cannot know about a deploy made from another computer, or one whose `config.env` was changed afterwards and whose `.state.json` was deleted (the first paragraph of this section). Kit B can be told to keep its state file somewhere else (its `KIT_STATE_FILE` setting); the audit reads only the kit folders. If a kit's state file names an account other than the one you are signed in to, or cannot be read, the result is NOT CLEAN, because what that kit created may be somewhere this run did not look.

**An AgentCore runtime that is still deployed is not free, and its open sessions cannot be seen.** The pricing page says: "Code storage costs: container deployment requires ECR storage (billed separately); direct code deployment bills for the size of the code artifacts you deployed at S3 Standard rates." Kit C uses direct code deployment. A session bills through its idle time: "With consumption pricing, you only pay for actual resource consumption during your session, which spans from microVM ready, initialization, active processing, idle periods, until session termination". No call in boto3 1.43.108 lists the sessions of a runtime (`bedrock-agentcore` has `ListSessions`, but that is the AgentCore Memory API and needs a memory id), so the audit cannot see an open session. What ends a session's compute is the runtime's own two time limits: the defaults are "900 seconds (15 minutes)" idle and "28800 seconds (8 hours)" lifetime, and "Runtimes that use a capacity provider (Instances) accept up to 1209600 seconds (14 days)". Kit C sets 120 and 900 seconds. The audit prints each runtime's two values. (AgentCore pricing, and the AgentCore lifecycle settings page, raw text read 2026-10-07.)

**The most expensive quiet mistake is an OpenSearch Serverless Classic collection.** "You will be billed at least for a minimum of 2 OCUs (1 OCU [0.5 x 2] indexing includes primary and standby, and 1 OCU [0.5 x 2] search includes one replica for HA) for the first collection in an account." At $0.24 per OCU per hour (US East (N. Virginia), US East (Ohio) and US West (Oregon); every other Region on the price data read was higher) that is at least $0.48 per hour, $11.52 per day, with zero queries. Without standby replicas ("0.5 OCU for indexing and 0.5 OCU for search") it is $0.24 per hour. Source: Amazon OpenSearch Service pricing and the price data that page loads, read 2026-10-07. Deleting a Bedrock knowledge base does not delete its collection: "Delete the vector store itself for your knowledge base." (Bedrock docs, delete a knowledge base, read 2026-10-07.)

**Your email address on a command line is remembered by your shell.** `--email you@example.com` lands in the shell's history file and is visible in the process list while the script runs. Section 3 shows the way that avoids both.

**AWS now has a real spend limit that pauses resources, but not for an existing account.** See section 3, "The account-level spend limit". Do not plan around it unless your account was created through the new sign-up.

## 3. Before you start

Steps only the account owner can do.

1. Sign in and make credentials available to the shell in whatever way you normally do (for example an SSO profile). No script here reads or stores credentials.
2. Install the pinned packages: `python -m pip install -r requirements.txt` (Python 3.11 or newer).
3. Give the identity you run as the permissions in section 6. The audit needs only the read policy.
4. Decide a monthly dollar limit and which address should get the alerts.
5. Decide how to hand the address to the script. Two ways, and only the second keeps it out of your shell history:
   - On the command line: `--email you@example.com`. Simple, but the address is written to your shell history and shows in the process list. Putting `BUDGET_ALARM_EMAIL=you@example.com` in front of the command on the same line has the same problem.
   - From the environment, typed at a prompt and not as a command:
     `read -r BUDGET_ALARM_EMAIL` (type the address, press Enter), then `export BUDGET_ALARM_EMAIL`, then run the script without `--email`, then `unset BUDGET_ALARM_EMAIL`. What you type in answer to `read` is input, not a command, so the shell does not record it. Several addresses: separate them with commas.

### The account-level spend limit (an owner step, console only, and probably not available to you)

Checked on 2026-10-07 against the AWS Free Tier FAQ and the AWS Account Management guide.

- **It exists.** The FAQ says: "When you upgrade to a Paid plan, you can set a monthly spend limit for your project starting at $20. You receive notifications at 50%, 75%, and 90% of your project's spend limit." and "If your project reaches its spend limit, AWS will pause your project and stop its resources until the next month, unless you increase the spend limit." The guide adds: "AWS pauses your project and stops all resources. Your data is preserved." and "If you take no action within 90 days of your project being paused, AWS permanently deletes your project data."
- **Who can use it.** Only accounts inside the new sign-up experience ("Sign up for AWS (new)", where an account is called a project), on the Paid Plan: "You must be on a Paid Plan to create a spend limit." Limits "can only be managed by project owners". The whole experience is in limited release: "We're currently releasing our new experience to a limited number of customers. You might not be able to access this experience yet."
- **An existing account.** No page read describes a way to put a spend limit on an account created the classic way ("Sign up for AWS (advanced)"). The guide's comparison of the two sign-up routes has the row "Create spend limits for your accounts" with Yes for the new sign-up and No for the advanced one, and it describes the opposite direction only, which removes the limit: "You cannot create a spend limit if you activate advanced features." Treat it as not available on an existing account. The only route would be a new sign-up, which creates a new and separate AWS account. The sign-up page says a person who is not eligible for the Free Tier is "placed on the Paid Plan" and "can set spend limits". That route was not tested, and it has costs for these kits: the project's Region is assigned for you (US East (Ohio), `us-east-2`, for a United States address), and for Amazon Bedrock "Global cross-Region inference and Geographic cross-Region inference are not supported."
- **How (console steps, quoted from "Create a spend limit in AWS Settings").**
  1. Open AWS Settings at https://settings.aws.com.
  2. In the main navigation pane, choose **Billing**.
  3. In **Cost by project**, for **Spend limit**, choose **Set limit** for a project.
  4. You can either choose the recommended spend limit or a custom limit.
  5. If you choose a custom limit, enter the custom amount.
  6. Choose **Set spend limit**.
  7. To customize your spend limit with early cost controls, you can select **Stop new resource launches**, **Pause idle resources**, or **Pause top cost drivers**.
  8. Choose **Save early cost controls**.
- **Limits of it.** The floor is "the greater of $20 or a conservative estimate of your likely spend". The optional "Pause idle resources" control does pause SageMaker endpoints, but only "if the endpoint had zero invocations in the past 14 days", which is too slow to protect a weekend build. Up to 10 projects can have a limit.
- **Not scripted here.** The page documents the console only. No API, CLI command or SDK call for it was found, and the Budgets model in boto3 1.43.108 has no spend-limit operation. The guide says "Spend limits are a type of AWS Budgets", so one might appear in `budget_alarm.py --show`; that is UNVERIFIED.

## 4. Run it

All commands are run from this folder. The audit can be run from anywhere: it finds the kit folders from its own location, not from where you stand.

1. See what a budget request would look like. Makes no AWS call:
   `python budget_alarm.py --email you@example.com --dry-run`
2. List the budgets that already exist. Read-only:
   `python budget_alarm.py --show`
3. Create the budget (default limit 25 US dollars, alerts at 50, 80 and 100 percent of actual spend). With the address in `BUDGET_ALARM_EMAIL` (section 3, step 5):
   `python budget_alarm.py --limit 25 --thresholds 50,80,100 --i-understand-this-changes-my-account`
   or, accepting that the address goes into your shell history:
   `python budget_alarm.py --email you@example.com --limit 25 --thresholds 50,80,100 --i-understand-this-changes-my-account`
4. Confirm it:
   `python budget_alarm.py --show`
5. See where the audit would look and which calls it would make. Makes no AWS call, and exits 3, not 0:
   `python whats_running.py --dry-run`
6. Run the audit. Read-only. It audits every Region and prefix it finds in the three kit folders, plus `AWS_REGION` and `KIT_PREFIX` from the environment, plus the kits' defaults `us-east-1` and `kitdemo`:
   `python whats_running.py; echo "exit code $?"`
   Then read the `RESULT:` line from its first word. If you gave `--only` or `--ignore-storage-only` it starts with `LIMITED CHECK`. Then it says `NOT CLEAN` and why; or, when nothing was found, it first names every kit folder that has no state file and only then says that nothing that bills was found. `Audited:` names the account (last four digits), the Regions and the prefixes. Under `INFORMATIONAL` it lists your budgets; that row is free information and never changes the result.
7. Add a Region or a prefix the kit folders do not know about (these ADD to what was found; they never replace it):
   `python whats_running.py --region us-west-2 --prefix acme`
8. If the `RESULT` line says a kit folder has no state file and you have ever deployed that kit, audit every Region that is enabled for the account. Slow (section 2), and it needs `account:ListRegions` (section 6):
   `python whats_running.py --all-regions; echo "exit code $?"`
   Read the `PER REGION` lines. To see the calls first: `python whats_running.py --all-regions --dry-run`.
9. After a kit's teardown, get one screen for that kit: every kind of thing the kit can create, each marked `checked: none found`, `FOUND`, `COULD NOT CHECK` or `not checkable by this audit` (with the console place to look):
   `python whats_running.py --after-teardown a` (or `b`, or `c`)
   The whole audit still runs and the `RESULT` line is for the whole audit. On top of that, any row of that kit marked `FOUND` makes the exit code 2, whatever the thing costs while idle (an endpoint configuration or a guardrail is free, and is still something the kit's teardown should have removed). The line then says that the kit's own clean check would say NOT CLEAN. This screen does not replace the kit's own `99_verify_clean.py`: run both.
10. When all three kits are finished, remove the budget if you no longer want it:
   `python budget_alarm.py --delete --i-understand-this-changes-my-account`

Other switches on the audit:
- `--only --region R --prefix P` audits only what you name and does not read the kit folders. Nothing then checks that these are the places the kits used. The `RESULT` line starts with `LIMITED CHECK: THE KIT FOLDERS WERE NOT READ (--only)`. It cannot be combined with `--all-regions`.
- `--skip FAMILY` skips one family (`sagemaker`, `bedrock`, `opensearch`, `s3vectors`, `s3`, `agentcore`, `ecr`, `logs`). A run with a skipped check cannot exit 0. The same holds when a Region does not offer one of these services: that check prints `COULD NOT CHECK`, and the audit cannot exit 0 for that Region whether you skip the check or not. In that case use `--after-teardown KIT`: its screen shows whether every row of your kit was checked, and lists by name the checks that did not run.
- `--ignore-storage-only` lets storage-only items pass (they are still listed). The `RESULT` line starts with `LIMITED CHECK: STORAGE-ONLY ITEMS WERE NOT COUNTED (--ignore-storage-only)` and how many remain. If an AgentCore runtime is among them, the same capitals say that its open sessions cannot be listed. With `--after-teardown KIT` a `FOUND` row of that kit still makes the exit code 2.
- `--json` prints JSON. It carries `verdict` (`clean`, `not clean`, `could not check` or `skipped`), `verdict_reasons`, `result_line` (the same line the text output ends with), `limited_check`, `damaged_state_files`, a `skipped` block, `all_regions`, `informational` (the budget row), and `audited` (account last four, Regions, prefixes, the state files read, and the kit folders that have none).
- `--kits-dir DIR` if the kit folders are not beside this one.

Other switches on the budget: `--name`, `--forecast-threshold`, `--aws-default-cost-types`. Both scripts take `--dry-run`, which prints the API calls and makes none.

### Exit codes, all four folders in one table

The table below was read on 2026-10-07 at 13:35 UTC from the code of all four folders as it stood at that minute (each kit's `kitlib` and its numbered scripts). The kit A column and the `budget_alarm.py` column were brought up to date in round 4 (kit A code 1 and 2: a stop after a create or delete call was sent is 1, never 2); the kit C column was brought up to date the same day from its round 4 changes (codes 1, 2 and 5); the kit B column was not re-read then. The three kits were being revised that day, so if a kit has changed since, its own README is the authority for that kit. The codes are not the same across folders. Do not carry a habit from one folder to the next: read the `RESULT` line, and in a shell script treat anything other than 0 as not clean.

| Code | `common/whats_running.py` | `common/budget_alarm.py` | kit A | kit B | kit C |
| --- | --- | --- | --- | --- | --- |
| 0 | clean: every check ran, none skipped, account named, no state file unreadable or damaged, nothing bills, and with `--after-teardown KIT` no row of that kit `FOUND`. Read the line: it can start with `LIMITED CHECK`, or name a kit folder with no state file | done (also every `--dry-run`) | done; `90_teardown.py`: nothing of the kit remains where it acted; `99_verify_clean.py`: CLEAN (read the line: `CLEAN ONLY WHERE CHECKED` when there is no state file, `LOGS KEPT` with `--allow-logs`) | done; `90_teardown.py`: every delete succeeded and nothing of kit B is listed afterwards; `99_verify_clean.py`: CLEAN | done; `99_verify_clean.py`: CLEAN |
| 1 | the script crashed; treat as not clean | an AWS call failed or got no clear answer (`OUTCOME UNKNOWN`), or the budget named for `--delete` does not exist | AWS returned an error, or something unexpected happened; any script that stopped after it had sent a create or delete call, whatever stopped it except Ctrl-C, which is 130 (the last line names the calls, and an endpoint may exist and bill); `90_teardown.py`: something remains, the tag check was incomplete, or the state file is damaged; `99_verify_clean.py`: NOT CLEAN or INCOMPLETE | failed or stopped (also a damaged state file, a setting with a bad value, or the answer "no" to the teardown question); `99_verify_clean.py`: NOT CLEAN | failed, something is left, or NOT VERIFIED; any stop after a create call was sent (deploy, observability, gateway); `90_teardown.py` when a recorded session could not be stopped |
| 2 | NOT CLEAN: something bills, or a check could not run or was skipped, or the scope is in doubt (a damaged state file, another account, Regions that could not be listed), or `--after-teardown KIT` found a row of that kit | not used | STOP before it created or deleted anything in this run (configuration, credentials, state file names another place, damaged state file without `--region` and `--prefix`, a failed load-test warm-up); also a bad command line | refused (billing flag missing); also a bad command line | refused before anything was sent: bad arguments, bad configuration, no credentials, or billing flag missing |
| 3 | `--dry-run`: nothing was checked | refused: flag missing, or `--delete` aimed at a budget this script did not create | `--dry-run` of `90_teardown.py` or `99_verify_clean.py`: nothing was checked or deleted | `99_verify_clean.py`: kits clean, but an OpenSearch Serverless collection exists | `--dry-run` of `90_teardown.py`, `optional_gateway/90_teardown_gateway.py` or `99_verify_clean.py`: nothing was checked or deleted |
| 4 | not used | not used | not used | `99_verify_clean.py`: INCOMPLETE | STOPPED: `.state.json` records another Region, prefix or account, or cannot be read, or names resources without saying where they are |
| 5 | not used | not used | not used | `--dry-run` of `90_teardown.py` or `99_verify_clean.py`: nothing was checked or deleted | INCOMPLETE: `99_verify_clean.py`; also `90_teardown.py --region R --prefix P` beside a state file it cannot use, when every delete worked (1 if one failed) |
| 64 | bad command line | bad command line | not used | not used | not used |
| 130 | not used | not used | interrupted with Ctrl-C; the last line names any create or delete call already sent | interrupted with Ctrl-C (`30_deploy_kb.py`, `40_create_guardrail.py`, `50_run_eval.py`, `90_teardown.py`) | interrupted with Ctrl-C |

The traps:
- 1 means "something is left" in the kits but "the script crashed" here. In kit A, 1 is also "stopped half way": something was created or deleted before the stop.
- 2 means NOT CLEAN here but "refused or could not run" in the kits.
- 3 and 5 swap meanings between kit B and kit C, and a dry run is 3 here and in kits A and C, 5 in kit B, and 0 in `budget_alarm.py`.
- A damaged state file gives 2 here, 1 or 2 in kit A, 1 or 4 in kit B, and 4 or 5 in kit C.
- Only 0 means "done" or "clean" everywhere, and even 0 has to be read with its line: here and in kit A the line can say that no state file was found.

## 5. What each script does and does not do

### budget_alarm.py

Does:
- Creates one `COST` budget, `MONTHLY`, in US dollars, named `<KIT_PREFIX>-monthly-cost` unless you pass `--name`, tagged `project=aws-kits` and `created-by=aws-kits-budget-alarm`.
- Adds up to five alerts (the API maximum) to up to ten email addresses each.
- Refuses to create or delete without `--i-understand-this-changes-my-account`, and makes no AWS call when it refuses.
- Refuses a limit or threshold that is zero, negative, not a number or infinite, and a limit that would round to zero cents.
- Prints what it expects the budget to cost (nothing: "You can monitor and receive notifications on your budgets free of charge.") before acting.
- Says which account it acted in, by its last four digits, in every mode that calls AWS: `Created budget '...' in the account ending 1234`. Read it: under the wrong profile the budget lands in another account.
- Writes the budget name and the last four digits of that account to `.state.json` in this folder so `--delete` can find it.
- Deletes only a budget it created. `--delete` goes ahead when `.state.json` records the name and you are signed in to the account the record was written for, or, failing either, when the budget carries the `created-by` tag above. Otherwise it refuses (exit 3) and makes no delete call. A record for another account is left as it is. If AWS says the recorded budget no longer exists, it clears the record and exits 0.
- Says `OUTCOME UNKNOWN`, not "not created", when `CreateBudget` was sent and no clear answer came back (a timeout, a dropped connection, a 5xx answer, a 4xx answer to a request the SDK had sent again, or a sign-in error raised while a retry was being signed). The budget may exist. It writes no record then and tells you to look with `--show`; exit code 1. The same for `DeleteBudget`: `OUTCOME UNKNOWN`, not "not deleted", and the record stays.
- Passes every line it prints, AWS error text included, through one filter that masks the addresses you supplied and cuts any 12-digit number to its last four digits.
- With `--show`, marks the budget it created (the one `.state.json` records) and points to the audit, which lists the same budgets under `INFORMATIONAL`.

Does not:
- Stop, pause or delete any resource, ever.
- Create budget actions, SNS topics or anything else.
- Store the email address. It goes to AWS in the `CreateBudget` call and nowhere else: not to `.state.json`, not to a log. On the screen it appears only masked, as the first character of the part before the `@` and nothing of the domain (`o***@***`). Of the account id only the last four digits are stored (since round 4), which is why the budget ARN is not in `.state.json`.
- Show subscriber addresses in `--show`.
- Promise what AWS's own error text contains. The filter removes the addresses you gave this run and anything that looks like an account id. Whether AWS ever repeats an address in an error is not known, and the filter cannot mask an address it was not given, such as another subscriber on a budget that already exists.
- Confirm that an alert email will arrive. Only a real alert proves that.
- Update an existing budget. To change it, delete and create again.

### whats_running.py

Does:
- Works out where to look. It reads, in each `../kit_*` folder, `config.env` and `config.example.env` (`AWS_REGION`, `KIT_PREFIX`) and every file whose name starts with `.state.json`: the state file with any history in it, a half-written `.state.json.tmp` (kit A, kit B) or `.state.json.tmp-<pid>` (kit C), a `.state.json.damaged-...` file that the earlier kit C set aside, and any copy made by hand. From a state file it takes keys such as `region`, `prefix`, `account_id`, and also the Regions, accounts and kit names inside ARNs, bucket names and AWS host names. From your `config.env` it also takes a Region or prefix on a line the plain reading skips, such as one you commented out after a deploy; for a prefix that line must assign it (`KIT_PREFIX=...` or `KIT_PREFIX: ...`, then the end of the line or a comment), so a sentence that only mentions `KIT_PREFIX` adds nothing. It adds `AWS_REGION` and `KIT_PREFIX` from the environment, anything you pass with `--region` and `--prefix`, every enabled Region with `--all-regions`, and the kits' defaults `us-east-1` and `kitdemo`. It prints where each value came from and which state files it found.
- Treats the three states of a kit folder differently. A state file that reads: its Regions are audited. No state file at all: the audit goes on, can exit 0, and the `RESULT` line says `<kit folder>: no state file, so this audit cannot know where that kit was last deployed; only the Regions listed here were checked` (several kits are named one by one and the consequence is said once). A state file that is empty, cut short, unreadable or set aside as damaged: it is read as far as a pattern search allows, the result is NOT CLEAN (exit 2), and the `RESULT` line names the file.
- With `--all-regions`, asks the Account Management API which Regions are enabled (`ListRegions`, one call per 50 Regions) and audits every Region whose status is not `DISABLED`. The Regions that are `DISABLED` are named and not audited. If the call fails, returns no enabled Region, or returns an entry that is not a Region name, the result is NOT CLEAN and the line says `could not list Regions`.
- Lists your AWS Budgets under `INFORMATIONAL` and says which one `budget_alarm.py` created (by the record in this folder's `.state.json` when that record is for the account being audited, or by the tag `created-by=aws-kits-budget-alarm`; tags are read for at most 20 budgets). A record for another account is said in a `NOTE`. A budget with email alerts is free and is not a leftover, so this row never changes the `RESULT` or the exit code: not when a budget exists, not when none does, not when the budgets cannot be read (the row then says `COULD NOT READ`).
- Starts the `RESULT` line with `LIMITED CHECK:` and the limit in capitals when `--only` or `--ignore-storage-only` was given.
- With `--after-teardown KIT`, exits 2 when any row of that kit is `FOUND`, whatever it costs while idle, and says that the kit's own clean check would say NOT CLEAN. One row is not claimed for the kit's own check: the `aws/spans` log group, which kit C does not create and which its clean check prints as information, not as a leftover.
- Asks STS which account the credentials are for, prints its last four digits only, and compares it with every account a kit's state file names. A different account makes the result NOT CLEAN.
- Lists everything below in each Region, whatever its name, with these exceptions. ECR repositories are listed only when the name contains a kit prefix. S3 buckets are listed only when they look like a kit's (see the next point). CloudWatch log groups are listed when they sit under the kits' service prefixes or contain a kit prefix.
- Finds kit S3 buckets three ways: by the kits' name patterns (`-kita-`, `-fedrag-` or `-kitc-` anywhere in the name, so a changed prefix does not hide one), by a name that starts with a kit prefix, and by the tag `project=aws-kits` on a bucket with any other name. For each one it says `empty` or `not empty` from one `ListObjectVersions` call for a single key. It reads no object.
- Finds log groups under `/aws/sagemaker/Endpoints/`, `/aws/bedrock-agentcore/`, `/aws/vendedlogs/bedrock-agentcore/` and `aws/spans` whatever the kit prefix is, and any other log group whose name contains a kit prefix or its underscore form (kit C names its runtime `my_kit_...` for the prefix `my-kit`).
- Reads each AgentCore runtime's detail and prints its compute type and its two session time limits.
- For each item prints the name, created time, state, whether it bills while idle (`yes`, `storage only`, `no`, or `unknown`, which is treated as `yes`), the reason, and the source page with the date it was read.
- Follows pagination on every list call.
- Ends a run over more than one Region with one `PER REGION` line per Region: what was found there and which checks did not run.
- Reports any check that could not run as `COULD NOT CHECK: <reason>` and exits 2.
- Cuts every 12-digit number in names and error text to its last four digits, so a bucket shows as `kitdemo-kitc-code-[account ending 1234]-us-east-1`. You know your own account id; put it back when you need the real name.

Does not:
- Create, change or delete anything. Every call goes through one function that refuses any operation outside a fixed list of List, Describe, Get and BatchGet operations. It does not delete, rename or rewrite any file in a kit folder either, damaged or not.
- Scan every Region unless you pass `--all-regions`, and then not a Region that is disabled. It never looks into any account but the one your credentials are for.
- Know where a kit ran when the kit folder has no state file and no other file names the Region (section 2, first paragraph).
- Tell "this service is not offered in this Region" from "this check failed". Both print `COULD NOT CHECK` and both stop exit 0.
- Replace a kit's own `99_verify_clean.py`. Kit B's and kit C's scripts look for things this audit does not, such as the kit's IAM role and, for kit C, its log deliveries and workload identity.
- See an open AgentCore runtime session. No API lists them (section 2).
- Check these, which a kit or the console could also leave behind: S3 buckets that neither look like a kit's nor carry the tag, IAM roles and policies, CloudWatch log delivery sources, destinations and deliveries, AgentCore workload identities, gateway targets (seen only through their gateway), browsers, code interpreters, capacity providers and harnesses, Cognito user pools, Secrets Manager secrets, KMS keys, Lambda functions, VPC endpoints and NAT gateways, EC2 instances, SageMaker domains and user profiles, Bedrock Agents (the older service), Bedrock Marketplace endpoints (these show up as SageMaker endpoints), and the vector store of a knowledge base when it is not S3 Vectors or OpenSearch Serverless (the knowledge base is then rated `unknown`). `--after-teardown` lists the ones each kit can create and where to look for them.
- Tell a serverless SageMaker endpoint from an instance-backed one. Every endpoint is reported as billing.
- Read your bill. For dollars actually charged, use Billing and Cost Management.

How "bills while idle" is decided (all pages read 2026-10-07; the same text is printed beside each item). Dollar figures carry their Region where the page showed one. Where it showed none, the row says so.

| Item | Verdict | Basis |
| --- | --- | --- |
| SageMaker endpoint | yes | "Delete endpoints to stop incurring charges." and "You are charged for usage of the instance type you choose." |
| SageMaker inference component | yes | Billed through its endpoint's instances. "An endpoint can scale to and from zero instances only if it hosts inference components." The copy count is not visible in the listing, so it is treated as billing. |
| SageMaker training job, `InProgress` or `Stopping` | yes | "You are charged for usage of the instance type you choose." Every training job is listed once, without a status filter, so neither state is missed. |
| SageMaker training job that has ended but holds a warm pool (`Available` or `InUse`) | yes | "SageMaker AI managed warm pools are a billable resource." |
| SageMaker training job in a status the audit does not know | unknown | Not mapped to a billing statement. |
| SageMaker notebook instance, running | yes | "You are charged for the instance type you choose, based on the duration of use." |
| SageMaker notebook instance, stopped | unknown | UNVERIFIED: no page read says whether the stopped instance's storage volume is billed. |
| SageMaker Studio app, running | yes | "The compute is only charged for the instance used when the JupyterLab space is running." |
| SageMaker Studio space | storage only | "Storage charges for a JupyterLab space accrued until it is deleted." |
| SageMaker model, endpoint configuration | no | No price line on the pricing page (absence, not a statement). "Deleting an endpoint will not delete the endpoint configuration or the SageMaker AI model." |
| Bedrock Provisioned Throughput | yes | Priced "per hour per model unit". |
| Bedrock custom model | storage only | "Price to store each custom model per month". |
| Bedrock imported model | storage only | "Monthly storage cost per Custom Model Unit"; compute scales to zero after 5 minutes without invocations. |
| Bedrock custom model deployment | unknown | UNVERIFIED: no price line found. |
| Bedrock knowledge base, managed | storage only | "Index Storage ... $5.00 per GB of raw data / month". No Region is shown beside that figure in the page text read. |
| Bedrock knowledge base, type `VECTOR` on S3 Vectors or OpenSearch Serverless | no | No standing price line (absence, not a statement). The vector store bills separately, and another check in this audit lists it. |
| Bedrock knowledge base of any other type or store (Aurora or RDS, Neptune Analytics, OpenSearch managed cluster, Kendra, SQL, third party, or type not returned) | unknown | The audit does not list that store, and it can bill around the clock where it lives. |
| Bedrock knowledge base data source | no | No standing price line (absence, not a statement). |
| Bedrock guardrail | no | Priced per unit processed, for example "$0.15 per 1,000 text units". No Region is shown beside that figure in the page text read. |
| OpenSearch Serverless collection, Classic or generation not determined | yes | The 2 OCU minimum quoted in section 2. $0.24 per OCU per hour is the us-east-1, us-east-2 and us-west-2 rate and a floor elsewhere. |
| OpenSearch Serverless collection, NextGen, group minimum 0 | storage only | "There is no minimum OCU requirement - Indexing and Search OCUs scale to zero after 10 minutes of inactivity." |
| OpenSearch Serverless collection or group, NextGen, group minimum above 0 | yes | "OpenSearch Serverless still maintains the specified minimum number of OCUs, and billing reflects that minimum." |
| OpenSearch Serverless collection group with no collections | no | "Empty collection groups do not consume OCUs or enforce capacity limits." |
| S3 Vectors vector bucket, index | storage only | Pricing row "S3 Vector Storage /Month - monthly logical storage of vector data, key, and metadata". |
| S3 bucket that looks like a kit's, empty or not | storage only | "S3 Standard - General purpose storage for any type of data, typically used for frequently accessed data", priced per GB per month. The dollar rate is filled in per Region by the pricing page and is not quoted here. An empty bucket has nothing to bill but is still a leftover. |
| AgentCore runtime, direct code deployment (kit C) | storage only | "direct code deployment bills for the size of the code artifacts you deployed at S3 Standard rates". Open sessions bill and cannot be listed (section 2). |
| AgentCore runtime, container deployment | storage only | "container deployment requires ECR storage (billed separately)". Open sessions bill and cannot be listed. |
| AgentCore runtime with a capacity provider (Instances compute) | yes | "Charged per instance-hour from provisioning (boot) until the instance is stopped or terminated, with an approximately 1-minute minimum." |
| AgentCore gateway | storage only | "$0.02 per 100 tools indexed per month" when tools are indexed for search; calls are per use. No Region is shown beside the figure on the page. |
| AgentCore memory | storage only | "$0.10 per GB-month" short-term storage; "$0.75 per 1,000 records/month" long-term (built-in). No Region is shown beside the figures on the page. |
| ECR repository (kit prefix), CloudWatch log group | storage only | Stored images and log data are billed while kept. No dollar figure is given here because none was verified today. |
| AWS Budgets budget (the one `budget_alarm.py` creates, or any other) | not rated: listed under `INFORMATIONAL`, never part of the result | "You can monitor and receive notifications on your budgets free of charge." `budget_alarm.py` creates no budget actions. The audit does not look at whether a budget made elsewhere has actions. |

## 6. Required IAM permissions

Minimal read policy for `whats_running.py` and for `budget_alarm.py --show`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AwsKitsAuditReadOnly",
      "Effect": "Allow",
      "Action": [
        "sagemaker:ListEndpoints",
        "sagemaker:ListEndpointConfigs",
        "sagemaker:ListModels",
        "sagemaker:ListInferenceComponents",
        "sagemaker:ListTrainingJobs",
        "sagemaker:ListNotebookInstances",
        "sagemaker:ListApps",
        "sagemaker:ListSpaces",
        "bedrock:ListKnowledgeBases",
        "bedrock:GetKnowledgeBase",
        "bedrock:ListDataSources",
        "bedrock:ListGuardrails",
        "bedrock:ListProvisionedModelThroughputs",
        "bedrock:ListCustomModels",
        "bedrock:ListImportedModels",
        "bedrock:ListCustomModelDeployments",
        "aoss:ListCollections",
        "aoss:BatchGetCollection",
        "aoss:ListCollectionGroups",
        "s3vectors:ListVectorBuckets",
        "s3vectors:ListIndexes",
        "s3:ListAllMyBuckets",
        "s3:GetBucketTagging",
        "s3:ListBucketVersions",
        "bedrock-agentcore:ListAgentRuntimes",
        "bedrock-agentcore:GetAgentRuntime",
        "bedrock-agentcore:ListGateways",
        "bedrock-agentcore:ListMemories",
        "ecr:DescribeRepositories",
        "logs:DescribeLogGroups",
        "budgets:ViewBudget",
        "budgets:ListTagsForResource",
        "account:ListRegions"
      ],
      "Resource": "*"
    }
  ]
}
```

Extra statement needed only to create or delete the budget (on top of the read policy above; `--delete` reads the budget's tags when `.state.json` has no record of it):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AwsKitsBudgetWrite",
      "Effect": "Allow",
      "Action": ["budgets:ModifyBudget", "budgets:TagResource"],
      "Resource": "*"
    }
  ]
}
```

Notes on the policy:
- `sts:GetCallerIdentity` is used by both scripts to find the account id and needs no permission: "No permissions are required to perform this operation."
- New since the round 1 review: `s3:ListAllMyBuckets` (the `ListBuckets` call), `s3:GetBucketTagging`, `s3:ListBucketVersions` (the `ListObjectVersions` call; the API page says "Be aware of the name difference"), `bedrock-agentcore:GetAgentRuntime`, and `budgets:ListTagsForResource`.
- New since the round 2 review: `account:ListRegions`, used only by `whats_running.py --all-regions` ("`account:ListRegions` (needed to view the list of AWS Regions and whether they are currently enabled or disabled)", Account Management guide). Without it `--all-regions` says `could not list Regions` and exits 2; a run without that flag does not make the call. `budgets:ListTagsForResource` moved from the write statement to the read policy, because the audit's budget row now uses it; the reference page gives it the access level Read. `budgets:ViewBudget` was already here for `--show` and now also serves the audit's budget row. Without the two budget actions the row says `COULD NOT READ` or that tags could not be read, and the result is not affected.
- The three S3 actions on `"Resource": "*"` let the audit read the tags of every bucket and ask any bucket for one object key. The script asks for a key only from buckets it lists as a kit's. The policy grants no `s3:GetObject`: no object can be read with it.
- All 35 action names above were looked up on the Service Authorization Reference pages on 2026-10-07 (raw page text). 33 appear there as `prefix:Action`, including `aoss:ListCollectionGroups`, which the first version of this README could not confirm ("IAM action: aoss:ListCollectionGroups" is on the page now), and `account:ListRegions`, added in round 2. The two S3 Vectors actions appear in that service's action table by operation name (`ListVectorBuckets`, `ListIndexes`) under the service prefix `s3vectors`.
- The policy grants read access to names, states, tags and settings only. It grants no invoke, create, update or delete action.
- Without one of these permissions the matching check prints `COULD NOT CHECK` and the audit exits 2. It does not quietly pass. The one exception is the budget row, which is information and not a check.

## 7. What you can truthfully say afterwards, and what you cannot

You cannot say that the budget capped your spend, that the audit proved the account was empty, that it showed no AgentCore session was open, or that either script was tested against AWS before you ran it. You cannot call a result clean when its `RESULT` line starts with `LIMITED CHECK`, or when it names a kit folder with no state file for a kit you did deploy, unless you also ran `--all-regions` and read every `PER REGION` line.

You can say: "I set a monthly cost budget with email alerts, and after each build I ran a read-only audit until it came back clean, and I read which account, Regions and prefixes it had covered." Only after you have done all of that.

## 8. What was and was not tested

Reviewed independently a second time on 2026-10-07 (round 2): 8 findings for this folder, 7 fixed, 1 left open (listed below). The reviewer ran the real scripts as processes against a stateful fake account: 143 teardown and audit sequences, of which 24 end in or go through this folder's audit (U00 to U11, 21 sequences, and three more that end with the audit: A25, B25, C25). Nothing ran against AWS in the review or here.

Left open after round 2 (1):
- **U01b, state lost and the Region only ever exported.** The default audit still exits 0 while the endpoint bills in the Region nothing names. That is a limit of any tool that reads local files, not a defect that code here can remove. What was done about it: the `RESULT` line carries the plain "no state file" statement for each kit folder without one, before the words "nothing that bills" (`test_r2_minor14_`, `test_r2_u01b_`), and `--all-regions` exists (`test_r2_allregions_`). In the test that copies the reviewer's sequence, `--all-regions` finds the endpoint and exits 2.

Fixed in round 2 (7). Each has tests in `tests/test_review_r2.py` that failed on the code as reviewed and pass now. Run against the code as reviewed, 94 of the 101 test cases first written failed; the other 7 guard behaviour that had to stay the same. Two more tests were added afterwards (one checks a count in this README, one a budget record of the wrong shape), which makes 103 new test cases:

| Finding | What changed | Tests (name prefix) |
| --- | --- | --- |
| U02d under BLOCKER 1: after kit C renamed a damaged state file to `.state.json.damaged-*`, the audit no longer read it, lost the Region it had salvaged, and exited 0 | Every file in a kit folder whose name starts with `.state.json` is read. An unreadable, empty, cut-short or set-aside file makes the result NOT CLEAN and is named in the `RESULT` line. More is salvaged by pattern (host names, bare Region values, either quote style) | `test_r2_u02d_` |
| MINOR 14: the lost-state limit was not visible in the `RESULT` line | Each kit folder with no state file, or with a state file that names no Region, is named in the `RESULT` line in plain words, before the verdict when the verdict is good | `test_r2_minor14_` |
| U03: `--only` in the wrong Region exits 0; the line could be misread | The `RESULT` line starts with `LIMITED CHECK: THE KIT FOLDERS WERE NOT READ (--only)` | `test_r2_u03_` |
| U04, U04b: `--ignore-storage-only` exits 0 with a managed knowledge base, buckets, a runtime and an open session left; the line could be misread | The `RESULT` line starts with `LIMITED CHECK: STORAGE-ONLY ITEMS WERE NOT COUNTED (--ignore-storage-only)`, the count, and the open-session warning, all in capitals | `test_r2_u04_` |
| MINOR 10: `--after-teardown` exits 0 with `[FOUND]` rows when only no-idle-charge items of that kit remain | Any `FOUND` row of that kit makes the exit code 2, and the line says the kit's own clean check would say NOT CLEAN | `test_r2_minor10_` |
| The budget that `budget_alarm.py` creates was covered by no row | The audit lists budgets under `INFORMATIONAL` and says which one this folder created. The row never affects the exit code. `budget_alarm.py --show` marks its own budget and points to the row | `test_r2_budget_` |
| Two accounts in one state history keep the audit at exit 2 for good, and that was not spelled out (U09, "what the fixes broke") | No code change: it is on purpose. Section 2 now says it is permanent and what to run instead | none: a statement in this README |

Limits that remain after round 2, worst first:
- The lost-state limit above (U01b).
- `--all-regions` can end at exit 2 in an account with nothing in it, when a service has no endpoint in an enabled Region. The audit does not guess; you read the `PER REGION` lines. It does not look in a Region that is disabled.
- `--only` and `--ignore-storage-only` still exit 0 with things left that bill (U03, U04, U04b). They were asked for. The line now starts with `LIMITED CHECK`.
- A damaged state file, and a state history that names two accounts, keep the audit at exit 2 until you act (section 2).
- `--after-teardown` still exits 0 when only things it cannot check are left (U08c: roles, log deliveries, a workload identity, all free). Its `RESULT` line now says how many resource types it cannot check.
- The audit still cannot see an open AgentCore runtime session, an IAM role, a log delivery, a workload identity or a gateway target.
- Exit codes still differ across the four folders (round 1, minor 9). The table in section 4 was rebuilt from the code in round 2.

Acceptance run after the round 2 fixes: the reviewer's harness (its fake account and the 24 sequences above, unchanged) was run again on 2026-10-07 against this folder as fixed and the three kit folders as they stood at 13:35 UTC. 52 audit runs. The audit exited 0 while something that bills remained in 5 of them, in 4 sequences: U01b twice (the open limit; both lines carry the no state file statement before the verdict), U03 once (`--only`), U04 once and U04b once (`--ignore-storage-only`); those three lines start with `LIMITED CHECK`. In the other 20 sequences, U02d among them, no audit run exited 0 while something that bills remained.

Changed in round 2 without the review asking for it (so that it is not a surprise):
- A run over more than one Region ends with `PER REGION` lines.
- A clean `--after-teardown` line says how many of the kit's resource types this audit cannot check, and that the screen does not replace the kit's own clean check.
- `config.env` is searched for a Region or prefix on lines the plain reading skips, such as a line you commented out. The example file is not.
- A Region inside an AWS host name in a state file is audited (kit A records its container image address).
- `--only` together with `--all-regions` is a usage error (exit 64).
- `--json` has new keys: `result_line`, `limited_check`, `damaged_state_files`, `all_regions`, `informational`, and in `audited` the state files read and the kit folders that have none.
- `budgets:ListTagsForResource` moved from the write statement to the read policy in section 6, and `account:ListRegions` was added to the read policy.
- Four older tests were changed because the wording or the call list changed on purpose: three now expect the new `RESULT` words, and one passes `--all-regions` to the dry run so that it still sees every operation. The two tests that compare this README with the code were updated for the new operations and permissions.

Not changed, and worth knowing: `budget_alarm.py --dry-run` still exits 0 in every mode, while the kits' teardown dry runs no longer do. A dry run of this script deletes or creates nothing, and its 0 was never a statement that something is clean.

### Round 1 record

Reviewed independently on 2026-10-07 (round 1): 15 findings (3 blockers, 3 majors, 9 minors), 14 fixed, 1 left open.

Left open:
- Minor 9, exit codes differ across the four folders. They still differ. The kits were not changed from here; the difference is now documented in one table in section 4.

Fixed, with the test that covers each, by test name prefix in `tests/`: blockers `test_b1_`, `test_b2_`, `test_b3_`; majors `test_m1_`, `test_m2_`, `test_m3_`; minors `test_minor1_`, `test_minor3_`, `test_minor4_`, `test_minor5_`, `test_minor7_`; minor 6 by `test_common_has_a_gitignore...`; minors 2 and 8 are corrections to this README (the reference URLs in section 9, the action name in section 6, a Region note on each dollar figure in section 5).

Still true after the round 1 fixes, and not fixable from this folder:
- The audit cannot see an open AgentCore runtime session, an IAM role, a log delivery, a workload identity or a gateway target. `--after-teardown` names them and says where to look.
- The audit cannot find a deploy that no file on this machine records.
- `--ignore-storage-only` can still produce exit 0 with a deployed AgentCore runtime in the account. The `RESULT` line then says, in capitals since round 2, that open sessions cannot be listed.

Changed on the same day without the round 1 review asking for it (so that it is not a surprise):
- `whats_running.py --dry-run` now exits 3, not 0, as the kits' `99_verify_clean.py` scripts do. A dry run checks nothing and should not pass a test for exit 0.
- `--region` and `--prefix` now add to what the kit folders say. Before, they replaced the defaults. `--only` gives the old behaviour.
- The audit prints account ids as their last four digits everywhere, including inside bucket names and AWS error text.
- The audit also looks up the `aws/spans` log group (CloudWatch Transaction Search, which kit C's README offers as an optional step).
- The audit lists training jobs without a status filter, and rates a status it does not know as `unknown`.
- `--after-teardown KIT`, `--kits-dir`, and the tests that read the kit folders beside this one.
- Budgets created from now on carry a second tag, `created-by=aws-kits-budget-alarm`, which `--delete` relies on when there is no state file.

**SAFE (ran here, offline, no network, no credentials, 2026-10-07):**
- `PYTHONDONTWRITEBYTECODE=1 python -m pytest -q` in this folder: 434 passed, 0 failed, on Python 3.13.16 and again on Python 3.14.6, each in a virtual environment built from `requirements.txt` (boto3 1.43.108, botocore 1.43.108, pytest 9.1.1), with kit A as fixed in round 5 and kits B and C as they stood at the end of round 4 beside this folder. Python 3.11 and 3.12 were not run. Before round 2 the count was 296, before round 4 it was 399, before round 5 it was 421; the 22 tests of round 4 are in `tests/test_review_r4.py`, the 13 of round 5 in `tests/test_review_r5.py`.
- 40 of 40 AWS operations that the two scripts can call exist in the boto3 1.43.108 service models (34 in `whats_running.py`, 6 in `budget_alarm.py`; 37 different operations, because `sts:GetCallerIdentity`, `budgets:DescribeBudgets` and `budgets:ListTagsForResource` are called by both). Round 2 added three to the audit: `account:ListRegions`, `budgets:DescribeBudgets` and `budgets:ListTagsForResource`. `tests/test_operations.py` prints this count and checks that this README states it.
- Request parameters and response shapes were validated by botocore's Stubber against those same service models for the calls the tests exercise that way. That includes the calls added after the round 1 review (`sts:GetCallerIdentity`, `s3:ListBuckets`, `GetBucketTagging`, `ListObjectVersions`, `bedrock-agentcore-control:GetAgentRuntime`, `budgets:ListTagsForResource`, and `DescribeLogGroups` with a name prefix) and the three added in round 2 (`account:ListRegions` with its token, `budgets:DescribeBudgets` with its token, and `budgets:ListTagsForResource` from the audit).
- One failure at a time was injected into each of the 31 calls that can decide the audit's verdict, 11 kinds each (access denied, throttling, no endpoint, timeout, no credentials, three kinds of exception, and a response that is `None`, a list or text): 341 cases. None leaves exit 0. 330 print `COULD NOT CHECK`. The other 11 are a failed `ListObjectVersions`, where the bucket is still listed, the line says its contents could not be read, and the exit code is 2. The same 11 kinds were injected into the three calls added in round 2. `account:ListRegions` under `--all-regions`: 11 cases, all exit 2 with `could not list Regions`. `budgets:DescribeBudgets`: 22 cases (an account with nothing in it, and one with an endpoint), and `budgets:ListTagsForResource`: 11 cases; in all 33 the exit code is what it would have been without the failure, and the row says so.
- A response that lacks its list key, or carries `None` there, is reported as `COULD NOT CHECK` for each of the 25 list calls that feed a check (50 cases), as is an empty `GetKnowledgeBase`, a `BatchGetCollection` without details and a `GetAgentRuntime` without its lifecycle settings. A `ListRegions` answer with no list, an empty list, only disabled Regions, or an entry that is not a Region name gives `could not list Regions` (6 cases). What is NOT covered: a response whose list is present but whose items have wrong or missing fields inside them. The audit reads most item fields with a default and would print `?` or `unknown` for them; it does not prove such a response is complete.
- The tests cover the scope rules: Regions and prefixes from `config.env` (plain lines, and lines the plain reading skips), from `config.example.env`, from `.state.json` and its history, from ARNs, bucket names and host names inside a state file, from the environment and from the command line; `--only`; `--all-regions`; a state file that is missing, empty, cut short, not JSON, a folder, or full of keys that were not expected; six other file names that start with `.state.json` (temporary, set aside as damaged, copies); a state file that names another account, including one with the same last four digits; an identity call that fails.
- The tests cover: exit codes 0, 2, 3 and 64 for the audit and 0, 1, 3 and 64 for the budget; pagination on `ListEndpoints`, `ListCollections`, `ListBuckets`, `ListRegions` and `DescribeBudgets`; refusal to create or delete a budget without the flag; refusal to delete a budget this script did not create; `--dry-run` making no client and no call; `--after-teardown` for kits a, b and c, including exit 2 for a `FOUND` row that costs nothing; the first words of the `RESULT` line with `--only`, with `--ignore-storage-only`, with both and with neither.
- On what reaches the screen: in the tests, the supplied address and the 12-digit account id never appear in the state file or in any printed line, including when a stubbed AWS error message contains them. That shows the filter works on text the tests fed it. It does not show what real AWS error text contains.
- Four tests (10 cases) read the real kit folders beside this one (and write nothing there): the create, put and start calls each kit makes today are the ones `--after-teardown` was built from, the names its patterns rely on are still in the kits' code, and the audit can read each kit's `config.example.env`. If a kit changes, these fail and the coverage table in `whats_running.py` has to be looked at again.
- The coverage table behind `--after-teardown` was compared by hand with every create, put and start call in the kits' code as it stood at 13:35 UTC: 3 such calls in kit A, 12 in kit B and 13 in kit C, the same sets as in round 1. No resource type was added or removed and no row changed. For each row the audit can check, the kit's own `99_verify_clean.py` was read to see whether it counts that kind of thing as a leftover: all do, except `aws/spans` in kit C, which that script prints as information.
- The tests block all socket use, so a test that touched the network would fail. With the real client factory, no credentials and no network, all 23 checks and the identity check report `COULD NOT CHECK`, exit 2, and the budget row says `COULD NOT READ`; the budget script exits 1 and writes no state.
- Both scripts were run from a shell with `--help` and with `--dry-run`, with no AWS credentials in the environment: `whats_running.py --dry-run` and `--all-regions --dry-run` exit 3, `budget_alarm.py --dry-run` exits 0 in its three modes.
- The reviewer's own harness (the fake account and the 24 sequences that involve the audit) was copied to a scratch folder and run again, unchanged, against the fixed audit and the kits as they stood. The result is in the acceptance paragraph above.
- The README's count of 27 read-only calls per Region is checked by a test that counts the calls an audit of one Region makes in an account with nothing in it.

**NOT RUN:**
- Every AWS call. No request was sent to AWS, no budget was created, no account was audited, no Region was listed. The scripts were not run with credentials.
- `--all-regions` against a real account. How long it takes, and how many checks end as `COULD NOT CHECK` because a service is not offered in a Region, are not known.
- No alert email was ever received, so nothing here shows that the alarm reaches an inbox.
- The IAM policies in section 6 were not attached to anything or simulated.
- The spend limit console steps were not followed.
- The `read -r` way of supplying the address (section 3) was not tried in zsh or fish; it is standard `read` behaviour in bash.

**UNVERIFIED (not confirmed in a current AWS doc or not confirmable without an account):**
- What a service answers in a Region where it is not offered. The audit treats every failure the same way (`COULD NOT CHECK`, exit 2), so this decides only how often `--all-regions` can reach exit 0, not whether it can be wrong.
- Whether `account:ListRegions` answers for an account created through the new sign-up experience (a "project"). The guide page read says it is about accounts from "Sign up for AWS (advanced)". If it does not answer, `--all-regions` says `could not list Regions`.
- Whether the live Budgets API leaves the `Budgets` list out of the answer when the account has none. `budget_alarm.py --show` and the audit's budget row both read a missing list as "none", and the audit's row says that it did.
- That a budget made by `budget_alarm.py` costs nothing in every account. The pricing sentence quoted is about monitoring and notifications; this script creates no budget actions.
- Whether the live Budgets API still accepts the deprecated `CostTypes` member. Fallback: `--aws-default-cost-types`.
- Whether AWS error text ever repeats a subscriber address.
- Whether any live service leaves an empty list out of a response. The audit now treats a missing list as `COULD NOT CHECK`, which is the safe direction but would be a false alarm for such a service. S3 was checked with botocore's own parser: an empty `Buckets` element parses to an empty list.
- Whether `ListBuckets` with `BucketRegion` behaves as documented on every endpoint, and whether `ListKnowledgeBases` returns Managed knowledge bases.
- That deleting a runtime ends its open sessions. The sessions page says only "The session itself remains valid until the AgentCore Runtime ARN is deleted."
- The console places named by `--after-teardown` come from AWS doc pages read today, not from a console. Which AgentCore console page lists workload identities was not found.
- That an OpenSearch Serverless collection with no collection group is always Classic. The audit assumes so because it is the expensive, safe reading.
- Whether a stopped SageMaker notebook instance's storage volume is billed (reported as `unknown`, treated as billing).
- Whether a Bedrock custom model deployment bills while idle (reported as `unknown`).
- That SageMaker models, endpoint configurations, knowledge bases on a listed store, data sources and guardrails carry no standing charge. This rests on the absence of a price line, not on a sentence that says so.
- Whether an endpoint in the `Failed` state bills. The audit says `yes` for every endpoint state, which is the safe reading.
- Whether a spend limit appears in `--show`, and whether an existing customer can in practice get the new sign-up experience.
- How live responses differ from the service model. For example `DescribeLogGroups` documents that with a name pattern "only arn, creationTime, and logGroupName are included in the response"; the script copes with that, but real responses were never seen.
- Dollar figures for ECR storage, CloudWatch Logs storage and S3 Standard storage. None is quoted because none was verified today.
- The OpenSearch Serverless hourly rate for any Region other than US East (N. Virginia), US East (Ohio) and US West (Oregon). The script uses $0.24 as a floor elsewhere and says so.

How the pages were read: the first version of this folder read AWS pages on 2026-10-07 through a page-fetch tool and then checked each quoted sentence character for character against saved copies of the same pages, the Markdown version of the doc page, or the documentation strings inside boto3 1.43.108. The reviewer found all 49 quotations then in this README verbatim on raw pages. Everything added after the round 1 review (the AgentCore pricing sentences, the lifecycle and session sentences, the warm pool sentence, the S3 and Budgets API facts, the IAM action names) was read as raw text with `curl`, from the pricing page's HTML or from the `.md` form of the doc page, and copied from there. The same holds for what round 2 added: the `ListRegions` API page, the guide page on enabling and disabling Regions (three sentences quoted from it in sections 2 and 6), and the two Service Authorization Reference pages for `account` and `budgets`. Prices change; re-read the page before relying on a figure.

## 9. Sources

All read 2026-10-07.

- AWS Budgets best practices: https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-best-practices.html
- Configuring budget actions: https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-controls.html
- AWS Budgets pricing: https://aws.amazon.com/aws-cost-management/aws-budgets/pricing/
- Budgets API, CreateBudget: https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_CreateBudget.html
- Budgets API, Budget and CostTypes: https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_Budget.html and https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_CostTypes.html
- Budgets API, DescribeBudgets, DescribeNotificationsForBudget, DeleteBudget, ListTagsForResource: https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_DescribeBudgets.html , https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_DescribeNotificationsForBudget.html , https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_DeleteBudget.html , https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_budgets_ListTagsForResource.html
- STS GetCallerIdentity: https://docs.aws.amazon.com/STS/latest/APIReference/API_GetCallerIdentity.html
- Account Management API, ListRegions (the call behind `--all-regions`): https://docs.aws.amazon.com/accounts/latest/APIReference/API_ListRegions.html
- Enable or disable AWS Regions in your account (default and opt-in Regions, the permission, what a disabled Region still costs): https://docs.aws.amazon.com/accounts/latest/reference/manage-acct-regions.html
- EC2 API, DescribeRegions (the other documented way to list enabled Regions; read, not used, because it needs an EC2 permission the audit otherwise has no use for): https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_DescribeRegions.html
- AWS Free Tier FAQs (spend limit, Paid plan Q2): https://aws.amazon.com/free/free-tier-faqs/
- Create a spend limit in AWS Settings: https://docs.aws.amazon.com/accounts/latest/reference/create-spend-limit.html
- Sign up for AWS (new): https://docs.aws.amazon.com/accounts/latest/reference/sign-in-new.html
- Compare sign-up options (the row "Create spend limits for your accounts"; found by the reviewer): https://docs.aws.amazon.com/accounts/latest/reference/sign-up-for-aws.html
- Activate advanced AWS features: https://docs.aws.amazon.com/accounts/latest/reference/activate-advanced-features.html
- AWS Regions for your projects: https://docs.aws.amazon.com/accounts/latest/reference/project-regions.html
- Supported AWS services for Sign up for AWS (new): https://docs.aws.amazon.com/accounts/latest/reference/supported-services-sign-up-new.html
- Amazon SageMaker AI pricing: https://aws.amazon.com/sagemaker/ai/pricing/
- SageMaker, delete endpoints and resources: https://docs.aws.amazon.com/sagemaker/latest/dg/realtime-endpoints-delete-resources.html
- SageMaker, scale an endpoint to zero instances: https://docs.aws.amazon.com/sagemaker/latest/dg/endpoint-auto-scaling-zero-instances.html
- SageMaker, managed warm pools (billing): https://docs.aws.amazon.com/sagemaker/latest/dg/train-warm-pools.html
- SageMaker API, ListTrainingJobs (how `StatusEquals` filters): https://docs.aws.amazon.com/sagemaker/latest/APIReference/API_ListTrainingJobs.html
- Amazon Bedrock pricing: https://aws.amazon.com/bedrock/pricing/
- Bedrock, delete a knowledge base: https://docs.aws.amazon.com/bedrock/latest/userguide/kb-delete.html
- Bedrock, sync a data source (console place for the sync history): https://docs.aws.amazon.com/bedrock/latest/userguide/kb-data-source-sync-ingest.html
- Amazon OpenSearch Service pricing: https://aws.amazon.com/opensearch-service/pricing/
- OpenSearch Serverless, collection group capacity limits: https://docs.aws.amazon.com/opensearch-service/latest/developerguide/collection-groups-capacity-limits.html
- OpenSearch Serverless, creating collections (NextGen and Classic): https://docs.aws.amazon.com/opensearch-service/latest/developerguide/serverless-create.html
- Amazon S3 pricing (S3 Standard storage row, S3 Vectors): https://aws.amazon.com/s3/pricing/
- S3 API, ListBuckets, GetBucketTagging, ListObjectVersions: https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListBuckets.html , https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetBucketTagging.html , https://docs.aws.amazon.com/AmazonS3/latest/API/API_ListObjectVersions.html
- Amazon Bedrock AgentCore pricing: https://aws.amazon.com/bedrock/agentcore/pricing/
- AgentCore, lifecycle settings (session time limits): https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html
- AgentCore, isolated sessions (session states): https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html
- AgentCore, configure observability (console places for log delivery): https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html
- AgentCore control API, GetAgentRuntime: https://docs.aws.amazon.com/bedrock-agentcore-control/latest/APIReference/API_GetAgentRuntime.html
- CloudWatch Logs API, DescribeLogGroups (name prefix and name pattern): https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_DescribeLogGroups.html
- IAM, roles in the console: https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_manage_delete.html
- Amazon ECR pricing: https://aws.amazon.com/ecr/pricing/
- Amazon CloudWatch pricing: https://aws.amazon.com/cloudwatch/pricing/
- API reference page for each list call: the URL is in the `READ_OPERATIONS` table at the top of `whats_running.py` and in the comment above each call.
- Service Authorization Reference (IAM action names). The addresses in the first version of this README now redirect to the index; these are the current pages, each checked on 2026-10-07: https://docs.aws.amazon.com/service-authorization/latest/reference/list_sagemaker.html , https://docs.aws.amazon.com/service-authorization/latest/reference/list_bedrock.html , https://docs.aws.amazon.com/service-authorization/latest/reference/list_bedrock-agentcore.html , https://docs.aws.amazon.com/service-authorization/latest/reference/list_opensearchserverless.html , https://docs.aws.amazon.com/service-authorization/latest/reference/list_s3vectors.html , https://docs.aws.amazon.com/service-authorization/latest/reference/list_s3.html , https://docs.aws.amazon.com/service-authorization/latest/reference/list_ecr.html , https://docs.aws.amazon.com/service-authorization/latest/reference/list_logs.html , https://docs.aws.amazon.com/service-authorization/latest/reference/list_budgets.html , https://docs.aws.amazon.com/service-authorization/latest/reference/list_sts.html , https://docs.aws.amazon.com/service-authorization/latest/reference/list_account.html
