# Kit B, round 5 (fifth independent review, 2026-10-08): what was found, what was done, what is left

Nothing here was run against AWS. One reader attacked the round 4 changes and wrote a runnable suite (68 + 15 cases, hashed before any case ran, and 11 scenario tests). Its headline before this fix: 36 wrong outcomes in 36 attack cases, 46 of 46 controls kept. After: 0 wrong in 36, 46 of 46 kept, on Python 3.13.16 and 3.14.6. Every count below was made offline.

## 1. What is still wrong, worst first

1. **The judge reader is still word lists, now with rules about sentence shapes.** With the question known it still reads as credit a reply made of list words in a shape the rules do not know. Two are known and kept as tests so the README cannot go stale: "The candidate gives a stage, and the reference gives a stage too." (CORRECT, since round 4) and "The candidate's answer is a refusal; its budget figure is not in the documents." (DECLINED, found in round 5: "its" is read as the use case's, because "the candidate declines since its budget is not recorded" means the use case). Without the question nothing changed in round 5, so the fifth reader's DECLINED replies are still read as credit there (only `scoring.read_judge` called by hand reads without the question).
2. **The round 4 reader's 203, 82 and 60 replies and the 20 real DECLINED replies of the rehearsal were not read again.** They are not in the kit. The round 5 rules can have moved those counts with the question in both directions: they refuse more, and they read refusals that were lost. README section 2, item 9 says so next to the counts.
3. **Clear replies are still lost**, and round 5 adds one shape on purpose: a DECLINED whose reason says only in the judge's own words that the answer is not there ("The information is not available in the documents.") no longer counts as the candidate declining (rule 5 below). Of the fixer's second set, 3 of 46 are lost (none read as credit): "The candidate's high impact determination matches the reference.", "The candidate gives the same high-impact status as the reference." (both lost before round 5 too) and "The candidate refuses to give a budget figure because the documents lack one." ("give" after "refuses to" is on a round 3 list).
4. **Everything was measured on hand-written text.** No Amazon Nova judge reply has been read.

## 2. The reader's headline counts, before and after

Command, run from the fixer's folder with the reader's `attack/` copied unchanged next to the kit copy (the runner checks the sha256 of its four files first):

`env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN -u AWS_CA_BUNDLE <venv>/bin/python -I attack/run_attacks.py`

| Finding | Wrong before | Wrong after |
|---|---|---|
| F1, DECLINED credit | 16 of 16 | 0 of 16 |
| F2, CORRECT credit | 9 of 9 | 0 of 9 |
| F3, interrupted row that never was | 1 of 1 | 0 of 1 |
| F4, download traceback | 1 of 1 | 0 of 1 |
| F5, refusals lost | 7 of 7 | 0 of 7 |
| F6, NOT COUNTED count | 1 of 1 | 0 of 1 |
| F7, gitignore | 1 of 1 | 0 of 1 |
| Headline | 36 of 36 | 0 of 36 |
| Controls kept | 46 of 46 | 46 of 46 |

The documented exact-match case ("It was reported, is the answer the Environmental Protection Agency") is still credited, as README section 2, item 8 says; it is not counted in the headline.

## 3. Every finding and what happened to it

| Finding | Outcome | Tests | Reader's case before / after |
|---|---|---|---|
| F1 (MAJOR) DECLINED credited when its reason says the candidate gave a value | FIXED with the question (rules 1 to 5). Without the question STATED AS A LIMIT (README section 2, item 9) | `test_review_r5.py`: `test_the_readers_judge_cases_come_out_as_a_person_reads_them`, `test_a_reason_that_says_the_candidate_gave_something_is_not_a_refusal`, `test_a_shape_found_while_attacking_the_round_5_reader_is_not_a_refusal`, `test_the_judges_own_words_that_the_answer_is_not_there_no_longer_count_as_the_candidate_declining`, `test_the_round_5_rules_are_not_applied_without_the_question`, `test_the_round_5_rules_are_fast_on_a_long_reply` | F1-01 to F1-16: DECLINED / UNPARSEABLE |
| F2 CORRECT credited when a second sentence contradicts the reference; the comment at scoring.py ~1303 false | FIXED: a free word of a stage or high-impact value refuses CORRECT in every kind of question; the comment now says what the code does | `test_the_impact_is_high_is_refused_in_every_kind_of_question`, `test_a_stage_said_in_other_words_after_the_match_is_refused`, `test_a_field_name_and_the_reference_value_itself_are_not_value_words_of_their_own` | F2-01 to F2-09: CORRECT / UNPARSEABLE |
| F3 removing a damaged row made a finished question "in flight" | FIXED: the calls record also holds `question_rows_before`; the row of the attempt arrived when raw.jsonl holds more rows of that question than then. The refusal message says what removing a row does | `test_removing_a_damaged_row_of_another_question_runs_only_that_question_again`, `test_a_question_really_in_flight_is_still_found_after_another_row_was_removed`, `test_the_record_says_how_many_rows_of_its_own_question_there_were`, `test_a_record_written_before_round_5_is_read_by_the_round_4_rule`, `test_item_18_says_what_removing_a_damaged_row_does` | S1: failed (exit 1, phantom q-006 row, "in flight") / passed (exit 0, 6 Retrieve calls) |
| F4 `IncompleteRead` during the download gave a traceback | FIXED: `http.client.HTTPException` is caught with the other two | `test_a_download_cut_short_is_one_message_and_builds_nothing` (3 cases) | S2: traceback / "ERROR: could not download the inventory CSV", exit 1 |
| F5 ordinary refusals lost | FIXED for the reader's 7 and the fixer's 25; 9 words added to `JUDGE_REFUSAL_WORDS`, "which is correct" after a refusal is safe, "responds with the refusal sentence" and "says the record is silent" are no longer read against DECLINED | `test_an_ordinary_refusal_is_read_as_declined`, `test_which_is_correct_after_a_refusal_is_not_read_against_it_but_a_correct_answer_still_is`, `test_does_not_use_the_refusal_sentence_is_not_a_refusal` | F5-01 to F5-07: UNPARSEABLE / DECLINED |
| F6 a second damaged record replaced the first | FIXED: each is moved to its own name (`last_question_calls.unreadable.json`, `-2`, `-3` ...) and all are counted and named in the usage line | `test_each_damaged_record_is_kept_and_counted` (2 and 3 records) | S7: "1 interrupted question(s)" / "2 interrupted question(s)" |
| F7 `.gitignore` missed copies of the state file | FIXED: `*state*.json` ignores every file whose name holds "state" and ends ".json" | `test_every_name_with_state_that_ends_json_is_ignored_by_pattern`, `test_git_itself_ignores_every_copy` (real `git status --ignored`), `test_no_file_the_kit_ships_is_hidden_by_the_new_line` | S8: failed / passed |
| Documents named by the reader | CORRECTED: README section 2, item 9 (the examples, the DECLINED sentence, a round 5 paragraph, the 203 counts dated); section 8 bullet "The judge reader is still lists of words"; RESULTS_TEMPLATE.md "Correct as judged" line; README item 18 (version, removing a row) | `test_item_9_puts_the_round_5_news_first_and_says_the_round_4_counts_predate_it`, `test_section_8_and_the_template_describe_the_judge_reader_as_it_is` | |

## 4. The rules (`kitlib/scoring.py`, block "Round 5")

With the question known, under DECLINED:

1. Every clause whose subject is the candidate, its answer, response or reply must be a refusal (`_REFUSAL_CLAUSE`): declines, refuses, abstains; cannot answer, is unable to; does not answer, give, provide ...; gives, has, offers ... no answer; uses or is the refusal sentence (not "with a budget figure"); or says, states, notes, explains, reports ... (that) it cannot answer, or that the documents, the budget or the answer are not there. Each later part of the clause after a comma or "and" that starts with a verb is read the same way; a relative clause right after the subject ("The candidate's reply, which holds a budget figure, ...") too.
2. "it", "they", "this", "the answer" and "the candidate's refusal" as a subject may decline, say that something is not there, or be "the expected behaviour"; anything else with a verb is refused. "it" or "the candidate" followed by a verb that gives ("the figure it found", "the budget figure the candidate determined") is refused anywhere.
3. A passive or a "there is" that gives something ("a budget figure is given", "the agency is in the answer", "... is the answer", "with a budget figure") is refused unless a negation or a refusal stands before it in its clause; "the candidate's figure" and "declines: budget figure" always.
4. Every sentence must say something negative (a refusal, "no", "not", "lacks" ...) or be plain ("This is the expected behaviour.", "Reference is NO ANSWER.").
5. "The documents lack it" in the judge's own words no longer counts as the candidate declining (`JUDGE_SAYS_IT_IS_NOT_THERE` is no longer part of that test); it counts where the candidate is said to say it (rule 1).

With these in place, `JUDGE_REFUSAL_WORDS` (175 words; 166 in round 4) took "appropriate explicitly stating uses used using sentence based exact"; "which is correct", "this is appropriate" after a refusal are safe phrases (`JUDGE_SAFE_UNDER_DECLINED_WITH_THE_QUESTION`); "does not use the refusal sentence" is refused first (`JUDGE_NOT_A_REFUSAL`). `CONTRADICTS_DECLINED` (36 patterns), `JUDGE_ADDS_TO_A_REFUSAL` (35), `JUDGE_SAYS_IT_IS_NOT_THERE` (10), `JUDGE_TIE_WORDS` (185) and `JUDGE_PRO_FORMS` (57) keep their sizes.

With the question known, under CORRECT: a word of a stage or high-impact value (`_value_words`: deployed, deployment, development, high, impact, pilot, pre, presumed, retired, and "use" where it is not "use case") that stands outside the reference value and outside a field name ("stage of development", "high-impact determination") refuses the verdict, in every kind of question; "development" after "in" or "in the" counts even inside "development stage".

The scoring version is `2026-10-08.r5`, so a run started under the round 4 rules cannot be resumed.

## 5. The fixer's own sets (`tests/judge_replies_r5.py`), not a measurement

- 30 DECLINED replies whose reason says the candidate gave something, and 25 ordinary refusals, written before they were run on either reader. Round 4 reader: 5 of 30 refused, 15 of 25 read. First run of the round 5 draft: 29 of 30 and 22 of 25; the draft was then changed. Now: 30 of 30 and 25 of 25, for a budget question and a held-out agency question.
- A second set of 46 (CORRECT and DECLINED, both directions), written after that change and before its own first run: 40 of 46 read as a person reads them on that run, 43 of 46 now, 27 of 46 by the round 4 reader. The 3 misses are losses, never credit (section 1, item 3).
- 34 shapes written while attacking the round 5 draft; 6 of them were read as DECLINED by a draft and made it stricter. All 34 are refused. One more is still read as DECLINED and is the limit in section 1, item 1.
- Every judge reply in the kit's earlier test sets (rounds 2 to 4, also the five real CORRECT wordings over every value) was read by the round 4 and the round 5 reader inside one test run: the only two that changed are the round 4 limits "The candidate declines. The agency is in the answer." and "The candidate has the answer. It declines to say so.", now refused with the question.

## 6. Existing tests that were changed, and why

- `tests/judge_replies_r4.py` `STILL_READ_FLATTERINGLY`: the two DECLINED limits above now say `False` with the question (the list's own rule: correct it when one starts to be caught). `tests/test_review_r4_docs.py::test_item_9_puts_the_round_4_news_first_and_names_what_is_still_read_flatteringly` expects 1 such reply instead of 3.
- `tests/test_review_r4_judge.py::test_the_words_of_the_allow_list_are_the_ones_the_readme_counts`: `JUDGE_REFUSAL_WORDS` 166 to 175 (F5).
- The scoring version `2026-10-07.r4` to `2026-10-08.r5` in `test_review_r2_table.py`, `test_review_r3_docs.py`, `test_review_r3_judge.py`, `test_review_r4_docs.py::test_item_18_names_the_round_4_guards` and `test_review_r4_judge.py::test_the_scoring_version_is_the_round_4_one`.
- `tests/test_review_r4_docs.py::test_item_9_states_the_sizes_of_the_lists` also looks in this file for a list size, and `test_the_test_counts_agree_between_the_readme_and_the_notes` (the README total) adds the round 5 tests that section 8 counts.
- `tests/test_review_r4_usage.py::test_the_record_holds_numbers_and_ids_and_no_text`: the record has one more number, `question_rows_before` (F3).

The reader's two scenario files `tests/test_attack_r5b.py` and `tests/test_attack_r5b_2.py` are in the kit unchanged (their sha256 is the one the reader recorded), so the reader's runner finds them at `../kit/tests/`.

## 7. Test counts

`python -m pytest -q`: 1,981 passed on Python 3.13.16 and 1,981 passed on Python 3.14.6 (1,733 before). 248 are new in round 5 (`tests/test_review_r5.py` 237, the reader's two files 11); run against the kit as it was reviewed in round 5, 147 of those 248 fail (the 101 that pass there are controls, the reader's 7 scenario controls among them, and the speed test).
