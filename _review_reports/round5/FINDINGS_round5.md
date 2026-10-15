# Round 5, Thu 8 Oct 2026: three independent reads of the round 4 fixes, and their fixes

Written for the review from the readers' and fixers' reports (kept privately, not in this repository; see `../README.md`) and the review's own runs.

## 1. What was read, and by whom
Three fresh readers, one per kit (kit A read together with `common/`), each given only the round 4 changes as a patch, the frozen final tree and a brief; none saw an earlier finding, a fixer's notes or another reader's folder. Each left an attack suite whose expected outcomes were hashed before the code ran on them.

| Reader | Worst finding | Findings | Headline before the fixes |
| --- | --- | --- | --- |
| Kit A and `common/` | none above MINOR; nothing left an endpoint unrecorded or gave a false clean | 9 MINOR, 1 question | 15 of 41 cases broken; 0 of 26 controls |
| Kit B | MAJOR: a DECLINED judge verdict counted as a correct refusal when its own reason said the candidate gave an answer (16 of 16) | 1 MAJOR, 6 MINOR | 36 wrong in 36 cases; 0 of 46 controls |
| Kit C | MAJOR: teardown and the clean check said clean while a recorded runtime existed, when AWS refused the lookup by id; MAJOR: round 4 opened three ways for unsupported text to pass the answer check; MAJOR: the usage step told you to wait for a result that could never come | 3 MAJOR, 15 MINOR | 25 of 27 probes showed a defect; wrong clean 3 of 8; unsupported text passed 5 of 5; 0 of 17 controls |

## 2. After the fixes (the review's own runs on the merged tree)
| Kit | Reader's headline after | Controls |
| --- | --- | --- |
| A and `common/` | 2 of 41 still "broken": A08 expects exit 1 after Ctrl-C, where the fix keeps 130 (as in kits B and C) and makes the last line name the calls sent; H01 asserts the false `nohup` claim the fix corrected | 0 of 26 broken |
| B | 0 wrong in 36 | 0 of 46 broken |
| C | 5 of 27 probes still differ, all documentation probes whose expected label was the old sentence; the sentences were corrected to match the code. Wrong clean 0 of 8; unsupported text passed 0 of 5 | 0 of 17 broken |

The 88 unseen answers of round 4 (plus the 2 conversations that ended at the step limit) were replayed through the fixed answer check: 90 of 90 identical to before round 5 in outcome, warnings, notes, reasons and the full text shown. No fixer opened them.

The local-emulator run was repeated on the round 5 tree: 350 kit commands, 15,901 requests, 0 tracebacks, every clean check agreeing with what the emulator held, no request flagged except the 8 carrying the emulator's own gateway id. Against the run on the tree before round 5, 350 steps are in both and 1 differs, only in a process id inside an error message; one step is only in the earlier run (a harness retry from saved responses).

Offline tests on the merged tree, Python 3.13.16 and 3.14.6, each in a virtualenv built from the folder's requirements.txt: common 434 passed; kit A 349; kit B 1,981; kit C 1,031.

## 3. What the fixes changed that you will notice
- Kit A: an expired sign-in at the moment of the first create call now exits 1 with that call named (it was 2). A stop before any change now ends `STOPPED BEFORE ANY CHANGE:`. Ctrl-C still exits 130 and the last line now names the calls that were sent.
- Kit B: the judge reader refuses a DECLINED verdict whose reason says the candidate gave something, and reads more ordinary refusals. The scoring version is `2026-10-08.r5`, so a run started under round 4 rules cannot be resumed. The judge-reader counts in its README (203, 82 and 60 replies) were measured before round 5 and were not measured again.
- Kit C: if AWS answers a lookup of a recorded runtime or gateway with any error other than "not found", teardown keeps the record and exits 1 and the clean check says NOT VERIFIED. Which error AgentCore gives for a deleted runtime is still UNVERIFIED (README section 8, item 15), so this can stop a teardown that in fact worked. The usage step now says when CROSS-CHECKED can never come and that teardown can go ahead.

## 4. What is still not done
- Nothing has run against AWS.
- Nobody independent has read the round 5 fix code. Each round so far has found defects in the round before.
- Kit B's judge reader was measured only on hand-written replies; no Amazon Nova judge reply has been read.
- Limits each fixer stated rather than fixed are in that kit's `REVIEW_NOTES_r5.md`.
