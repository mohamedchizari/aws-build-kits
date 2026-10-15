# Round 4, Wed 7 Oct 2026: what was done and what it found

Written for the review from the readers' and fixers' reports, the blind readers' label files and the review's own runs. Where a number comes from an agent's report and was not re-run in the review it says "(agent)".

## 1. An earlier headline was wrong, and why

Rounds 3 reported: "the smaller stand-in model gave a misleading answer to 13 of 30 questions, and to 12 of 30 after the system prompt was rewritten; the larger gave none; the choice of model mattered more than the prompt or the check."

That result came from a rehearsal in which the tool calls were chosen in advance by the agent that prepared it. The model was handed the results of searches it had not written, often a single search whose matches were mostly off topic, and had to answer from them. In the kit, the model writes its own searches and can search again.

Round 4 let the stand-in model choose its own tool calls, through the kit's real tools against the live Federal Register API. Same model (Claude Haiku), same 30 questions:

| Who chose the tool calls | System prompt | clean | minor | misleading | answers |
| --- | --- | --- | --- | --- | --- |
| the preparing agent | as before round 3 | 10 | 7 | 13 | 30 |
| the preparing agent | rewritten in round 3 | 11 | 7 | 12 | 30 |
| the model itself | as before round 3 | 21 | 8 | 1 | 30 |
| the model itself | rewritten in round 3 | 22 | 7 | 0 | 29 (1 conversation ended at the kit's step limit) |

On 30 NEW questions, with the model's own tool calls and the rewritten prompt, two readers each labelled every answer: Claude Haiku 23 or 24 clean, 7 or 6 minor, 0 misleading of 30; Claude Sonnet 25 clean, 4 minor, 0 misleading of 29 (1 conversation ended at the step limit). The two readers agreed on 58 of 59 answers.

Were the round 4 readers simply easier? A fresh reader relabelled 30 answers of the round 3 second pass with the same instructions: 27 of 30 the same label as before, and 5 misleading both times (4 the same answers). So the readers still call those answers misleading; what changed is the answers.

What this supports, and its limits:
- With pre-chosen tool calls the smaller model misled in 12 or 13 of 30 answers; with its own tool calls in 0 or 1 of 30, on the same questions. The rewritten prompt made little difference in either condition (13 against 12; 1 against 0).
- One reader per answer in the two "model itself" rows on the earlier questions; two readers on the new questions. The readers in round 3 and round 4 are different agents with the same instructions.
- Stand-in models (Claude Haiku, Claude Sonnet), not the kit's default (Amazon Nova Micro). Each stand-in ran inside its own agent harness, read the prompt as a text file and called the tools from a shell, took ten questions in one context, and knew it was a test. The kit's model has none of that.
- The model made 2.7 to 3.5 tool calls per question on average (82 for 30 questions; 99 and 105 for 30 new questions) where the pre-chosen rehearsal had 47 for the same 30 questions (one to three each).
- 2 of 90 conversations under the current prompt ended at the kit's step limit with no answer for the user (one Haiku, one Sonnet).

## 2. The check on answers it had never seen

The answer check (`kit_c_langgraph_agentcore/agent/graph.py`) had been corrected three times, each time on text it had just been shown. The 88 answers above that were written under the current prompt with the model's own tool calls (59 on new questions, 29 on the earlier ones) were not shown to anyone who changed code. Outcome on the code as it stood before the round 4 fixes, and again on the round 4 code (identical, answer by answer):

| Reader's label | passed | warned | replaced |
| --- | --- | --- | --- |
| clean (70) | 59 | 6 | 5 |
| minor (18) | 16 | 2 | 0 |
| misleading (0) | 0 | 0 | 0 |

The 8 warnings:
- 4 say a tool call failed, and one did: 3 are the question's own document number that does not exist, 1 is an agency name the model guessed wrongly and then corrected.
- 1 flags a date and a time the model took from the visible part of a field the tool had cut short. The system prompt tells the model not to do that; both readers still called the answer clean.
- 3 flag a number "that appears in no complete field of a tool result" which the model had worked out correctly from the results: 22 matches less 3 left out is 19; 27 less 16 is 11; two effective dates 34 days apart. The warning's own words allow for this ("may be invented, worked out by the model, or ..."), but on a correct figure it reads as an accusation. 3 of 88.
The 5 replaced answers all followed a search that returned nothing, after which the kit always shows fixed text. The withheld model texts were clean.

No answer in the 88 was misleading, so this set says nothing about what the check catches. The one misleading answer written with the model's own tool calls (the earlier prompt, question H15: two conclusions about small lenders that the returned abstracts do not state, with no digits in them) passes the round 4 check with no warning (agent's replay; one case). It says the check does not wrongly warn on the kinds of sentence it wrongly warned on in round 3 (0 of 88), and that its "number not found" warning fires on correct arithmetic about 1 time in 30.

A separate reader in round 4 wrote 68 honest answers from the stored tool results in styles the check had not met (spaced dashes between fields, label and value lines, tables). Before the round 4 fixes 12 of 68 were warned; after them 0 of 68 (own run). That set is now seen.

## 3. The four independent reads and what was fixed

| Read | Worst finding | Headline before the fixes | After (own run on the merged tree unless marked) |
| --- | --- | --- | --- |
| Money and state, all folders (377 sequences on a fake account) | Kit A: when the sign-in expired during a wait, the last line and exit code 2 said "could not run" after the endpoint had been created | wrong "clean" 37 of 377 (state file intact: 2 of 244); exit-code mismatches 4 of 386; unrecorded creates 13 of 24; account id on screen 9 of 20 checks | wrong "clean" 34 of 377 (state file intact: 1 of 244, the audit's documented blind spot for open AgentCore sessions); exit-code mismatches 0 of 386; unrecorded creates 3 of 24; account id on screen 0 of 20 checks and 0 of 1,060 script runs |
| The same, second finding | Kit A: a lost CreateEndpoint answer is retried by the SDK, answered "already exists", and the kit erased its own record of a running endpoint. Found independently by the emulator run as well | reproduced with real botocore against a local stand-in server | the record is kept and the script stops with "EXISTS ... IT IS BILLING BY THE HOUR" (agent, same probe) |
| Kit B numbers | The judge reader credited a CORRECT verdict whose own reason took it back, when the other value was written in an everyday spelling | flattering judge reads 30 of 203 with the question; exact-match false credit 3 of 300; usage line wrong in 6 of 22 interrupted runs | flattering 0 of 203 with the question, 2 of 203 without; false credit 1 of 300; lost credit 73 of 300; usage line 0 of 22 |
| Kit C, what a user sees | "Ten documents matched the search" when 20 did passes once it carries "among ...", the usual wording of real answers | planted unsupported content passing with no warning 50 of 212; honest texts warned 12 of 68; wrong "clean" 3 of 33 | 25 of 212 (the README no longer claims the classes it cannot read); 0 of 68; 0 of 33 |
| Emulator (moto plus hand-written fakes; 358 kit commands, 16,107 requests, no packet to AWS) | the lost-CreateEndpoint defect, plus six smaller ones | no parameter-validation error, no request outside the service model's enum, pattern or length rules, no wait loop that did not return, no clean check that said clean while the emulator still listed that kit's resource | its smaller findings fixed by the three fixers (agent); the emulator run itself was not repeated on the fixed tree [repeated later on the final tree: section 6] |

What the emulator run does not show: most Bedrock, AgentCore and SageMaker runtime calls were answered by fakes written from the SDK's service model, because the emulator does not implement them. A pass shows the kit builds a valid request and reads a model-shaped answer. It does not show what AWS answers.

Tests on the merged round 4 tree, run by the review on a cloud test machine in virtualenvs built from each folder's requirements.txt, on Python 3.13.16 and again on 3.14.6: common 421 passed; kit A 317 passed; kit B 1,727 passed; kit C 970 passed.

## 4. What is still not done

- Nothing has run against AWS. The kits' default models have never been called.
- Nobody independent has read the round 4 fix code. Each round so far has found defects in the round before. [Read in round 5: `../round5/FINDINGS_round5.md`.]
- The kit C check was corrected a fourth time on text it had just been shown (the reader's 212 planted and 68 honest texts). The 88 answers of section 2 were not shown to the fixer and give the same outcomes before and after, which is the only unseen evidence there is.
- The comment in kit C's `agent/graph.py` says one question is bounded at 15 requests; the rig's builder measured 18 (agent). Not changed. [Done later: section 6.]
- A defect in one reader's own harness, found by the review: run from its own folder, the kit C reader's suite loads two modules from the reader's frozen kit copy whatever tree it is pointed at. Its numbers above come from a copy of the suite that cannot do that.

## 5. Where things are

- `reader_*.md`, `emulator_run.md`: the four reports as handed back.
- `heldout_new_questions/`, `earlier_questions_own_calls/`, `earlier_questions_own_calls_earlier_prompt/`: for each, the questions, each writer's answers, the transcript of every tool call with the stored API response, the blind labels (`*_labels.jsonl`; `*_labels_b.jsonl` is the second reader), and the check's summary and per-answer results.
- `calibration/pass2_part1_relabel.jsonl`: the fresh reader's labels for 30 answers of the round 3 second pass.
- Each kit's `REVIEW_NOTES_r4.md`: its fixer's account, finding by finding.

## 6. Added later (7 Oct 2026, late evening)

After a Mac run of the offline tests, the review repeated the round 4 emulator run on the final tree, with the reader's own one command and the same guard (kit code in a network namespace with loopback only, dummy keys, the guard proved before any kit code ran): 351 kit commands in 32 scenarios, 15,903 requests, 0 Python tracebacks, 0 commands the harness had to stop, every clean check agreeing with what the emulator still held, and no request flagged against the service models' rules except the 8 that carry the emulator's own gateway id, as before. Against the reviewed tree's run (358 commands, 16,107 requests, 1 traceback), 347 steps are in both and 90 of them differ: 87 in wording only (a scope sentence on every clean result, the account masked in two more lines, a stray prefix "exported" gone from the audit's list), and 3 in outcome, each one a round 4 fix doing what it says: kit A's lost CreateEndpoint answer now stops with the endpoint EXISTS and keeps the record (the clean check after it says NOT CLEAN, a second deploy is refused), kit C's teardown with a damaged state file now ends TEARDOWN INCOMPLETE, exit 5, instead of exit 0, and kit B's blocked download prints one line instead of a traceback. Two kit C steps went from exit 1 to 0 because the emulator's own fault (an HTTP 500 from moto) was corrected after the first run, as the reader's report says. Evidence: `_review_reports/round4/emulator_rerun_on_final_tree/`.

The review also measured a figure the round 4 record had left open: kit C's comment said one question is bounded at 15 Federal Register requests (5 tool turns x 3); with a model that never finishes, the step limit of 12 lets six tool turns run, so the bound is 18 (a question that finishes has had at most four, 12 requests). Three tests were added first, then the comment was corrected; no behaviour changed.
