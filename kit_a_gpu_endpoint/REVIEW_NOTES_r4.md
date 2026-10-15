# Kit A: record of the round 4 review (2026-10-07)

Nothing here was run against AWS. Round 4 had two independent readers who did not write the code. One
followed the money: every script of the kit was run as a real process against a stateful fake account
(377 sequences and 149 further checks across the kits). The other ran the kits against a local emulator.
This file lists what they found in kit A and what was done about each finding. The README holds the
resulting rules; this file holds the record.

## What is still wrong or limited after round 4

1. **Nothing in this kit has run against AWS.** That has not changed.
2. **A stale or hand-edited state file still fools teardown and the clean check.** The money reader's
   sequences A102, A103, A106, A110 to A113 and A115 still end with exit code 0 while an endpoint bills in
   another Region. The file is readable and names no live deploy there, so the scripts have nothing to go
   by (README section 8, limits 2, 3 and 14). Round 4 changed only the words of teardown's last line.
3. **With no state file the same holds** (A062 to A065, A070). The closing lines say `NO USABLE STATE FILE
   WAS FOUND`.
4. **Exit code 1 now has one more meaning** (README section 8, limit 11). Read the last line.
5. **The text of "already exists" is not from an AWS page** (README section 8, UNVERIFIED item 20). The
   deploy step does not depend on it alone: it asks ListEndpoints before it takes an endpoint out of the
   state file.
6. **An endpoint kept after "already exists" may be older than its record**, so its hours may be too low.
   Every line that prints them says so.
7. **Ctrl-C in the load test waits at most 60 seconds** for requests already on their way. One that has
   not come back by then is in no file, and the last line says how many.

## Two decisions

**The exit code after a script has acted.** Code 2 keeps one meaning: the script stopped before it created
or deleted anything in this run. Once `kitlib.Aws.call` has sent a create or delete call that AWS carried
out, or may have carried out, every stop is exit code 1, whatever stopped it: an expired sign-in, a
`KitError`, an AWS error, a crash. The last line then starts `BEFORE IT STOPPED, THIS RUN HAD SENT TO AWS:`
and names the calls. A call counts as sent unless AWS refused it on the first and only try (a 4xx answer
with `RetryAttempts` 0) or the error was raised before anything left the machine (a sign-in error, a
request botocore refused to build). No new code was introduced: 1 already meant "AWS returned an error, or
something remains", and kits B and C use 1 in the same place. `../common/README.md` section 4 has the rule
in the one table.

**"Already exists" on a create this script just sent.** Stricter than "may exist". For the endpoint, which
bills: the record is taken out of `.state.json` only when AWS refused the one request that was sent, in
words other than "already exists", AND ListEndpoints does not list the endpoint. In every other case the
endpoint and the deploy record stay:

| What came back from CreateEndpoint | What the kit does |
| --- | --- |
| 4xx on the first try, not "already exists", endpoint not listed | record removed, AWS's error shown, exit 1 (as before) |
| "already exists" (any try), or a 4xx with the endpoint listed | record kept, marked `create_answer: already exists`; stop: "an endpoint named ... EXISTS ... IT IS BILLING BY THE HOUR"; exit 1 |
| a 4xx that came back after the SDK had sent the request again | record kept, marked unconfirmed; stop: "MAY exist and MAY be billing"; exit 1 |
| a 4xx on the first try and ListEndpoints fails as well | record kept, marked unconfirmed; exit 1 |
| no answer, or a 5xx | record kept, marked unconfirmed (as before); exit 1 (was 2) |

The script does not adopt the endpoint and go on waiting. It cannot tell an endpoint its own lost request
made from one that was there before, and the second kind would carry this run's settings and start time by
mistake. It says: tear down, then deploy again. For the model and the endpoint configuration, which cost
nothing, the rule is the first and third rows without the listing.

## Findings and outcomes

Money reader: BLOCKER 1, MAJOR 1 to 3, MINOR 3, 4, 10 to 14. Emulator reader: Emulator 1 (the same defect
as MAJOR 1) and Emulator 5. Every finding was reproduced first with the reader's own command. Tests are in
`tests/test_review_r4.py`; each was run against a copy of the kit as reviewed and failed there, except the
ones named `..._control`.

| Finding | Outcome | What changed (file, function) | Tests |
| --- | --- | --- | --- |
| BLOCKER 1: the sign-in expires while deploy or teardown waits; last line "no usable AWS credentials", exit 2, after the endpoint was created or the delete was sent | FIXED | `kitlib.py`: `Aws.call` records create and delete calls, `guarded` and `stop_reminder` exit 1 and name them | `test_r4_b1_...` |
| MAJOR 1 and Emulator 1: a lost CreateEndpoint answer is retried by the SDK, answered "already exists", and the kit erased its record of a running endpoint | FIXED | `kitlib.py`: `create_stack`, `definitely_rejected`, `retry_attempts`, `says_already_exists`; `billing_lines` and `run_line` say the limit; README section 4 step 2 names the message | `test_r4_m1_...`; one older test in `test_kitlib.py` changed (it pinned the removal) |
| MAJOR 2: Ctrl-C in the load test did not stop the load and lost every measurement | FIXED, with limit 7 above | `60_loadtest.py`: `run_level`, `LevelInterrupted`, `run` | `test_r4_m2_...` |
| MAJOR 3 (kit A part): full account id and caller ARN printed from AWS error text; README advice to move a damaged state file to the folder above; `.gitignore` covered only two file names | FIXED | `kitlib.py`: `redact`, `_RedactingStream`, `error_message`, `guarded`; `60_loadtest.py` (the error column of the CSV); `.gitignore` (`.state.json*`); README section 5 | `test_r4_m3_...` |
| MINOR 3: teardown called the shell's Region "the place .state.json records" when the file recorded another | FIXED (words only; limit 2 above stays) | `90_teardown.py`: `run` | `test_r4_n3_...` |
| MINOR 4: the clean check said CLEAN for a live record with no Region | FIXED: INCOMPLETE, exit 1 | `99_verify_clean.py`: `run` | `test_r4_n4_...` |
| MINOR 10: a denied or throttled List call stopped teardown before the delete that stops the bill | FIXED: the endpoint is deleted first, then the error is reported, exit 1 | `90_teardown.py`: `run` | `test_r4_n10_...` |
| MINOR 11: a failed warm-up ended the load test with no BILLING lines | FIXED | `60_loadtest.py`: `run` | `test_r4_n11_...` |
| MINOR 12: after a setting change the BILLING line counted only the new endpoint | FIXED: a second line gives the hours and dollars of the endpoints it replaced | `70_change_one_setting.py`: `run`; `kitlib.py`: `create_stack` (`replaced`), `billing_lines` | `test_r4_n12_...` |
| MINOR 13: with the clock set back the BILLING line said 0.00 h and $0.00 | FIXED: "HOURS AND DOLLARS SO FAR ARE UNKNOWN" | `kitlib.py`: `billing_lines`, `close_run`, `run_line` | `test_r4_n13_...` |
| MINOR 14: `70_change_one_setting.py` exited 2 after DeleteEndpoint was sent | FIXED: exit 1 (the rule above) | `kitlib.py`: `guarded`; `70_change_one_setting.py` (message) | `test_r4_n14_...` |
| Emulator 5: every AWS error ended "Run: python 99_verify_clean.py", also when that script was the one that failed and in `00_check.py`; teardown said the state file "does not exist" when it existed | FIXED | `kitlib.py`: `stop_reminder`; `90_teardown.py`: `run` | `test_r4_e5_...` |

Not asked for and changed all the same: `10_deploy.py` exits 1, not 2, when CreateEndpoint (or CreateModel,
CreateEndpointConfig) gets no clear answer, because that too is a stop after acting. The money reader had
listed this case as sound (sequences A180, A181); the exit code there contradicted the same table.

## What ran in round 4, offline

The counts are filled in from the last runs on the final code.

- **The new tests on the kit as reviewed.** `tests/test_review_r4.py` has 40 tests. Run against a copy of the
  kit as reviewed, 33 fail and 7 pass; the 7 are the ones named `..._control`. On the fixed kit all 40 pass.
- **The kit's suite.** System Python 3.13.16: 316 passed, 1 skipped (the test that needs the OpenAI SDK). In a
  virtual environment built from `requirements.txt` outside this folder: 317 passed on Python 3.13.16 and
  317 passed on Python 3.14.6. Two older tests were changed: `test_kitlib.py` (a refused CreateEndpoint now
  asks ListEndpoints before the record is taken out, so the test queues that answer) and `test_kit_rules.py`
  (one more `# UNVERIFIED:` marker in `kitlib.py`).
- **Every script with `--help` and `--dry-run`**, no credentials, an empty home directory, `boto3.client`
  replaced by a function that aborts: `--help` 8 of 8 exit 0; `--dry-run` 6 of 8 exit 0 and the two that must
  not (teardown, clean check) exit 3; 56 calls printed, 0 made, no client built.
- **The money reader's suite, run again unchanged** (a byte-for-byte copy of its harness, run from a scratch
  folder so that its output lands there; the tree under test holds this kit and `common/` as fixed and kits
  B and C as reviewed). 377 sequences and 149 checks, before and after:

  | Count | As reviewed | Fixed |
  | --- | --- | --- |
  | Wrong "clean", all folders | 37 of 377 | 36 of 377 |
  | ... of them kit A sequences | 16 of 143 | 15 of 143 (A108 is now INCOMPLETE, exit 1) |
  | Exit-code mismatches against the one table | 4 of 386 (L09, L10, M02, M06) | 1 of 386 (M06, which is kit C) |
  | Load test checks not as expected | 5 of 12 | 0 of 12 |
  | Hours and dollars checks not as expected | 2 of 11 | 0 of 11 |
  | Full account id on screen, kit A checks (K01 to K08) | 5 of 8 | 0 of 8 |
  | Kit A script runs inside the sequences that print a full account id | 8 | 0 |
  | "Last line says something that is not so", kit A checks (M01, M02, M05) | 2 of 3 | 0 of 3 |
  | Dry-run side effects; calls without the billing flag | 0 of 37; 0 of 12 | 0 of 37; 0 of 12 |

  No sequence and no check that was right before is wrong now. The 15 kit A sequences that still end
  "clean" with something billing are limits 2 and 3 at the top of this file (13 sequences) and the two that
  keep the logs on request (A030, A031). Every one of them states its limit in its closing lines.
  In 12 sequences the exit code of one step changed from 2 to 1 on purpose (a deploy whose
  CreateEndpoint got no clear answer; a teardown whose sign-in expired after DeleteEndpoint).
- **The reader's retry probe** (the real SDK with the kit's own client settings against a stand-in server
  on this machine; the first CreateEndpoint answer is held back, the second try is answered "already
  exists"). As reviewed: `state file 'deploy': None`, no endpoint in the record. Fixed: the endpoint and the
  deploy record are kept, `create_answer` is `already exists`, and the stop message says the SDK had sent
  the request 2 times.
- **The emulator reader's suite was not run again.** Its harness copies the kits from its own folder and
  has no setting for another tree. Its two findings for this kit were reproduced in other ways: Emulator 1
  with the retry probe above, Emulator 5 in the outputs of the money suite on the kit as reviewed (the clean
  check told to run the clean check; "which does not exist" for a state file that exists).
