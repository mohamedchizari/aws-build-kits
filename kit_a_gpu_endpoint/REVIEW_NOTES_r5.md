# Kit A and common/: record of the round 5 review (read 2026-10-07, fixed 2026-10-08)

Nothing here was run against AWS. One independent reader read kit A and `../common/` against the frozen tree
and left a runnable attack suite of 41 cases, each with its expected outcome written (and hashed) before the
code under test was run. It found no BLOCKER and no MAJOR: 9 MINOR findings (F1 to F9) and one question (Q1).
This file lists what was done about each. The README holds the resulting rules; this file holds the record.

## Findings and outcomes

Every finding has a test that failed on the code as reviewed and passes now (`tests/test_review_r5.py` here,
`../common/tests/test_review_r5.py` for the budget script and the exit code table). Tests whose name ends in
`_control` pin behaviour that must not change and passed before as well. "Case" is the reader's case id;
"before / after" is that case in the reader's suite on the code as reviewed and on the fixed code.

| Finding | Outcome | What changed (file, function) | Tests | Case: before / after |
| --- | --- | --- | --- | --- |
| F1 a sign-in error raised by a create or delete call was taken as "nothing was sent", though botocore signs every retry again | FIXED: such an error is "no clear answer", the call is named, exit 1 | `kitlib.py`: `NOT_SENT_ERRORS` now holds only the errors botocore raises before the first try (no credentials at all, unknown profile, no Region, a request it refused to build); `../common/budget_alarm.py`: `_NOT_SENT_ERRORS`, `outcome_unknown` | `test_r5_f1_...` (kit 4 tests + 4 controls, common 1 test + 4 controls) | A05, A06, B04, I02: broken / hold |
| F2 `budget_alarm.py` did not use kit A's retry rule; a DeleteBudget timeout said "not deleted"; the delete failure line named no account | FIXED: a 4xx to a request sent again is OUTCOME UNKNOWN (CreateBudget and DeleteBudget); DuplicateRecordException after a retry also says the budget exists; "not found" to a delete retry no longer says "Nothing was deleted now"; every delete failure line names the account when it is known | `../common/budget_alarm.py`: `outcome_unknown`, `do_create`, `do_delete`; `../common/README.md` section 5 | `test_r5_f2_...` (common 7 tests + 1 control) | I01, S04: broken / hold |
| F3 the documents said every stop after a create is exit 1 with the calls named; Ctrl-C gave 130 and "If an endpoint exists" | FIXED: Ctrl-C stays exit 130 (the same code as kits B and C, and the reader's control A09 expects it) and its last line now names the calls already sent, like every other stop; a create or delete interrupted mid-call is named "(no clear answer)"; the documents say 130 | `kitlib.py`: `Aws.call`, `stop_reminder`, `guarded` (and its docstring); docstrings of `10_deploy.py`, `70_change_one_setting.py`; README section 4 step 2 and limit 11; `../common/README.md` exit code table rows 1 and 130 | `test_r5_f3_...` (kit 4), `test_r5_f3_exit_table_...` (common 1) | A08: broken / still broken in the reader's suite, see below |
| F4 teardown's listing-failure path said the hourly charge "has stopped" when the endpoint was absent and nothing was deleted | FIXED: "was not found in <place> (already absent): this run deleted nothing there", and it no longer names a state file that does not exist | `90_teardown.py`: `run` | `test_r5_f4_...` (1 test + 1 control) | B03: broken / holds |
| F5 the endpoints a setting change replaced were billed as "0.00 h, about $0.00" with the clock behind, and lost the "already exists" caveat | FIXED: "for an UNKNOWN time ... use your bill"; the caveat is carried | `70_change_one_setting.py`: `run` (`replaced`: `unknown`, `already_exists`); `kitlib.py`: `billing_lines` | `test_r5_f5_...` (2) | G01: broken / holds |
| F6 a request whose `send()` raised disappeared from the level uncounted | FIXED: it is counted as a failed request whose error names the exception | `60_loadtest.py`: `run_level` | `test_r5_f6_...` (1) | E02: broken / holds |
| F7 README and a test fixture blamed `nohup` for an ignored interrupt signal | FIXED (document): it is the background start with `&` from a shell that is not interactive; `nohup` alone ignores only the hang-up signal | README section 4 step 5; docstring of the `ctrl_c_arrives` fixture in `tests/test_review_r4.py` | `test_r5_f7_readme_...` (1) + `test_r5_f7_..._control` (measures both starts) | H01: broken / still broken, see below |
| F8 START_HERE and README last-line and BILLING-block claims the code did not match | FIXED, code where cheap: a failed or timed-out setting change now ends with the BILLING block; TEARDOWN INCOMPLETE is the last line, with what to do on it; a stop before any change now ends `STOPPED BEFORE ANY CHANGE: this run created and deleted nothing in AWS ...` (the words of the old last line follow the headline); START_HERE says the block sits between two rules and holds the "To stop the charge" line, and the README lists `STOPPED BEFORE ANY CHANGE` | `70_change_one_setting.py`: `run`; `90_teardown.py`: `run`; `kitlib.py`: `stop_reminder`; START_HERE line 56; README section 5 | `test_r5_f8_...` (4) | H03, H04a, H04b: broken / hold |
| F9 the output filter rewrote a valid KIT_PREFIX with 12 digits in a row | FIXED: digits that stand inside the KIT_PREFIX in use are printed as they are, unless the prefix is digits only or the digits are the account read from GetCallerIdentity | `kitlib.py`: `show_prefix`, `redact`, `load_config`, `config_for_place`, `caller_account` | `test_r5_f9_...` (2) | S01: broken / holds |
| Q1 README said "12 fixed, 0 stated as a limit" for round 4 while limit 14 reads like a limit | ANSWERED from `REVIEW_NOTES_r4.md`: all 12 were recorded as fixed; MINOR 3 was "FIXED (words only; limit 2 above stays)" and MAJOR 2 "FIXED, with limit 7 above". The README line now says so (items 13 and 14) | README section 8, round 4 line | `test_r5_q1_...` (1) | not a case |

One older test was changed because it pinned F1: `tests/test_review_r4.py::test_r4_b1_a_refused_first_call_leaves_no_mark_and_a_lost_answer_does`
asserted that a sign-in error on `delete_model` leaves no mark ("a sign-in error is raised before the request
leaves this machine"); it now expects `DeleteModel (no clear answer)`. The `ctrl_c_arrives` fixture's docstring
in the same file was corrected (F7); its code is unchanged. No test was deleted or weakened.

## The two cases that still break in the reader's suite, and why

- **A08** asserts exit code 1 after Ctrl-C during the InService wait. The finding allowed either fix, and the
  one taken keeps 130: it is what Ctrl-C means in kits B and C and in `../common/README.md`, and the reader's
  own control A09 (Ctrl-C inside CreateEndpoint) asserts 130. The rest of A08 now holds: the state keeps the
  endpoint and the last line names CreateModel, CreateEndpointConfig and CreateEndpoint. Making A08 pass
  would break A09.
- **H01** asserts that `nohup` in the foreground starts Python with SIGINT ignored, which is what the old
  README sentence claimed. That is false (it prints `False`), so the case cannot pass; the fix was to the
  sentence. `test_r5_f7_..._control` measures the corrected claim: `nohup` in the foreground `False`, `&` in
  `sh -c` `True`.

## What ran in round 5, offline

All commands ran with `env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN -u AWS_CA_BUNDLE`
(the process runs with `env -i`), with sockets refused by the conftest fixtures. No AWS call was made.

- **The reader's suite**, unchanged except for the folder it copies into (`run_attack.sh` pointed at this
  tree; both expectation files still match their sha256), Python 3.13.16 and 3.14.6, identical results:

  | Count | As reviewed | Fixed |
  | --- | --- | --- |
  | expected outcome broken | 15 of 41 | 2 of 41 (A08, H01) |
  | EXIT / LAST / STATE wrong | 3 of 14 / 3 of 12 / 0 of 9 | 1 of 14 / 1 of 12 / 0 of 9 (all A08) |
  | FALSE / DOC / DATA wrong | 6 of 13 / 5 of 8 / 1 of 3 | 0 of 13 / 2 of 8 / 0 of 3 |
  | controls broken | 0 of 26 | 0 of 26 |

- **The new tests on the code as reviewed** (a scratch copy of the frozen kit A and `common/` with only the
  new test files added): kit A 26 tests, 20 fail and 6 pass, the 6 being the `_control` tests; common 13
  tests, 8 fail and 5 pass, the 5 being the `_control` tests. On the fixed code all 39 pass.
- **Kit A suite**: 349 passed on Python 3.13.16 and on 3.14.6 (virtual environments built from
  `requirements.txt`); 348 passed and 1 skipped on the system Python 3.13.16 (no OpenAI SDK there). Before
  round 5: 323.
- **common suite** (kits B and C beside it, as frozen): 434 passed on Python 3.13.16 and on 3.14.6. Before
  round 5: 421.
- **Every script with `--help` and `--dry-run`**, empty home directory, no credential variables, sockets and
  `boto3.client` replaced by a function that aborts: `--help` 8 of 8 exit 0; `--dry-run` 6 of 8 exit 0 and
  teardown and the clean check exit 3; 56 calls printed, 0 aborts, no state file written. `10_deploy.py`
  without the flag: exit 2 after the price; `70_change_one_setting.py` with the flag and no state file:
  exit 2; `90_teardown.py` without `--dry-run`: stopped by the aborting stand-in (exit 99), as it should be.
- Not run: anything on the Mac, anything against AWS.

## Decisions

- **Which sign-in errors still mean "nothing was sent".** Only the ones botocore 1.43.108 can raise before the
  first try leaves: `NoCredentialsError` (raised when the client's credentials are None, and they are fixed
  when the client is built), `ProfileNotFound` and `NoRegionError` (raised while the client is built), and
  `ParamValidationError`. `TokenRetrievalError`, `SSOTokenLoadError`, `UnauthorizedSSOTokenError` and
  `PartialCredentialsError` can come from a refresh while a retry is signed again (`endpoint.py`: "Create a
  new request when retried (including a new signature)"; `credentials.py`, `_protected_refresh`: in the
  mandatory refresh period "all errors that occur when we attempt to refresh credentials are propagated back
  to the user"), so they count as no clear answer. Cost: an expired sign-in at the moment of the first create
  call now ends with exit 1 and that call named, where it was 2. Every script asks GetCallerIdentity first,
  so a sign-in that is already expired still stops there with exit 2.
- **Ctrl-C keeps exit code 130**, and its last line is the same line as any other stop (`BEFORE IT STOPPED,
  THIS RUN HAD SENT TO AWS: ... Exit code 130.`, or `STOPPED BEFORE ANY CHANGE: ...`).

## Observations, not changed

- With the clock set back, teardown's `All N finished runs` total adds 0.00 h for the run whose time is
  unknown and does not say so (each per-run line does say UNKNOWN). Same kind of display as F5; not a
  finding of this round, so not changed. Seen with `kitlib.run_report_lines` on a two-run history.
- `../common/whats_running.py` and `../common/budget_alarm.py` have their own output filters, which still cut
  12 digits inside a prefix (F9 was about kit A's filter).
- The reader's other observations stand as written in its report: the audit's prefix patterns need a letter
  first (verdict unaffected), `save_state` does not fsync, and what DeleteEndpoint answers for an endpoint
  that is Creating or Deleting is UNVERIFIED.
