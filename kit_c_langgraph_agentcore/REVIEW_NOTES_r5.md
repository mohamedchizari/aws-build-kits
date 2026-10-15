# Kit C: review round 5, finding by finding

Round 5 was an independent read of the round 4 code (8 Oct 2026), with a runnable attack suite of 44
cases (27 probes, 17 controls) whose expected labels were hashed before any case ran. This file
records what was done about each of its 18 findings. The tests are in `tests/test_r5_fixes.py`
unless another file is named. Every test named "F..." there failed on the round 4 code; the ones
named "unchanged" pass on both and pin what must not move.

## What is still wrong, first

- Five of the reader's 27 probes still differ from their expected label: TD01, TD05, DOC01, DOC02a
  and DOC02b. All five test a sentence of README.md or START_HERE.md against the code, and their
  expected label is what the old sentence claimed. For those five (F14, F15, F17, F18) the code
  was right and the sentence was corrected, so the probe cannot change. A test in
  `tests/test_r5_fixes.py` now holds each corrected sentence to what the code prints.
- F1 has a cost. If AgentCore ever answers GetAgentRuntime or GetGateway for a resource that is
  gone with an error other than ResourceNotFoundException (section 8, item 15, UNVERIFIED),
  teardown now keeps the record and exits 1 every time, and the clean check says NOT VERIFIED.
  The kit offers no override. With AccessDenied the way out is to grant the read permission.
  The list call still decides in one place: while teardown waits for a runtime or gateway that
  the listing showed and this run deleted.
- F2 is fixed for a docket id written with its agency letters ("FAA-2026-0491"). Written without
  them, "2026-0491" has the form of a document number and is warned by that rule, as before. A
  group of two numbers with no letters before it is still compared one number at a time, and a
  group of two four-digit numbers still passes as a range of years when both numbers stand in the
  run ("2026-2730" when 2026 and 2730 do; the year-range rule does not check that the second is a
  year). Not changed: not part of the reader's case, and the held-out answers decide.
- F5: an honest quotation that joins a title and an abstract with "..." is now warned, because
  the pieces must stand in one string of a tool result.
- F7: the comparison is still case-sensitive, so "Note:" or "Model's summary" in lower case is
  not marked (as in round 4).
- F8: only what is shown is cleaned. The tool error the model receives still holds the argument
  name as it sent it.
- F9: only control characters (Unicode category Cc, other than tab and the line breaks) are
  replaced. Invisible format characters such as a right-to-left override are not.
- F13: 00, 10, 12, 20 and the optional gateway's scripts do not wrap their output. 00_check.py
  masks the one account id it prints; 10_run_local.py could print an account id inside a Bedrock
  error text (not tested).
- README section 8 still says "Nobody independent has read the round 4 fix code." The round 5
  reader did. The sentence was left: it is not one the findings name.
- The answer check has an unseen set of 88 answers that this fixer did not open. Every change to
  the check (F2, F4, F5, F6, F7) can only add a warning or a mark, never take one away; F9
  changes only a text that holds control characters, and F8 changes only what is printed.

## The findings

| Finding | Done | Test | Reader's case before | After |
|---|---|---|---|---|
| F1 MAJOR, recorded runtime called gone when GetAgentRuntime is refused | FIXED in `kit_resources.py`: for a runtime or gateway that `.state.json` records and the listing did not show, any error other than "not found" keeps the record (teardown exits 1) and makes the clean check NOT VERIFIED. The same for the gateway | `test_F1_teardown_keeps_the_record_of_a_runtime_the_get_call_is_refused_for`, `test_F1_the_clean_check_is_not_verified_when_the_get_call_is_refused`, `test_F1_unchanged_a_runtime_that_answers_not_found_is_confirmed_absent`; three existing tests changed (below) | TD07 EXIT0; TD07b CLEAN_AFTER; VC03 CLEAN_EXIT0 | TD07 NOT_EXIT0; TD07b NOT_CLEAN_AFTER; VC03 NOT_VERIFIED_EXIT1 |
| F2 MAJOR, docket id from parts of the run | FIXED in `agent/graph.py`: a group after letters and a hyphen that starts with a year is compared whole, before the year-range rule | `test_F2_a_docket_id_with_its_year_swapped_is_warned`, `test_F2_unchanged_without_the_agency_letters_a_swapped_docket_number_is_still_warned`, `test_F2_unchanged_the_returned_docket_id_ranges_and_model_numbers_pass` | AC01 NO_WARN | AC01 WARN (AC01c NO_WARN, AC14 WARN, as before) |
| F3 MAJOR, an instruction to wait for what cannot come | FIXED in `60_read_usage.py`, README section 4 step 10, START_HERE: with no USAGE_LOGS delivery or a session with no end time, it says the result cannot change however long you wait and that teardown can go ahead | `test_F3_without_a_usage_log_delivery_it_says_waiting_gains_nothing`, `test_F3_a_session_with_no_end_time_says_waiting_gains_nothing`, `test_F3_unchanged_an_early_read_still_says_to_wait` | US03, US04 IMPOSSIBLE_WAIT_SAID | US03, US04 NO_IMPOSSIBLE_WAIT |
| F4, total restated after a sentence of matches | FIXED: the earlier sentence excuses the restatement only when it refers back ("all 31", "the 31", "these 31", "those 31") | `test_F4_a_total_restated_as_a_count_of_documents_is_warned_after_a_sentence_of_matches`, `test_F4_unchanged_a_sentence_that_refers_back_to_the_total_passes` | AC03 NO_WARN | AC03 WARN (AC03c NO_WARN) |
| F5, quotation spliced with "..." | FIXED: the pieces must stand in order inside one string of a tool result | `test_F5_a_quotation_spliced_from_two_documents_is_warned`, `test_F5_the_pieces_of_a_quotation_must_stand_in_order`, `test_F5_unchanged_pieces_in_order_from_one_abstract_pass` | AC04 NO_WARN | AC04 WARN (AC04c NO_WARN) |
| F6, passive "matched" and "among" anywhere | FIXED: "were/was/are/is/has been/have been matched" counts as the sentence's own verb; "among", when it is the sentence's only subset word, excuses a count only within three words of it | `test_F6_a_count_that_was_matched_in_the_passive_is_warned_despite_among`, `test_F6_among_far_from_the_count_does_not_excuse_it`, `test_F6_unchanged_among_next_to_the_count_and_other_subset_words_still_excuse_it` | AC13, AC02 NO_WARN | AC13, AC02 WARN (AC02c, AC12 WARN) |
| F7, look-alike characters hide a kit-shaped line | FIXED: NFKC, format characters removed, look-alike apostrophes folded, any leading white space taken off, before the comparison | `test_F7_a_line_shaped_like_the_kits_is_marked_through_look_alike_characters` (4 cases), `test_F7_unchanged_an_ordinary_line_is_not_marked` | AC05, AC06 marked=False,warned=False; AC06b NOT_MARKED | AC05, AC06 WARN_AND_MARKED; AC06b MARKED (AC06c as before) |
| F8, argument names written into the block | FIXED: each tool error goes through `_cell` in the block, the WARNING line and the replacement text | `test_F8_an_argument_name_the_model_made_up_cannot_write_lines_into_the_block` | AC07 MODEL_LINE_IN_BLOCK | AC07 BLOCK_CLEAN |
| F9, terminal control characters shown | FIXED: each is replaced by a space in the model's text before it is checked or shown | `test_F9_terminal_control_characters_in_the_models_text_are_not_shown`, `test_F9_unchanged_tabs_and_line_breaks_stay` | AC08 ESC_IN_ANSWER | AC08 NO_ESC_IN_ANSWER |
| F10, DELETE_FAILED reported as not asked | FIXED: the clean check counts it as left (NOT CLEAN) with its status; teardown says it still exists | `test_F10_a_runtime_in_delete_failed_is_not_clean_and_is_not_called_unaskable` | VC04 NOT_VERIFIED_EXIT1 | VC04 NOT_CLEAN_EXIT1 |
| F11, "running totals" not seen | FIXED: the reason names only the layouts seen | `test_F11_the_mixed_layouts_reason_names_only_the_layouts_seen` | US01 SAYS_RUNNING_TOTALS | US01 NO_FALSE_RUNNING_TOTAL_CLAIM |
| F12, LOWER BOUND only beside a price | FIXED: the caveat ends every "Token cost:" line | `test_F12_the_lower_bound_is_said_when_no_price_is_known` | US02 NOT_SAID | US02 LOWER_BOUND_SAID |
| F13, account ids printed by 30 to 60 | FIXED: 30, 40, 50 and 60 wrap `out` with `kitlib.redacting`; its docstring now names the scripts that do | `test_F13_60_show_logs_masks_an_account_id_in_the_runtime_log`, `test_F13_scripts_30_to_60_hand_a_masking_print_to_everything_they_run` (4 cases) | RD01 FULL_ACCOUNT_ID_PRINTED | RD01 MASKED |
| F14, exit 0 with "Teardown finished." | FIXED in README section 5 (the exit-0 row names both forms) and START_HERE | `test_F14_every_exit_0_ending_of_teardown_is_in_the_readme_table_and_start_here` | TD01 EXIT0_WITH_OTHER_LINE | the same (the probe's label is the old sentence) |
| F15, exit 0 when the tag listing was refused | FIXED in README section 5 (the exit-0 row) | `test_F15_the_exit_0_row_does_not_claim_a_tag_listing_that_was_refused` | TD05 EXIT0_WITHOUT_TAG_LISTING | the same (as above) |
| F16, the line above "Now prove it" | FIXED in `90_teardown.py`: every other closing line comes before the verdict | `test_F16_the_verdict_is_the_line_right_above_now_prove_it` | TD06 LINE_ABOVE=Removed the local .build folder. | TD06 LINE_ABOVE_IS_VERDICT |
| F17, "two `Next:` lines" | FIXED in START_HERE | `test_F17_start_here_describes_the_last_lines_of_30_deploy_as_printed` | DOC01 NEXT_LINES=1 | the same (as above) |
| F18, STOPPED for another Region, then --region | FIXED in README section 5 and START_HERE: for a file that records another place, run the command the STOPPED message gives; TEARDOWN INCOMPLETE is for a file that cannot be used | `test_F18_after_stopped_for_another_region_naming_a_place_does_not_say_teardown_incomplete` | DOC02a rc=4,STOPPED; DOC02b rc=1 | the same (as above) |

Existing tests changed, because they pinned what F1 corrects:
- `tests/test_r2_money.py`: `test_M7_teardown_finishes_when_the_get_call_reports_a_missing_runtime_with_another_error`
  (3 cases) is now `test_M7_a_recorded_runtime_the_get_call_answers_with_another_error_keeps_its_record`: exit 1
  and the record kept, where it asserted exit 0 and the record cleared.
- `tests/test_gateway.py`: `test_gateway_teardown_takes_the_list_call_as_proof_when_the_get_call_fails_another_way`
  is now `test_gateway_teardown_keeps_the_record_when_the_get_call_fails_another_way` (exit 1, record kept), and
  `test_gateway_teardown_keeps_the_record_of_a_gateway_it_cannot_confirm_gone` no longer queues the list call
  the code no longer makes. Its assertions are unchanged.

Also changed, to keep documents true: README section 8, item 15 (the list call), the counts in
sections 1 and 8, the file table in section 1 (this file); notes that start `> ` in
`RECORD_OF_REVIEWS.md` (its old text is held unchanged by a test); the docstrings of `agent/graph.py`,
`kit_resources.py`, `kitlib.redacting` and `60_read_usage.py`.

## Counts, before and after

The reader's suite, run against this tree by a copy of the reader's runner that copies the test
into this kit's `tests/` folder and prints `module.__file__` for every module under test:

| | before | after |
|---|---|---|
| probes that showed a defect | 25 of 27 | 5 of 27 (TD01, TD05, DOC01, DOC02a, DOC02b: see the first section) |
| controls broken | 0 of 17 | 0 of 17 |
| wrong clean | 3 of 8 | 0 of 8 |
| unsupported model text that passed | 5 of 5 | 0 of 5 |

The rows were the same on Python 3.13.16 and 3.14.6. The kit's suite: 993 passed before; 1031
passed, 0 failed, after, on Python 3.13.16 and on Python 3.14.6 (38 new tests in one new file).
