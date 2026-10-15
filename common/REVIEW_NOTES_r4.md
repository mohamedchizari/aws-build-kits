# common: record of the round 4 review (2026-10-07)

Nothing here was run against AWS. Round 4 had two independent readers who did not write the code. One
followed the money: both scripts of this folder were run as real processes against a stateful fake account
(21 budget checks; 54 audit sequences among 377). The other ran the kits and the audit against a local
emulator. This file lists what they found in `common/` and what was done about each finding.

## What is still wrong or limited after round 4

1. **Nothing in this folder has run against AWS.** That has not changed.
2. **The audit cannot see a kit A state file that is an older copy** (MINOR 16, the reader's sequence W045).
   Stated as a limit in README section 2. It exits 0 while an endpoint bills in another Region, and it
   cannot print the no-state-file sentence, because a readable state file is there.
3. **The audit still exits 0 for a deploy that no file on this machine records** (W031, W033, W034, W035,
   W040, W042: no state file and a Region that was only exported). Open since round 2; the `RESULT` line
   names the kit folders without a state file.
4. **`--only` and `--ignore-storage-only` still exit 0 while something bills** (W050, W051, W052, W055), in
   capitals, as before.
5. **An open AgentCore session cannot be listed** (W068), as before.
6. **`budget_alarm.py` does not read the budget back after creating it.** It prints `Created` after
   CreateBudget answered 200 and names the account. Whether the three alerts are in place is shown by
   `--show`, which you run yourself.
7. **The budget record trusts four digits.** `--delete` trusts the record in `.state.json` when the last
   four digits of the account match. Two accounts of yours that end in the same four digits, each with a
   budget of the same name, would still be confused. The full account id is deliberately not stored.
8. **The exit code table in README section 4 was brought up to date for kit A and for `budget_alarm.py`
   only.** The kit B and kit C columns are as read on 2026-10-07 at 13:35 UTC. The line "A damaged state
   file gives ... 4 or 5 in kit C" was left as it was for the round's coordinator to settle against kit C.

## Findings and outcomes

Every finding was reproduced first with the reader's own command. Tests are in `tests/test_review_r4.py`;
each was run against a copy of the folder as reviewed and failed there, except the ones named `..._control`.

| Finding | Outcome | What changed (file, function) | Tests |
| --- | --- | --- | --- |
| MINOR 6: `budget_alarm.py` never said which account it acted in (checks P03, P07) | FIXED | `budget_alarm.py`: `do_create`, `do_show`, `do_delete` name the account by its last four digits; the record keeps those digits (`account_tail`) | `test_r4_minor6_...` |
| MINOR 7: "FAILED, budget not created" when the answer was lost and the budget existed (P09) | FIXED: `OUTCOME UNKNOWN`, how to check, no record written, exit 1 | `budget_alarm.py`: `outcome_unknown`, `AwsCallFailed`, `_call`, `do_create` | `test_r4_minor7_...` |
| MINOR 8: `--delete` trusted a name-only record across accounts (P14) | FIXED, with limit 7 above | `budget_alarm.py`: `do_delete`, `do_show`, `budget_record`; `whats_running.py`: `recorded_budget`, `check_budgets`, `budget_lines` (the audit's budget row goes by the account of the record too) | `test_r4_minor8_...` |
| MINOR 9: `--delete` crashed on a record of the wrong shape (P150) | FIXED: such a record counts as no record and is not rewritten | `budget_alarm.py`: `budget_record`, `do_delete` | `test_r4_minor9_...` |
| MINOR 16: the audit cannot see a stale kit A state file; this README did not say so (W045) | STATED AS A LIMIT: README section 2, "A kit A state file that is an older copy reads as healthy" | README only | `test_r4_readme_states_the_stale_kit_a_state_file_limit_...` |
| Emulator 2: the audit read the word "exported" in a comment of kit A's `config.env` as a name prefix and printed it in every `RESULT` line | FIXED: a prefix counts only where it is assigned | `whats_running.py`: `_CONFIG_PREFIX_RE` | `test_r4_emulator2_...` |
| Emulator 7 (second part): nine tests of `tests/test_against_sibling_kits.py` failed when a folder above the kits was called `tests` | FIXED | `tests/test_against_sibling_kits.py`: `kit_source` | `test_r4_emulator7_...` |

Also changed because a finding of kit A required it: the kit A cells of codes 1 and 2 in the exit code
table (README section 4), and the first trap under it. Kit A now exits 1, never 2, when it stops after it
has sent a create or delete call.

Not asked for and changed all the same: `.gitignore` here now covers `.state.json*`; the audit's JSON
output has one more key under `informational` (`record_is_for_account_ending`).

## What ran in round 4, offline

The counts are filled in from the last runs on the final code.

- **The new tests on the folder as reviewed.** `tests/test_review_r4.py` has 22 tests. Run against a copy of
  the folder as reviewed, 18 fail and 4 pass; the 4 are the ones named `..._control`. On the fixed folder
  all 22 pass.
- **The folder's suite**, in a virtual environment built from `requirements.txt` outside this folder, with
  kit A as fixed and kits B and C as reviewed beside it: 421 passed on Python 3.13.16 and 421 passed on
  Python 3.14.6. One test helper was changed (`kit_source` in `tests/test_against_sibling_kits.py`, which
  was the finding). No older test had to change.
- **Both scripts with `--help` and `--dry-run`**, no credentials, an empty home directory, `boto3.client`
  replaced by a function that aborts: `--help` 2 of 2 exit 0; `budget_alarm.py --dry-run` exits 0 in its
  three modes; `whats_running.py --dry-run` and `--all-regions --dry-run` exit 3; no client built.
- **The money reader's suite, run again unchanged** (a byte-for-byte copy of its harness, run from a scratch
  folder; the tree under test holds this folder and kit A as fixed and kits B and C as reviewed). Before and
  after, for this folder:

  | Count | As reviewed | Fixed |
  | --- | --- | --- |
  | Budget alarm checks not as expected | 5 of 21 (P03, P07, P09, P14, P150) | 0 of 21 |
  | Audit sequences that end exit 0 with something billing | 12 of 54 | 12 of 54 |
  | Audit runs or budget runs that print a full account id | 0 | 0 |
  | The two dry-run checks of the audit (D55, D56) | both exit 3 | both exit 3 |

  No sequence and no check that was right before is wrong now. The 12 audit sequences are limits 2 to 5 at
  the top of this file: W045; W031, W033, W034, W035, W040, W042; W050, W051, W052, W055; W068. Every one
  states its limit in its `RESULT` line.
- **The emulator reader's suite was not run again** (its harness copies the kits from its own folder and has
  no setting for another tree). Its two findings for this folder were reproduced with the commands in its
  report. Emulator 2: `cp config.example.env config.env` in kit A, then `python common/whats_running.py
  --dry-run`: as reviewed the scope block says `prefix exported: kit_a_gpu_endpoint/config.env`; fixed, it
  lists `kitdemo` only. Emulator 7: the four folders under a folder called `tests`: as reviewed 9 failed and
  1 passed in `tests/test_against_sibling_kits.py`; fixed, 10 passed.
