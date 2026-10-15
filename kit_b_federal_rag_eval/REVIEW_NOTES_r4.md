# Kit B, round 4 (fourth independent review, 2026-10-07): what was found, what was done, what is left

Nothing here was run against AWS. Three of the round's reports concern this kit: a reader who attacked the numbers (2 major and 9 minor findings), a reader who attacked billing and teardown (3 findings for kit B), and a run of the kit against an emulated AWS (2 findings for kit B). Every count below was made offline, most of them by the first reader's own suite: 203 + 82 + 60 + 60 + 28 hand-labelled or mechanical judge replies, 300 hand-labelled answers, the 120 answers and 120 judge replies two stand-in models wrote in the rehearsal, 22 scripted runs of `50_run_eval.py`, and 60,000 random answers. The reader's labels were written before this fix existed and were not touched; the suite checks their digests itself.

"Flattering" means read as CORRECT or DECLINED where a person reads no such verdict. "Lost" means counted as unparseable, or as not correct, although a person can read it. "With the question" is how every run reads a judge reply. "Without the question" is `scoring.read_judge` called by hand with the reply alone.

## 1. What is still wrong, worst first

1. **The judge reader is still lists of words.** Since round 4 it is an allow-list for the reason of a CORRECT or DECLINED verdict when the question is known. That closes the two holes the reader found, and it cannot close this one: a reason made only of words on the lists is read as its verdict whatever it means. Known cases, kept as tests so that the list cannot go stale (`tests/judge_replies_r4.py`, `STILL_READ_FLATTERINGLY`):
   - with the question: "The candidate gives a stage, and the reference gives a stage too." (CORRECT), "The candidate declines. The agency is in the answer." and "The candidate has the answer. It declines to say so." (DECLINED);
   - without the question: one stated value and nothing to compare it with ("Candidate states Pilot.", "The candidate names the Bureau of Mines."), a comparison without a verb ("Candidate says the Dept. of Energy, reference EPA.", "Navy was given. The right one is EPA."), a value under DECLINED that is in no label set in that spelling ("the agency is given as the navy"), a part of the refusal sentence quoted under CORRECT, and a mismatch phrase on no list ("is a world away from", "garbles", "is a poor match for", "is news to").
   On the reader's 203 replies, without the question, 2 are still flattering: "Candidate says the Dept. of Energy, reference EPA." and a reply cut off after "...is Pilot, which".
2. **The price of the allow-list is lost verdicts.** A clear verdict whose reason holds a word on no list is unparseable. It is never counted as correct, and it makes the judged rate undercount. On the reader's 123 clear verdicts: 27 lost with the question (32 before), 45 without (49 before). `summary.md` counts the unparseable replies and `judge_note` says which word decided. If that count is high, read the replies in `raw.jsonl`, which holds each reply whole since round 4.
3. **Exact match still credits 1 of the reader's 111 answers a person would reject:** "It was reported, is the answer the Environmental Protection Agency". Every word is on the list for an agency question and no sentence starts with a verb. It also credits "Deployed is a stage of development.", a true sentence that is not an answer; the reader could not label it either way.
4. **The usage and cost line cannot know three things.** A call that failed or was cut off before its answer arrived; the second sending of a call the SDK retried (counted once); and a call that was answered in the instant before the process was killed, before the note of it was written. The first two are said in the usage line of every run. The third is said here and in README section 2, item 5.
5. **Everything was measured on text written by hand, by rule, or by two stand-in models.** No Amazon Nova answer and no Amazon Nova judge reply has been read by either scorer.

## 2. The reader's headline counts, before and after

The reader's one command (`run_all.sh`, about three minutes), run on the kit as it was reviewed and on the kit as it is now.

| Count | Before | After |
|---|---|---|
| Judge reader, 203 hand-labelled replies, flattering, with the question | 30 | 0 |
| The same, without the question | 37 | 2 |
| Judge reader, 203 replies, lost of the 123 clear verdicts, with the question | 32 | 27 |
| The same, without the question | 49 | 45 |
| Another value in an everyday spelling (82 replies), flattering, with / without the question | 58 / 82 | 0 / 0 |
| One mismatch phrase (60 replies), flattering, with / without the question | 37 / 37 | 0 / 0 |
| The quoted reference "Not High-impact" and then one phrase of disagreement (60), with / without | 37 / 0 | 0 / 0 |
| Natural reasons for DECLINED (16), lost | 9 | 0 |
| "Declines, then answers" under INCORRECT (12), lost | 5 | 0 |
| The 120 real judge replies read as the blind reader labelled, with / without the question | 120 / 110 | 120 / 110 |
| Mechanical rewordings of the real verdicts: lost of 1,750, of 400, of 80, of 900 | 0, 0, 20, 0 | 0, 0, 0, 0 |
| Exact match, 300 hand-labelled answers, false credit (of the 111 a person rejects) | 3 | 1 |
| Exact match, 300 answers, lost credit (of the 189 a person accepts) | 85 | 73 |
| The same on the 81 the reader tagged as realistic wording | 37 | 26 |
| 15 plain wordings around the 100 real right answers, lost of 1,500 | 680 | 0 |
| The real answers with another value swapped in, credited of 1,750 | 0 | 0 |
| 60,000 random answers, credited although a word changes the meaning | 0 | 0 |
| The 100 real right answers credited, the 20 real refusals counted | 100, 20 | 100, 20 |
| 22 scripted runs: summary differs from the reader's own count of rows | 1 | 0 |
| 22 scripted runs: usage or cost line differs from the calls that were served | 6 | 0 |
| `--resume` ended in a traceback | 1 | 0 |
| Rows of 20,000 not one physical line or not read back; cut positions misread of 40 | 0, 0 | 0, 0 |
| Minor findings that reproduce, of 6 | 6 | 0 |

No reply and no answer that was read as its label before is read otherwise now. Two things had to be put right on the way: a draft that counted one value written any number of times as one value turned the right sentence written 400 times into a correct answer (the reader's run T08 counts it as unclear), and it gave credit to one of the 60,000 random answers. The rule is now "at most three places", and two words run together with an underscore are not a phrase of the list.

The round 2 reader's sets were run again from that reader's own files after this fix: exact match on its 250 answers, false credit 0 and lost 61; the judge reader on its 88 replies, flattering 0 and lost 9; its scripted run prints the same table (93 correct, 1 unclear, 5 another value, 1 refused, 4 unparseable). All as the README has said since round 2.

## 3. Every finding and what happened to it

FIXED means the reader's own check no longer reproduces it and a test in `tests/test_review_r4_*.py` holds it. STATED AS A LIMIT means the code was left as it is and the sentence named says so.

| Finding | Outcome |
|---|---|
| Numbers, MAJOR 1: `read_judge` credits a CORRECT or DECLINED verdict that its own reason takes back | FIXED where the question is known (0 flattering on every set of the reader, section 2). The rest is STATED AS A LIMIT: README section 2, item 9, "What this cannot do", and item 1 above |
| Numbers, MAJOR 2: the usage and cost line leaves out calls that were answered, with no note | FIXED. Each answered call of the question in flight is noted in `last_question_calls.json`; `--resume` turns the note into an "interrupted" row of `raw.jsonl`, and the summary counts it in the usage only. What cannot be counted is said in the usage line itself |
| Numbers, MINOR 3: `--no-guardrail` still priced the guardrail before the run | FIXED. The estimate leaves the line out and says "NOT APPLIED (--no-guardrail)": $0.1816 where it said $0.2536 |
| Numbers, MINOR 4: one value written twice was "more than one value" | FIXED. The same value in two or three places is one value. The abbreviation in front of its own full name in brackets, and the name in bold before its abbreviation, are each one spelling. Four places or more are unclear |
| Numbers, MINOR 5: three answers built only from list words got credit | Two FIXED: a sentence also starts after a semicolon; quoted text that is neither the question's use case name nor a value makes the answer unclear. One STATED AS A LIMIT: README section 2, item 8, first paragraph |
| Numbers, MINOR 6: clear judge verdicts lost in shapes the README did not list | FIXED: INCORRECT for an answer that declines and then answers; a natural reason for DECLINED when the question is known ("the information is not available in the passages"); `says: "I cannot answer ..."`; quotation marks that are not escaped, a raw line break or a tab inside the reason; `**Verdict:** CORRECT`. STATED AS A LIMIT: an extra key such as `"score": 1` (README item 9, list of lost replies) |
| Numbers, MINOR 7: `raw.jsonl` kept only the first 500 characters of a judge reply | FIXED. The whole reply is kept |
| Numbers, MINOR 8: two gaps in the `--resume` guards | FIXED. `run_config.json` carries a fingerprint of `eval_set_meta.json`, and a `run_config.json` that cannot be read stops `--resume` with a sentence before any call |
| Numbers, MINOR 9: a comma or a dash between "not" and "High-impact" was read as the value "Not High-impact" | FIXED. Between two words of a value only what the value has there may stand, or a space |
| Numbers, MINOR 10: the stop reason of a call was dropped | FIXED. `gen_stop_reason` and `judge_stop_reason` are in `raw.jsonl` and `per_question.csv`, and `summary.md` carries a WARNING line that counts the texts cut at the token limit |
| Numbers, MINOR 11: lost credit on plain wording | FIXED for "Based on the passages, ...", "Sure. ...", "... as of the 2025 inventory.", "... This is stated in passage 1.", an exclamation mark that ends a sentence, "has a stage of development of Deployed", "is listed under", "is classified as", "Department of Treasury". STATED AS A LIMIT: "is currently in the Deployed stage" ("currently" is a word about time and stays off the list) and a use case name repeated with other spacing around its slash (README section 8, round 4 list) |
| Billing, MINOR 15: killed right after the create call, the state file named neither the knowledge base nor the data source | FIXED by name: both fixed names are written to `.state.json` before their create calls, with the id marked as not known yet; a second run of the deploy fills in the ids, a teardown finds both by name. STATED AS A LIMIT: the id of a data source cannot be on record before AWS answers (README section 8, round 4 list) |
| Billing: `.gitignore` did not cover a hand copy of the state file | FIXED: `.state.json*`, `*.state.json`, `*state*.json.bak` |
| Billing: a STOP message printed the full local path of the state file | FIXED. A path under the home folder is printed with `~` |
| Emulator: a failed corpus download ended in a traceback | FIXED. One ERROR line that names the URL, the reason and the way out (`--csv <file>`), exit code 1 |
| Emulator: "Whatever was created so far is recorded in .state.json" was untrue after a lost answer to `CreateKnowledgeBase` | FIXED by the name written before the call |

## 4. How the judge reader reads a reply now

All of it is in `kitlib/scoring.py`, in the block headed "Round 4" above `read_judge`. Every rule below can only refuse a verdict.

With the question known, verdict CORRECT:

1. Everyday names. A value is also recognised as the one-word name of a "Department of X" agency written with a capital letter ("Energy", "Treasury", "State"; ten such names in the inventory), as an agency abbreviation in another letter case ("DoE", "epa"), and, for a stage question, as another form of a stage word ("piloting", "deployment", "retirement"). Another form of a stage word is only named, never taken out: "deployment is planned" is not the value "Deployed".
2. The allow-list. Once the reference value, the things the question gives and a few safe phrases ("no fact that contradicts it") are taken out, every word of the reason must be in `JUDGE_TIE_WORDS` (185 words) or `JUDGE_PRO_FORMS` (57), or be one of the question's own words. "The candidate says the Pentagon; the reference says EPA." is refused for "pentagon", "is at odds with" for "odds", "rejects EPA" for "rejects".
3. The tie. What the reason says of the candidate must hold the reference value, or be made of tie words and say that it agrees, or lead straight to the reference. "The reference is Not High-impact; the candidate says it is." is made of list words and is refused by this rule.
4. A reason must hold the reference value, a word of agreement or a safe phrase. "It is." holds none.

With the question known, verdict DECLINED:

5. The reply may be made only of `JUDGE_REFUSAL_WORDS` (166 words), the question's own words and quoted things. "declines in part", "nearly declines" and "and volunteers the Navy" are refused. Because of that net, the natural ways to say that the documents do not hold the answer are read as a reason for DECLINED (`JUDGE_SAYS_IT_IS_NOT_THERE`, 10 patterns). Without the question they are not.

With or without the question:

6. Without the question no value is known, so the reader compares what the reply says of the candidate with what it says of the reference: "The candidate says Energy; the reference says EPA." gives two different things.
7. A character outside a short list ("=", "<", ">", "/", "+", "$", an emoji, the not-equal sign) refuses CORRECT and DECLINED. An exclamation mark is allowed only where it ends a sentence.
8. Longer lists of words that speak against a verdict: `JUDGE_MISMATCH_WORDS` (109 patterns, among them the families un-, mis- and dis-) under CORRECT, `JUDGE_ADDS_TO_A_REFUSAL` (35) under DECLINED, `JUDGE_OUTSIDE_AGAINST` (8) for the text around a JSON object. `CONTRADICTS_CORRECT` (59) and `CONTRADICTS_DECLINED` (36) are as rounds 2 and 3 reviewed them.
9. An object without a verdict may hold objects, lists and reason-like strings and nothing else, and "Correct: X. Candidate: Y." is a list of labels, not a verdict.

Changed in the other direction, each only where everything in the reply is still read: `**Verdict:** CORRECT`; a reason with quotation marks that are not escaped or with a raw line break; `says: "I cannot ..."`; INCORRECT for "declines but then names ...", and for any mention of a refusal when the question has an answer.

The 27 clear verdicts of the reader's 203 that are still lost with the question, by kind: a negation or "only", "but", "other" used innocently (12: "No issues.", "nothing is missing", "only the wording differs", "not a different agency", "Cannot fault it.", "error-free"); another value named while denying it, or a paraphrase of a value (5: "not Pilot or Retired", "not a high-impact one"); a shape that is not a verdict for this reader (5: a sentence, a verdict line with brackets or a check mark after the word, labels before the verdict); DECLINED whose reason does not say that the candidate declined, or says "although" or "Correct behavior" (4); a key next to the verdict that is not a reason (`"score": 1`, a reason that is `null`: 2). One of them is a reply cut off inside a value.

The fixer's own lists are in `tests/judge_replies_r4.py`. They are not a measurement, because the person who changed the reader wrote them: 105 replies whose reason speaks against the verdict (the round 3 reader read 68 of them as credit, this one reads none so with the question); 115 clear replies (1 lost: "Not High-impact is the reference and the candidate states it."); 10 that are still read flatteringly (item 1 above).

## 5. Exact match: what changed and what is still lost

Changed (`read_answer`, `_spellings`, `LEAD_IN_PHRASES`): a second list of 37 phrases; the number after "passage" or "document" as a citation mark; "of" between the name of the field and the value; an exclamation mark that ends a sentence; one value in two or three places; the abbreviation in front of its own full name in brackets; "Department of X" for "Department of the X" where no other agency's name holds those words; what may stand between two words of a value; a sentence that starts after a semicolon; quoted text that is not the use case name; words run together with an underscore. The 53 phrases of `FILLER_PHRASES` are as rounds 2 and 3 reviewed them. `SCORING_VERSION` is `2026-10-07.r4`, and `--resume` refuses a run that was scored under another version.

Still lost, and left so on purpose: a hedge, a tense, a date or an explanation ("As of May 2025 it is Deployed.", "is currently in the Deployed stage"); the bureau named with the agency; two spellings joined by "or" ("The EPA, or EPA, reported it."); a line break inside a value; a use case name written with other spacing than the question's; an agency abbreviation alone that is also a word or a state code; a table; a refusal in any wording but the fixed sentence (the reader's four rewordings of the 20 real refusals: 80 of 80 are not counted as refusals; they are not credited as answers either). On the kit's own 270 hand-labelled answers: false credit 0, lost 45 (48 before).

## 6. The usage and cost line

`evalloop.evaluate_item` reports after every call that was answered. `50_run_eval.py` writes the numbers of the question in flight (call names, token counts, text units, document ids; no text) to `last_question_calls.json` by replacing the file whole. When a question's row never reaches `raw.jsonl` (Ctrl-C, a kill, a row cut while it was written), `--resume` adds an "interrupted" row from that note before it runs the question again. `summarise` counts such a row in the usage and nowhere else, and the usage line says how many earlier attempts are included. If the note cannot be read it is moved to `last_question_calls_unreadable.json`, the run goes on, and the usage line says NOT COUNTED and for how many questions (up to 4 answered calls each).

## 7. Changed without being asked

- INCORRECT with a reason that says the candidate is "right" or "accurate" is unparseable, as it already was for "correct".
- A JSON object without a verdict may hold only objects, lists and reason-like strings; "Correct: X. Candidate: Y." is not a verdict; the text around a JSON object is checked for words that mark it as an example or a format.
- New columns `gen_stop_reason` and `judge_stop_reason` in `per_question.csv`; new keys `interrupted_attempts_included`, `interrupted_without_a_record`, `answers_cut_at_token_limit` and `judge_replies_cut_at_token_limit` in `summary.json`; `eval_set_meta_sha256` in `run_config.json`; a new file `last_question_calls.json` in every run folder.
- In an answer, the use case name is replaced by a pair of brackets, no longer by a quotation mark, so that the other quotation marks of the answer stay in pairs.
- `10_build_corpus.py --csv <file>` with a file that cannot be read ends in one ERROR line, like a failed download.
- `RESULTS_TEMPLATE.md` has two more rows: what the usage line says is not counted, and the texts cut at the token limit.

## 8. Where the tests are

`tests/test_review_r4_judge.py` with `tests/judge_replies_r4.py` (MAJOR 1, MINOR 6), `tests/test_review_r4_usage.py` (MAJOR 2), `tests/test_review_r4_eval.py` (MINOR 3, 7, 8, 10), `tests/test_review_r4_exact.py` (MINOR 4, 5, 9, 11), `tests/test_review_r4_state.py` (the billing and emulator findings), `tests/test_review_r4_docs.py` (the README and this file against the code). 360 tests in all; run against the kit as it was reviewed, 257 of them fail and 18 more cannot be loaded, because the file they read did not exist. The whole suite is 1,727 tests and passes on Python 3.13 and on Python 3.14.6.
