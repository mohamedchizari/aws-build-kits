# Kit C: record of reviews

What `README.md` said before it was shortened on 2026-10-07, after review
round 4, under headings by round. The README has the current state, and
`REVIEW_NOTES_r4.md` has round 4 finding by finding.

Nothing here was reworded. Every line of the README as it stood that is no
longer in the README stands in this file, unchanged. Added to the old text are
the headings, the code fences around passages that are quoted out of their
place, and the lines that start `> `, which say where a statement was
corrected later.

Read "Statements corrected in round 4" first: the parts after it repeat those
statements in their place, as history. In all of them "this code" means the
code of round 4, and section numbers are the README's.

- **Statements corrected in round 4**: each as it stood, and what replaced it.
- **Round 4**, **Round 3**, **Round 2**, **Round 1**: what the README said of
  each round.
- **Before the reviews**: how the sources were read, and corrections to the
  research notes.
- **Reference text that left the README when it was shortened**: not history.
  The rules of the answer check one by one, the billing traps, usage data,
  quotas, things that can go wrong, sections 5, 6 and 7 as they stood, every
  AWS call that was not run, the UNVERIFIED items in full and the 42 sources.
  It was written for the code of round 4, and the kit's tests still hold
  several of its statements to the code.

## Statements corrected in round 4

Until round 4 the README gave, as the main result of the round 3 rehearsal,
that the smaller stand-in model wrote a misleading answer to 13 of 30
questions and to 12 of 30 after the system prompt was rewritten, that
rewriting the prompt did not fix it, and that the choice of model mattered
more than the prompt or the check. Round 4 showed where that came from. The
rehearsal's tool calls were chosen in advance by the agent that prepared it:
the model was handed the results of searches it had not written, often a
single search whose matches were mostly off topic, and had to answer from
them. In the kit the model writes its own searches and can search again. Round
4 let the same model (Claude Haiku) choose its own tool calls, through the
kit's real tools against the live Federal Register API, on the same 30
questions:

| Who chose the tool calls | System prompt | clean | minor | misleading | answers |
| --- | --- | --- | --- | --- | --- |
| the preparing agent | as before round 3 | 10 | 7 | 13 | 30 |
| the preparing agent | rewritten in round 3 | 11 | 7 | 12 | 30 |
| the model itself | as before round 3 | 21 | 8 | 1 | 30 |
| the model itself | rewritten in round 3 | 22 | 7 | 0 | 29 (1 conversation ended at the kit's step limit) |

The counts of the rehearsal stand, as counts of that rehearsal, and so does
what the check did with its 120 answers: it passes 15 of the 25 misleading
ones with no warning. What does not stand is each statement below, which read
the rehearsal as more than it was, or which round 4 overtook. Each is given as
it stood, with the lines it had in the README before the shortening, and with
what replaced it. The limits of round 4 are in README section 2: stand-in
models and not the kit's default, each in its own harness, and no misleading
answer among the 88 that the check was run on. The source is
`../_review_reports/round4/FINDINGS_round4.md`, sections 1, 2 and 4.

C11 and C12 are of another kind. No reader of round 4 reported them. They are
two sentences that the documentation pass after round 4 found the kit's own
steps and scripts do not bear out, when it wrote `START_HERE.md` from them.

### C1. Section 2, the first of "the three results that matter most"

As it stood (README lines 123 to 127):

```
- The smaller of two stand-in models gave a misleading answer to 13 of 30
  questions. The system prompt was then rewritten against exactly those
  errors, and the same model gave a misleading answer to 12 of 30. The larger
  model gave none in 60 answers. Rewriting the prompt did not fix the smaller
  model.
```

Replaced by: README section 2, the table of the four conditions and the paragraph under it: the 13 and the 12 belong to tool calls chosen for the model; with its own it misled in 0 or 1 of 30 answers, and the rewritten prompt made little difference in either condition.

### C2. Section 2, "Read the columns headed This code for what they are"

As it stood (README lines 226 to 229):

```
Read the columns headed "This code" for what they are. The second correction
was made with the second pass's answers in view, as the first was with the
first pass's, and no answers that this code has not seen have been put through
it. The first correction shows what such a figure is worth: no wrong warning
```

Replaced by: README section 2, "The check on 88 answers it had not seen": 88 answers written with the models' own tool calls were put through the check; none of them was misleading, so they say nothing about what it catches.

### C3. Section 2, "What this means if you run the kit"

As it stood (README lines 240 to 244):

```
exists. And in this rehearsal the choice of model mattered more than the
prompt or the check: the smaller model misled in 25 of its 60 answers and the
larger in none of its 60, the rewritten prompt moved the smaller model from 13
to 12, and the check warned or replaced 7 of the 13 and 3 of the 12. Neither
stand-in is the kit's default model, which has not been tried.
```

Replaced by: README section 2, "That was wrong": the gap between the two stand-in models was measured only with tool calls chosen for them. Section 7 now lists the claim under what you cannot say.

### C4. Section 7, "You cannot say": "That the agent's answers are correct, or were evaluated"

As it stood (README lines 1077 to 1080):

```
  seen 120 answers from two stand-in models (Claude Haiku and Claude Sonnet),
  not from the model you ran, for tool calls a person's agent had chosen;
  readers called 25 of them misleading, all 25 from the smaller model, and the
  check as it is now passed 15 of those 25 with no warning.
```

Replaced by: README section 7, the same bullet: 120 answers written from tool calls an agent had chosen (25 misleading, 15 of those passed with no warning) and 88 written with the models' own tool calls (none misleading).

### C5. Section 7, "You cannot say": "That a document the agent listed is about what you asked"

As it stood (README lines 1085 to 1087):

```
  rule on X" in an answer is that, or that nothing else was published. These
  were the commonest serious errors in both rehearsal passes and no rule in
  the kit checks them. The block gives you each title and a count of search
```

Replaced by: README section 7, the same bullet, which now says only "No rule in the kit checks these": how common such errors are when a model chooses its own searches has not been counted.

### C6. Section 7, "You cannot say": "That the prompt or the check makes a weak model safe to use"

As it stood (README lines 1091 to 1095):

```
- That the prompt or the check makes a weak model safe to use. In the
  rehearsal the rewritten prompt moved the smaller stand-in from 13 misleading
  answers in 30 to 12, the check passed most of them, and the larger stand-in
  wrote none in 60. Which model you ran matters more than either, and the
  kit's default model was in neither pass.
```

Replaced by: README section 7, two bullets: "That the prompt or the check makes a model safe to use" and "That the choice of model matters more than the prompt or the check, or that rewriting the prompt failed to fix a smaller model".

### C7. Section 7, "You cannot say": "That the warnings are reliable on your model's text"

As it stood (README lines 1096 to 1098):

```
- That the warnings are reliable on your model's text. The check put a wrong
  warning on 10 of 39 clean answers the first time it met text it had not been
  corrected on, and on 12 of 68 honest texts a reader wrote for round 4.
```

Replaced by: README section 7, the same bullet, with the 8 warnings on the 88 answers the check had not seen. The 10 of 39 is a figure of round 3 and stands under "Round 3" below; the 12 of 68 stands under "Round 4".

### C8. Section 8, round 3, "What the second pass found"

As it stood (README lines 1190 to 1193):

```
- What the second pass found. The rewritten prompt did not fix the smaller
  model: Claude Haiku wrote 13 misleading answers of 30 in the first pass and
  12 of 30 in the second, Claude Sonnet 0 of 30 both times (its clean answers
  rose from 23 to 28). The check passed 9 of the 12 with no warning:
```

Replaced by: README section 2: with its own tool calls the same model misled in 1 of 30 answers before the prompt was rewritten and in 0 of 29 after it.

### C9. Section 8, round 3, "What was not measured"

As it stood (README lines 1221 to 1225):

```
- What was not measured. Answers that this code has not seen: the second
  correction was made with the second pass in view, as the first was with the
  first. What that is worth is shown by the first correction: no wrong warning
  on the 33 clean answers it was tuned on, ten on the next 39. The kit's
  default model was not used at all. No model chose its own tool calls. The
```

Replaced by: README sections 2 and 8: round 4 measured both with stand-in models, on 88 answers the code had not seen. The kit's default model has still not been used at all.

### C10. Section 8, NOT RUN, the bullet for `10_run_local.py` and `12_serve_local.py`

As it stood (README lines 1479 to 1484):

```
  Converse through `langchain-aws`. The kit has never called a model. The
  tool schemas have not met a real model: in both rehearsal passes an agent
  chose the tool calls. The prompt as it was before round 3 and the prompt
  as it is now were each read by two stand-in models as plain text. The
  answer check has seen 120 real answers from those two models and
  otherwise only text written for the tests and the acceptance runs. How
```

Replaced by: README section 8, "NOT RUN": stand-in models have since called the kit's tools from a shell and the check has met 88 more real answers; the tool schemas have still not met a model through Bedrock.

### C11. Section 7, "you can say": "You called the local server with curl"

As it stood (README lines 1042 to 1042):

```
- You called the local server with curl and saw the contract it serves
```

Replaced by: README section 7, the same bullet, which now says that you served the entrypoint on your own machine and that the self-test of step 3 makes both calls: no step of the README has you type a curl command (they are in `python 12_serve_local.py --help`).

### C12. Section 5, the teardown that names its place with `--region` and `--prefix`

As it stood (README lines 899 to 899):

```
as it is. Its last line is `TEARDOWN INCOMPLETE` and its exit code is 5, not
```

Replaced by: README section 5: "Its verdict line starts `TEARDOWN INCOMPLETE`". The script prints one or two lines after the verdict, and its last line is always `Now prove it: python 99_verify_clean.py`.

## The four rounds in one paragraph

### As section 8 opened

Everything here was done on 2026-10-07 in Linux workspaces with no AWS account
and no credentials of the owner's: the kit was written, reviewed
independently, corrected, reviewed independently a second time, corrected
again, and then its answer check was rehearsed twice on text written by two
real models and corrected after each pass, on the same day.

## Round 4

### The dated line of section 8

Reviewed independently a third time on 2026-10-07 (round 4): 1 blocker, 7
majors and 13 minors from a reader of what a user sees, and more from two
others. `REVIEW_NOTES_r4.md` has each, what was done, and what is still wrong.

### From section 2: the reader's planted and honest texts

Measured in round 4 on texts the code had not seen: a reader wrote 212 texts
with planted unsupported content and 68 honest ones. The code as it stood
passed 50 of the 212 with no warning (26 of them inside what this section then
said was compared) and warned 12 of the 68. This code passes 25 (numbers in
words, an ordinal, "FY27", and 19 counts in wordings the count rules do not
read) and warns none; that pair is again for texts the rules were corrected
on. `REVIEW_NOTES_r4.md` has every finding of round 4.

### From section 8: what ran (SAFE), with the test counts of round 4

**SAFE: what ran here**

- `python -m pytest -q`: 970 passed, 0 failed, with the network blocked and
  AWS variables removed, on Python 3.13.16 and again on Python 3.14.6 (not on
  3.11, where the 830 tests of round 3 ran), each in a clean environment built
  from `requirements.txt` alone, outside the kit folder. 20 test files:
  `test_aws_flows.py` 33, `test_cli.py` 47, `test_entrypoint.py` 12,
  `test_fr_tools.py` 45, `test_gateway.py` 12, `test_graph.py` 24,
  `test_grounding.py` 66, `test_hosted_calls.py` 8, `test_kitlib.py` 24,
  `test_package.py` 10, `test_r2_answer_check.py` 251, `test_r2_money.py` 31,
  `test_r2_usage.py` 25, `test_r3_rehearsal.py` 93, `test_r3_second_pass.py`
  36, `test_r4_answer_check.py` 98, `test_r4_money.py` 41, `test_readme.py`
  23, `test_state_guard.py` 69, `test_usage_cost.py` 22.
  `test_r3_rehearsal.py` was new after the first rehearsal pass: run against
  the code as it was before round 3, 80 of its 93 tests fail; the other 13 pin
  rules that did not change. `test_r3_second_pass.py` is new after the second
  pass: run against the code as it was before the second correction, 23 of its
  36 tests fail; the others pin what had to stay. Seven older tests of the
  code were changed with the rules they pinned after the first pass and two
  more after the second, and each says so where it stands; `test_readme.py`
  was changed with the README both times.
- The graph ran end to end with scripted fake models: model to tool to
  model to finalize to end, two tool rounds, the recursion limit (measured: a
  limit of 12 lets four tool rounds finish and stops a fifth, and the tokens
  used up to the stop are still reported), the cap of three tool calls per
  turn, and the answer check in the tests of `test_grounding.py` and
  `test_r2_answer_check.py`, through the graph, the hosted entrypoint, the
  hosted caller and the local script. The acceptance runs above used the
  same graph, and so did the rehearsal: the 120 real answers of the two
  passes went through `run_question` as the last turn of a scripted model.
- The hosted entrypoint ran as a real HTTP server on 127.0.0.1:8080 with the
  fake model: `GET /ping` returned 200 `Healthy`, `POST /invocations` returned
  200 with the tool call, real documents, the block, the model's text and the
  check report as separate fields.
- `20_package.py` ran for real, from the lock file, on a copy of this code:
  uv installed the 119 pinned packages for arm64 Linux and Python 3.13, and
  the zip came to 54.0 MB zipped and 149.8 MB unzipped, 6,412 files. The 15
  scripts in `bin/` all begin `#!/usr/bin/env python3`, and no path of the
  build machine is in the zip. All 36 native libraries in it are aarch64
  builds, checked by their ELF headers. The fallback build with
  `ENABLE_OTEL=false` also ran: 50 packages, 44.3 MB zipped, 123.2 MB
  unzipped, 4,900 files. Three compiled libraries carry a path from their own
  publishers' build machines (`/root/.cargo/...`); those are not yours and are
  left alone. Neither zip was started on an arm64 machine or uploaded
  anywhere.
- Live Federal Register requests: 10 GETs while the kit was written, 11 by
  the first reviewer (4 of them unintended, which is why the recorder now
  needs `--record`), 4 during the first correction, and 2 during the second:
  the two fake-model runs in section 4. The second review's answer-check
  reader fetched 200 records (100 rules, 100 notices); the listings, the
  abstract lengths and the 10,000 figure quoted here come from those. The
  rehearsal sent 47 and stored the responses; the second pass and both
  round 3 corrections sent none and worked from that store.
- 14 of 14 scripts (the ten numbered scripts, the three gateway scripts and
  `tests/record_fixtures.py`) answer `--help` with exit code 0 and `--dry-run`
  with the exit code they document, with no credentials and the network
  blocked, and write no state file. That code is 0 for eleven of them and 3
  for `90_teardown.py`, `99_verify_clean.py` and
  `optional_gateway/90_teardown_gateway.py`, on purpose. 7 of 7 billing
  scripts refuse to run without `--i-understand-this-bills`.
- Every AWS request the scripts build is checked against the service
  definitions in botocore 1.43.108, both in `--dry-run` and in the tests:
  parameter names, types, required fields and length limits. The tests also
  run each script's logic against responses shaped like the documented ones,
  including the full teardown and every verdict of the clean check, and
  `test_r2_money.py` runs deploy, teardown and the clean check against a
  small stateful fake of the account with two Regions.
- The cost function reproduces AWS's worked example on the pricing page
  ($0.006703 per session) to within a millionth of a dollar, and the figures
  for an unstopped session in section 2 are tested against the same list
  rates.

## Round 3

### From section 8: the dated line, and the two rehearsal passes point by point

Rehearsed on real model text on 2026-10-07 (round 3), in two passes: 120
answers to 30 questions, 60 in each pass, written by two stand-in models
(Claude Haiku and Claude Sonnet, not the kit's default model) from the kit's
own final-turn prompts, with the tool calls chosen by an agent and not by the
model; blind readers labelled the first pass 33 clean, 14 minor, 13 misleading
and the second 39 clean, 9 minor, 12 misleading. First pass: before round 3
the check passed 9 of the 13 misleading answers and warned or replaced 10 of
the 33 clean ones; on this code it passes 6 of the 13 and warns or replaces 3
of the 33. Second pass: the check as corrected after the first pass passed 9
of the 12 misleading answers and warned or replaced 13 of the 39 clean ones;
on this code it passes 9 of the 12 and warns or replaces 3 of the 39.

> Corrected in round 4: in the list below, the opening of "What the second
> pass found" is C8 above, and "What was not measured" holds C9.

- What the first pass was. An agent wrote 30 questions and chose the tool
  calls for each (47 live requests to the Federal Register, stored). The
  kit's own graph produced the conversation up to the model's last turn.
  Each stand-in read those conversations as plain text, 15 to a file, and
  wrote the final answer of each. The kit's check then ran on the 60 texts
  with the stored tool results. No AWS call and no call through Bedrock
  was made. Nothing here exercises a model that chooses its own searches,
  calls no tool, or sends a wrong argument.
- What the first pass found. 13 misleading answers, all from Claude Haiku.
  Nine of them the check had passed with no warning, and none of the nine
  holds an invented number. In four, a search total stands as a count of
  documents on a topic ("EPA published 31 proposed rules about air quality
  implementation plans", when 4 of the 10 documents returned are on other
  subjects by their titles and abstracts and 21 were never seen). In five,
  a returned document is
  presented as the thing asked for when its own fields say otherwise, or
  documents on other subjects are listed as answers.
- What the first correction did to those 60 answers. Three of the nine
  are now warned, by the new rule on totals. Six still pass: five of the
  second kind, one of the first in a wording the rule does not read. Two of
  the six carry a `NOTE:` that neither the title nor the abstract of the
  document called the newest holds a word of the search. The commonest real
  error, a search total or an off-topic document presented as the answer,
  is one the check sees only in part.
- False warnings in the first pass. Of the 33 clean answers 9 were warned
  and 1 replaced before; 2 are warned and 1 replaced now. The causes that
  were removed: a
  date of the model's own search (3 answers), a date the question gave in
  words (1 of those 3), a count compared with the number of documents the
  text named (2), a number the user asked about whose lookup failed, called
  "may be invented" (2, still warned, in true words now), docket ids copied
  from the `docket_ids` field (2), "names none of the documents" on an
  answer to "how many" (2), and the year of a returned date read as a
  number in no tool result (1). The 2 clean answers still warned follow a
  lookup that failed. The 1 replaced followed an empty search.
- What the second pass was. The first correction had added four rules to the
  system prompt (rules 10 to 13), two fixed sentences to each search result,
  two fields to each document in it, and lines to the block. The same 30
  questions, the same recorded tool calls and the same stored Federal Register
  responses were put in front of the same two stand-in models again with that
  prompt and those tool results, and they wrote 60 new answers. New readers
  labelled them, blind as before. Their instructions had two more lines than
  the first pass's (count as unsupported a match total given as a count on a
  topic, and a returned document presented as the thing asked for), so the two
  sets of labels are not strictly comparable. The tool calls had been chosen
  under the old prompt: a model that had read the new rules might have
  searched differently. No AWS call, no call through Bedrock, and not the
  kit's default model.
- What the second pass found. The rewritten prompt did not fix the smaller
  model: Claude Haiku wrote 13 misleading answers of 30 in the first pass and
  12 of 30 in the second, Claude Sonnet 0 of 30 both times (its clean answers
  rose from 23 to 28). The check passed 9 of the 12 with no warning:
  relevance, attribution, "nothing else", comparison and requirement claims,
  none with an invented number. And the check, corrected on the first pass,
  warned 12 of the 39 clean answers and replaced 1; ten of the twelve warnings
  were wrong. Eight came from the count rule, on honest sentences that the new
  prompt asks for ("I left out the other 4 returned documents", "the other 6
  matches were not returned", "all three were published" with the total two
  sentences earlier, "five documents" in answer to "the five newest"). Two
  came from the number rule, which did not know the 10 that the block prints
  in "Documents returned (10)". In the 120 answers of both passes no document
  number, citation, URL, date or docket id was invented; the one slip, a
  dropped "C1-" prefix, was the same in both and was warned both times.
- What the second correction changed. The count rule: a stated count of
  documents is a warning in three cases only (the number returned given as all
  there are, a search total given as a count of documents, and more documents
  than every search matched), and every other comparison of a count is one
  `NOTE:` line; section 2 has the wording. The number rule: the counts the
  block prints in its headings, and two remainders code can work out again,
  are not unverified numbers. No rule was added for relevance, attribution,
  "nothing else" or comparison claims. The system prompt and the tools were
  not touched, so the second pass's answers are answers to this code's prompt.
- What the second correction did to the 120 answers. First pass: every answer
  ends as it did (clean 30 passed, 2 warned, 1 replaced; minor 11, 3, 0;
  misleading 6, 6, 1). Second pass: clean 26, 12, 1 before and 36, 2, 1 after;
  minor 8, 1, 0 before and 9, 0, 0 after; misleading 9, 2, 1 before and after,
  the same answers with the same warnings. The 2 clean answers still warned in
  each pass follow a lookup that failed, and the 1 replaced in each follows an
  empty search.
- What was not measured. Answers that this code has not seen: the second
  correction was made with the second pass in view, as the first was with the
  first. What that is worth is shown by the first correction: no wrong warning
  on the 33 clean answers it was tuned on, ten on the next 39. The kit's
  default model was not used at all. No model chose its own tool calls. The
  labels are readers' judgements, made under two sets of instructions. `NOTE:`
  lines were not judged: 9 of the 39 clean answers of the second pass carry
  one on this code.
- What round 3 opened. Six kinds of text that earlier code warned pass now;
  section 2 lists them. In the 60 runs below they are A02, A07, C06 and F14,
  and in the 79 runs N25.
- Acceptance runs for round 3, kept outside the kit, with scripted models,
  run after the first correction and again after the second:
  - the answer-check reviewer's 189 runs: unsupported text shown with no
    warning in 5 before round 3 and the same 5 after each correction; no run
    that was warned or replaced before passes now; of the 40 honest listings
    and the 5 clean controls in that set, none is warned, before or after;
  - the 79 runs of the round 2 correction: the same result run for run after
    the first correction. After the second, one run changed: "Two rules:
    2026-20311, and a Treasury rule on beneficial ownership reporting" was
    warned for its count and now passes with a note;
  - 60 further runs written for round 3 and labelled before they were run: 28
    with unsupported content that a changed rule is meant to see, all 28
    warned after the first correction (the earlier code warned 21; the 7 it
    passed gave a total as a count); 23 honest answers, none warned (the
    earlier code warned 12; on the first run of the first correction 1 was
    warned, a smaller count of documents the text named, and that rule was
    then narrowed); 1 honest answer after a failed lookup, warned in true
    words; and 8 labelled beforehand as passing, of which 6 passed and 2, a
    docket id called a document or given for the wrong document, were warned
    after a tightening made when the first run showed them. After the second
    correction 27 of the 28 are warned: "Three final rules are about lithium
    batteries. 2026-20944 is one of them" passes with a note. The other 59
    runs end as before.
- Changed in round 3 although the rehearsal's findings did not ask for it, so
  that you know. After the first pass: the year of a full date in a tool
  result counts as a returned number, and the year of a month and year alone
  does not (with it one of the 189 passed); a docket id counts only next to
  the document whose field holds it and is warned when called a document; the
  rule on a number returned being given as all there are no longer fires on a
  smaller count of documents the text names; the note on "the newest" (a
  warning in a first version, withdrawn because it fired on an honest scripted
  answer); the count of search words is given to the model in each search
  result as well as to the reader in the block; and the results template has
  four more rows. After the second pass: a count larger than every total and
  than the block stays a warning, although it fires on none of the 120 real
  answers, because without it one of the 189 runs ("Three final rules
  mentioning AI were published", with a third rule invented, after a search
  that matched two) would have passed; a count the question asked for is not
  excused when the sentence says "only" or "exactly"; a remainder of two or
  more digits is not an unverified number; the note on a count that equals a
  figure in the block is no longer said of the total of a search that returned
  fewer documents than matched; and section 6 and the results template ask for
  ten answers read by hand.

### From section 2: the rehearsal on real model text

> Corrected in round 4: the first of the three results below is C1 above.

Measured on text written by real models (two rehearsal passes, 2026-10-07,
round 3). The three results that matter most, worst first:

- The smaller of two stand-in models gave a misleading answer to 13 of 30
  questions. The system prompt was then rewritten against exactly those
  errors, and the same model gave a misleading answer to 12 of 30. The larger
  model gave none in 60 answers. Rewriting the prompt did not fix the smaller
  model.
- The check let 6 of those 13 and 9 of those 12 reach the reader with no
  warning.
- The check was corrected on the first pass's answers until none of their
  clean answers carried a wrong warning. On the 60 new answers of the second
  pass that same code put a wrong warning on 10 of the 39 a reader called
  clean. It had been tuned on one set of answers and misfired on the next.

What the two passes were. Two stand-in models, Claude Haiku and Claude Sonnet,
were each given the kit's own final-turn prompts for 30 questions and wrote 60
answers; that was done twice, 120 answers in all. They are not the kit's
default model (Amazon Nova Micro). They read each prompt as plain text, not
through Bedrock. The tool calls in each prompt were chosen by the agent that
prepared the rehearsal, not by the model, and the second pass used the first
pass's tool calls and stored Federal Register responses again. The first pass
was written under the system prompt as it was before round 3; the second under
the system prompt and the tool results of this code. Readers who saw the
answers and the tool results and not the kit's output labelled every answer
clean, minor or misleading, and the second pass had new readers. The second
pass's readers had two more lines in their instructions (count as unsupported
a match total given as a count on a topic, and a returned document presented
as the thing asked for), so the labels of the two passes are not strictly
comparable. The check was corrected after each pass. Below, "the first
correction" is the code as it stood between the two passes, and "this code" is
the code after the second correction.

What the stand-ins wrote, as the readers labelled it:

| Writer, 30 answers in each pass | First pass: clean / minor / misleading | Second pass: clean / minor / misleading |
|---|---|---|
| Claude Haiku | 10 / 7 / 13 | 11 / 7 / 12 |
| Claude Sonnet | 23 / 7 / 0 | 28 / 2 / 0 |

In the 120 answers, each written with the tool results in front of the model,
no document number, citation, URL, date or docket id was invented. The one
slip was the same in both passes: the smaller model dropped the "C1-" prefix
of a correction's number, and the check warned on it both times. The
misleading answers were of other kinds. In the first pass six of the 13 gave a
search total as a count of documents on a topic. Of the 12 in the second pass,
five present a returned document as the thing asked for or list documents on
other subjects as answers; three say that nothing, or nothing else, was
published when the search does not show that; one compares two search totals
as if they were counts of rules; one says what a rule requires when no
returned field shows it; one gives the number returned as the number that
matched; and one is the dropped prefix.

What the check made of the 60 answers of the first pass (each cell: passed /
warned / replaced):

| Reader's label | Before round 3 | After the first correction | This code |
|---|---|---|---|
| clean (33) | 23 / 9 / 1 | 30 / 2 / 1 | 30 / 2 / 1 |
| minor (14) | 12 / 2 / 0 | 11 / 3 / 0 | 11 / 3 / 0 |
| misleading (13) | 9 / 3 / 1 | 6 / 6 / 1 | 6 / 6 / 1 |

And of the 60 answers of the second pass, written under this code's prompt:

| Reader's label | After the first correction | This code |
|---|---|---|
| clean (39) | 26 / 12 / 1 | 36 / 2 / 1 |
| minor (9) | 8 / 1 / 0 | 9 / 0 / 0 |
| misleading (12) | 9 / 2 / 1 | 9 / 2 / 1 |

The misleading answers. On this code 6 of the 13 misleading answers of the
first pass and 9 of the 12 of the second still reach the reader with no
warning. First pass: five of the six present a returned document as what was
asked for, or list documents on other subjects as answers; the sixth gives two
search totals as counts in a wording the rule does not read. Two of the six
carry a `NOTE:` (below). Of the six that are warned, five gave a search total
as a count of documents and one dropped the prefix; the one replaced followed
an empty search. Second pass: the nine that pass are the relevance, "nothing
else", comparison and requirement claims listed above, and two of them carry a
`NOTE:` (one on "the most recent", one that the text names no document). The
two that are warned are "Ten documents matched the search", when 20 matched
and 10 were returned, and the dropped prefix; the one replaced followed the
empty search. The second correction changed none of this: every misleading
answer of both passes ends as it did before it. No rule was added for the
nine. The commonest real error, a search total or an off-topic document
presented as the answer, is one the check sees only in part.

The wrong warnings. Of the 12 clean answers of the second pass that the first
correction warned, ten were warned wrongly. Eight were the count rule
misreading honest sentences that the rewritten prompt asks a model to write:
five times a count of returned documents left out ("I left out the other 4
returned documents", after one of five was listed), once the matches that were
not returned ("the other 6 matches were not returned", of 11), and twice the
number returned read as all there are, where the total stood two sentences
earlier or the question had asked for "the five newest". Two called the 10 of
"none of the 10 returned documents" a number that appears in no tool result,
although the block itself says "Documents returned (10)". This code warns none
of the ten. The 2 clean answers still warned in each pass answer a question
that names a document number which does not exist: the lookup failed, and the
warnings say that. The 1 replaced in each pass followed a single empty search,
after which the kit always shows fixed text. One warning on a minor answer of
the first pass stays: "All three were published on 2026-10-02" in an answer
that never says the three are 3 of 3,131 matches. The reader marked the answer
down for that omission, so what the warning says is true, though the sentence
it quotes is not the one at fault.

> Corrected in round 4: the first two sentences of the next paragraph are C2
> above.

Read the columns headed "This code" for what they are. The second correction
was made with the second pass's answers in view, as the first was with the
first pass's, and no answers that this code has not seen have been put through
it. The first correction shows what such a figure is worth: no wrong warning
on the 33 clean answers it was tuned on, ten on the next 39. Expect wrong
warnings on your own run, and count them (section 6). `NOTE:` lines were not
judged by any reader: on this code 4 of the 33 clean answers of the first pass
and 9 of the 39 of the second carry one.

> Corrected in round 4: the next paragraph, from "And in this rehearsal" to
> its end, is C3 above.

What this means if you run the kit. The block built by code is the supported
part of every answer. A pass on the model's text means that its document
numbers, citations, other numbers, dates, URLs and quoted phrases were found
in the tool results. It does not mean that a document it lists is about what
you asked, that "the newest" is the newest of its kind, or that nothing else
exists. And in this rehearsal the choice of model mattered more than the
prompt or the check: the smaller model misled in 25 of its 60 answers and the
larger in none of its 60, the rewritten prompt moved the smaller model from 13
to 12, and the check warned or replaced 7 of the 13 and 3 of the 12. Neither
stand-in is the kit's default model, which has not been tried.

The kit itself has still never called a model. The default model has seen
neither the prompt nor the tools through Bedrock, and no model chose its own
searches in either pass, so how the default model chooses its searches, how it
words its answers, and how often it makes these errors is not known.

### From section 2: what round 3 gave up to remove false warnings

What round 3 gave up to remove false warnings. Six kinds of text that earlier
code warned now pass. The first three were given up after the first pass, the
last three after the second:

- an invented document with no number and no quotation marks, listed beside
  real ones under a count that is right ("Two final rules: 2026-19964, and an
  Energy Department rule on grid storage"). It draws a note now. The
  comparison behind the old warning also fired on "the 10 newest matches" in
  an honest answer;
- the first or the last day of the model's own search, used about something
  else ("takes effect on 2026-09-01"). The old rule warned honest answers that
  restated the dates of a search the model had chosen;
- an invented claim with no digits, in an answer that names no document and
  gives a search total in the right words. It draws a note now. The old
  warning fired on honest answers to "how many";
- a count that equals no figure in the block and that the text does not back
  by naming that many documents: "Three final rules are about lithium
  batteries. 2026-20944 is one of them", or "Two rules: 2026-20311, and a
  Treasury rule on beneficial ownership reporting", where the second rule is
  invented. Each draws a note now. The comparison behind the old warning fired
  on five honest answers of the second pass ("I left out the other 4 returned
  documents");
- the number returned in a sentence that reads as all there are, when your
  question asked for that many and the sentence has no "only" or "exactly"
  ("The SEC published five notices on tariffs" in answer to "give me the five
  newest"), or when a larger total stands elsewhere in the same paragraph and
  not in the same sentence;
- an invented number that happens to equal a count the block prints in a
  heading (the number of documents returned, for one) or one of the two
  remainders above.

## Round 2

### From section 8

Reviewed independently a second time on 2026-10-07 (round 2): 27 findings for
this kit, 26 fixed, 1 left open (listed below).

- Left open after round 2: finding F1 of the answer-check review, in part.
  The finding was that one real document number in an answer switched the
  check off for everything that had no number. Every answer now starts with
  a block built by code, and the numbers, dates, URLs, counts and quoted
  phrases in the model's text are compared whether or not a real number is
  cited. What remains: a claim with no digits and no quotation marks still
  reaches the reader with no warning, under a label that says the model's
  wording is not checked. In the reviewer's own scripted runs that was 91 of
  189 on the reviewed code and is 5 of 189 on this code: a wrong agency, a
  wrong document type, two numbers swapped, "no other agency has issued any
  such rule", and one sentence copied from a returned abstract. Section 2
  lists the kinds. Rules without a model cannot close this. The rehearsal
  on real model text (above) showed how much of it matters in practice: in
  those 120 answers no identifier was invented, and the errors were of this
  kind.
- The 27 findings were 7 blockers, 3 majors and 17 minors, from three
  reviewers: 14 on the answer check, 6 on the numbers, 7 on money and
  teardown. Each has at least one test that fails on the reviewed code and
  passes on this code; they are in `test_r2_answer_check.py`,
  `test_r2_usage.py` and `test_r2_money.py`. Run against the reviewed code,
  225 of the 307 tests in those three files fail; the other 82 pin behaviour
  that was already right.
- Answer check. F1: the block built by code, the label, and checks that no
  longer depend on a real number being cited (left open in part, above). F2:
  an invented citation in 21 written forms. F3: an invented document number
  in 83 spellings, the reviewer's and five more; text is normalised before
  anything is compared. F4:
  other invented identifiers; numbers of two or more digits, number groups,
  CFR references and URLs are compared. F5: a number counts as returned only
  from a `document_number` or `citation` field; one that only occurs inside
  a returned text gets its own warning; a cut field is no source; a lookup
  answered with an empty object is an error. F6: a search response without
  the expected fields is an error, not "nothing found". Minors: CFR parts
  and docket ids are no longer cut silently; a cut text is marked; a total
  equal to 10,000 is reported as the API's figure with a note; an unknown
  tool argument is refused by name; the no-results text speaks of the
  searches and shows them; a long answer ends with the warning again; model
  text is kept out of spans by `TRACELOOP_TRACE_CONTENT=false`; the hosted
  script flags a replaced answer.
- Numbers. Blocker: `60_read_usage.py` said `CROSS-CHECKED` on partial data;
  an early read is now a reason, and records without elapsed time, or with
  running-total elapsed time, count as partial. Major: four rows of the
  results template asked for a time no script printed; the scripts now print
  them. Minors: the price for a `global.` inference profile; the rates line
  says when the platform version was assumed; a call after a failed call is
  no longer listed as "same question again"; the tolerance is 10% and a gap
  above 2% is given as a range.
- Money and teardown. Blocker: with the state file lost, damaged or older, a
  teardown in the wrong Region deleted the bucket and the role of a live
  runtime in another Region, and the clean check said `CLEAN`; section 5
  gives the rules that replace that. Major: teardown never finished when
  `GetAgentRuntime` reported a missing runtime with an unfamiliar error
  code; the list call now decides. Minors: teardown exits 1 when a listing
  shows something of the kit that it did not delete, and waits until a
  gateway is gone; a teardown dry run exits 3; a denied X-Ray call no longer
  decides the clean check's verdict; a versioned bucket is emptied; the
  RESULT line says in plain words when no state file was found.
- Changed although no review asked for it, so that you know: numbers are
  compared from two digits up, not from four as the review proposed; URLs,
  phrases in quotation marks, "the last N days" and counts of CFR parts are
  compared; a search result keeps 1,500 characters of an abstract, not 400,
  which costs input tokens (section 2); records must
  cover 90% of each session, not 80%; `--tolerance-percent`; the role guard
  also reads the role's trust policy; a teardown with no record of a deploy
  exits 1 when the tag listing cannot be read; the gateway teardown's dry
  run exits 3.
- Acceptance runs for round 2. These are scripts kept outside the kit, run
  with scripted models and a fake AWS; they are not part of `tests/`.
  - The answer-check reviewer's 189 scripted runs: unsupported text shown
    with no warning in 91 before and 5 after (above). Of the 40 honest
    listings of real records and the 5 clean controls in that set, none was
    warned.
  - 79 further runs written and labelled before they were run: 32 with an
    unsupported number, date, URL, count or period, of which 31 were warned
    and 1 stopped being unsupported when the abstract limit was raised; 8
    where nothing supported the text, all replaced or stopped; 23 honest
    answers, none warned; 2 after a failed tool call and 3 true answers in
    a form the tool did not return, all 5 warned as expected; and 11 of the
    kinds section 2 lists, of which 8 passed with no warning and 3 were
    warned.
  - The numbers reviewer's four inputs that had ended `CROSS-CHECKED` on
    partial data now end `NOT CROSS-CHECKED` with exit code 1.
  - The money reviewer's kit C sequences, C00 to C25, and seven further
    ones: after 163 teardown and clean-check steps there was no step that
    exited 0 or printed `CLEAN` while something of the kit remained, except
    the gateway-only teardown, which exits 0 with the runtime still there
    because the runtime is not its job (the clean check then says
    `NOT CLEAN`).

### From section 2: the scripted runs

Measured with scripted answers and no model: the second review ran 189, and 91
of them reached the reader with an unsupported claim and no warning. On this
code the same 189 leave 5, as they did before round 3, and 79 further runs
written for the round 2 correction leave 9. It was 8 until the second pass:
the ninth, "Two rules: 2026-20311, and a Treasury rule on beneficial ownership
reporting", is a count that the text does not back, and such a count draws a
note now. All 14 are of the kinds listed above. One of the 5 repeats a
sentence, date included, that was planted in a returned abstract; the date is
in the tool result, so no rule here can see it. Section 8 has 60 more runs
written for round 3.

## Round 1

### From section 8

Reviewed independently on 2026-10-07 (round 1): 27 findings, 27 fixed, 0 left
open (listed below).

- The 27 findings were 4 blockers, 5 majors and 18 minors. Each blocker and
  major has a test that failed on the reviewed code and passes on this
  code.
- Left open: none at the time. Round 2 reopened four of them: blocker 1
  (invented documents reached the reader), blockers 3 and 4 (usage read too
  early, and a cross-check that failed open) and major 2 (a damaged state
  file); see above. Fixed only as far as code and tests without AWS can
  show, and therefore still in the UNVERIFIED
  list below: the portable start lines in `bin/` (major 3), the explicit
  listen address (minor 3), and the execution role's access to the zip
  (minor 17).
- Blockers: 1 invented documents reached the reader; 2 token prices were
  taken per 1,000 against a page that prices per 1M; 3 usage was read too
  early; 4 the cross-check on the session cost failed open.
- Majors: 1 teardown and the clean check trusted the current Region and
  prefix over the state file; 2 a damaged state file stopped teardown; 3 the
  zip kept the build machine's Python path; 4 the latency figures were
  mislabelled; 5 section 7 overstated what a run amounts to.
- Minors, by the reviewer's numbers: 1 and 2 pricing sentences; 3 and 15
  listen address; 4 V2 rates when the version is not echoed; 5 tokens after a
  stop at the step limit; 6 tool calls per turn; 7 the reason behind an HTTP
  400; 8 date ranges computed in code; 9 a stop that fails; 10 a refused
  runtime delete; 11 re-running step 8; 12 two wrong messages in the
  preflight; 13 the fixture recorder; 14 where spans are counted; 16 sign-in
  commands; 17 the role and the zip; 18 the lock files.

## Before the reviews

### From section 8: how the sources were read, and corrections to the research notes

How the sources were read. For the two corrections these were read as raw
text or raw HTML on 2026-10-07, and quotations from them are exact: the
AgentCore pricing page, the Bedrock pricing page and its price file, the AWS
Price List files for Amazon Bedrock in us-east-1, us-east-2 and us-west-2
(second correction), and the documentation pages for runtime metrics and
usage logs, configuring observability, direct code deployment, runtime
permissions, lifecycle settings, the HTTP contract, quotas, and AWS CLI
sign-in. The other AWS pages
were read when the kit was first written through a tool that returns an
extract of each page, so a quotation from one of those is as that tool
reported it; the reviewer checked 43 points against raw text and found 6
contradicted, all corrected here. The request shapes do not depend on either,
because they are checked against the SDK's own definitions. Where an API page
was read only to confirm that an operation exists and what it requires, the
behaviour described on it is still untested.

Corrections to the research notes this kit started from (section 9 has the
sources):

- The notes said Runtime hosts code "in a container". Current documentation
  gives two artifact types: a container image in ECR, or a zip in S3 ("direct
  code deployment"). Both need arm64. This kit uses the zip.
- The notes named the starter toolkit and `configure / launch / invoke /
  destroy`. Those are the old toolkit's commands, and its README now says it
  is no longer supported. The documented CLI today is `@aws/agentcore` with
  `create / dev / deploy / invoke / status`, and removal is
  `agentcore remove all` followed by `agentcore deploy`.
- The notes gave V2 prices only. The default platform version is V1, at
  different rates. Both are in section 2.
- Confirmed as the notes had it: `BedrockAgentCoreApp`, `@app.entrypoint`,
  port 8080, `/invocations`, `/ping`, arm64; Gateway turns an OpenAPI
  description into MCP tools; Observability stores logs, spans and metrics in
  CloudWatch; Bedrock Agents Classic closed to new customers on 30 July 2026;
  the samples repository is `awslabs/agentcore-samples`.

## Reference text that left the README when it was shortened

### Above section 1 and in section 1: lines and paragraphs that were reworded

README line 24:

```
| `agent/fr_tools.py` | the two tools as plain functions: validation, timeouts, a User-Agent, small result caps, "the last N days" worked out in code, a mark on every field that was cut short, an error when a response lacks the fields it should have, a fixed sentence in every search result that its total counts matches of the search words, and for each result a count of how many of the search words stand in its title and its abstract |
```

README line 42:

```
| `tests/` | 970 offline tests and four recorded Federal Register responses |
```

README lines 52 to 55:

```
One difference from that sample: it starts the agent as plain `agent.py`.
This kit's default start command is `opentelemetry-instrument agentcore_app.py`,
which is the example on AWS's direct code deployment page and is what makes
traces exist. Section 2 says what can go wrong with it and what the fallback is.
```

README lines 57 to 67:

```
The other documented route, not used here: the AgentCore CLI
(`npm install -g @aws/agentcore`, Node.js 20 or later; `agentcore create`,
`agentcore dev`, `agentcore deploy`, `agentcore invoke`, `agentcore status`,
`agentcore logs`, `agentcore traces`, `agentcore remove all`). It deploys
through AWS CDK and CloudFormation, so it also needs the CDK bootstrap stack
(`CDKToolkit`, with roles for deploying, for publishing code to S3 and for
publishing images to ECR), a CloudFormation stack per project and, for
container builds, ECR and CodeBuild. That is more to find and delete than
this kit wants. The older Python "starter toolkit"
(`bedrock-agentcore-starter-toolkit`, with `agentcore configure`, `launch`,
`invoke`, `destroy`) is marked "no longer supported" in its own README.
```

### Section 2: how it opened

**Nothing in this kit has been run against AWS.** It was written, and then
corrected after three rounds of independent review and two rehearsal passes of
its answer check on text written by real models, without an AWS account. The
agent, the tools, the graph, the local HTTP server and the packaging step were
built and run for real. Every AWS call was written from AWS documentation,
AWS's sample code and the request and response definitions inside the AWS SDK.
Section 8 lists exactly what ran, what did not, and which details could not be
confirmed. Expect to fix something on first contact.

### Section 2: what passes with no warning

**A model can invent things, and it can present real things as what they are
not. The kit's check sees the first when it comes with a number, a date, a
URL or quotation marks, and sees little of the second.**
Bad news first. All of these pass with no warning:

- a returned document presented as the thing you asked for when its own title
  and abstract say otherwise: "the newest NHTSA final rule on federal motor
  vehicle safety standards" for a rule about fuel economy, security zones
  listed as safety zones, a "Presidential Document" called the most recent
  executive order, a request for information called "the latest proposed
  rule". On text written by real models this was the commonest misleading
  claim in both rehearsal passes (measured below). No rule here checks it;
- a claim that nothing else exists, or a comparison, drawn from part of what
  matched: "only the Interior Department's Fish and Wildlife Service published
  a final rule clearly about endangered species" when 10 of 14 matches were
  returned, "the FAA published more airworthiness directive final rules in the
  last 30 days than in the 30 days before that" from two search totals. Both
  are from the second pass. No rule here checks these either;
- a search total given as a count of documents on a topic, in any wording the
  rule on totals does not read. It reads "31 proposed rules"; it does not read
  "proposed rules number 16 total (5 returned)";
- a count of documents that no figure in the block supports, unless it is
  larger than every total: "Three final rules are about lithium batteries.
  2026-20944 is one of them." Since the second pass it draws a `NOTE:` and not
  a warning (below);
- a claim with no digits in it: a wrong agency, a wrong document type, "this
  rule bans X", "nothing else was published", or a whole invented rule
  described without a number and without quotation marks around its name;
- a real document number attached to the wrong document, for example two
  returned numbers with their descriptions swapped;
- a single digit standing alone, such as "5 percent" or "3 hours"; a number
  written as words; a two-digit ordinal ("the 83rd"); two digits that follow
  letters ("FY27", "COVID-19"); a site named without a path ("regulations.gov");
- a number or a date that does occur somewhere in a tool result, used about
  something else. Since round 3 that includes the first and the last day of
  a search the model itself sent;
- a claim the model copied from a returned title or abstract. That text comes
  from a public API, the model reads it, and it can steer the model;
- a search that does not match your question. The model writes the search.

### Section 2: what a kept answer is made of

What the kit does. The model's text is never shown as the answer by itself. A
kept answer has these parts, in this order:

1. A block built by code, headed `FROM THE FEDERAL REGISTER API`. The model
   writes none of it. It lists each search as it was sent (the term, the
   type, the dates and whether the tool or the model chose them, the limit)
   and the total the API reported. Under each total stands a fixed sentence:
   the total counts documents that match the search words, not documents
   about the topic, and the documents listed were not checked for relevance.
   Then comes each document a tool returned: document number, type,
   publication date, agencies, title and URL, copied from the API's fields.
   A document that a search returned also has a line that starts
   `Search words`: how many of the search's words stand in its title and in
   its abstract, and which do not. That line is arithmetic, not a judgement.
   The words are those of the search term other than a, about, an, and, as,
   at, by, for, from, in, of, on, or, the, to, with; a word counts when it
   stands there as a whole word, ignoring upper and lower case and a final
   s. A
   document on your topic can show 0 and one on another subject can show
   all of them: in the rehearsal a state air plan approval showed 1 of 4 in
   its abstract and an emissions rule on another subject showed 2 of 4. A
   total of exactly 10,000 carries a note that it looks like a ceiling and
   not a count. A field the tool had to cut short ends in `[TRUNCATED]`.
   Above 30 documents the rest are counted on one line, not listed. This
   block is the supported part of the answer.
2. Lines starting `WARNING:`, one for each check on the model's text that
   failed, each listing what was not found.
3. Lines starting `NOTE:`. A note is information, not a failed check, and an
   answer with notes and no warning counts as passed. There are five. The text
   names no document but gives a search count in words that say so. The text
   names no document and the block holds only one. A count in
   the text was compared with the figures in the block and is not one of the
   three count warnings below: it equals no total, no number a search returned
   and not the number of documents listed, or it equals one of those and the
   text names fewer documents by number than that; the line says it is
   information, not a finding. A string with the form of a document number is
   a docket id from a returned `docket_ids` field. The text calls one document
   "the newest", "the most recent" or "the latest" and neither the title nor
   the abstract of that document holds one word of the search that returned
   it.
4. The model's text, under a fixed label that begins `MODEL'S SUMMARY` and
   says what was and was not compared.

When all of that is longer than 24 lines the warnings are repeated as the
last line, so they are on screen where the output stops. After a search the
block alone is usually that long.

### Section 2: what is compared in the model's text, rule by rule

What is compared in the model's text, after dashes, digits of other scripts,
HTML entities, URL escapes, invisible characters and markup are normalised:

- document numbers, only against the `document_number` fields the tools
  returned, and "NN FR NNNN" citations, only against the `citation` fields. A
  number that occurs only inside a returned title or abstract gets its own
  warning: mentioned inside a returned document, not returned as one. A
  number your question names that no tool returned gets a warning that says
  so and says whether its lookup failed; it is not called invented. A docket
  id with the form of a document number (an SEC release number such as
  33-11438) gets a note when it comes from the `docket_ids` field of a
  document the text names, and a warning when the text calls it a document
  or does not name that document;
- every other number of two or more digits, and every group of numbers
  joined by a hyphen, a dot, a slash or a colon, against the complete fields
  of the successful tool results, your question and the current year; the
  year of a full date in a tool result counts as well, and so do the counts
  the block prints in its own headings ("Documents returned (10)"). A
  two-digit number is read by itself, with a unit joined to it ("a 60-day
  period", "$83M") and after a label ("No.83"), not as an ordinal or after
  letters. Two numbers joined by one hyphen ("parts 70-71") are compared one
  by one. The numbering of a list or of a table is not compared;
- every "NN CFR part NN" reference in one line of the model's text, against
  the CFR references the tools returned;
- every date, against the dates in the tool results, the first and the last
  day of each search as it was sent, today, and the dates in your question
  in the common written forms ("September 1, 2026", "Sept. 1", "9/1/2026",
  "1 September 2026", "2026/09/01", "September 1-30, 2026"). A day and month
  with no year in your question take the year your question names, or the
  current year when it names none;
- every URL, against the URL fields the tools returned, also when it is
  written without "https://" and has a path;
- a stated count of documents, against the number each search returned, the
  totals the API reported and the number of documents in the block. Code knows
  those figures and not which documents a count is about, so a count draws a
  warning in three cases only. One: the number returned given as all there
  are, when a search returned fewer documents than matched ("Only five final
  rules were published", "Ten documents matched the search" when 20 did). Not
  when the sentence says it is a part, a sample or a remainder (newest, most
  recent, latest, first, top, shown, returned, listed, "was given", these,
  those, among, other, remaining, rest, "left out", "of the 5", "of them",
  "here are", following and the like), not when a larger total stands in the
  same paragraph or, as a count of matches, in an earlier one, and not when
  your question asked for that many, unless the sentence says "only",
  "exactly" or the like. When the sentence's own verb says the count matched
  ("Ten documents matched the search for X among Y"), such a word excuses it
  only within three words of the count; a heading such as "the following 10
  final rules:" still passes. Two: a count that equals the total of a search
  which returned fewer documents than matched, in a sentence with none of the
  words match, search, results, hits, returned, API, mention or contain in
  their common forms, unless an earlier sentence of the paragraph gave that
  total with one of them. The warning says the total is a count of search
  matches. Three: more documents than every search of the run matched and than
  the block holds ("Seven final rules were published" after a search that
  matched two). Only a phrase that reads as a count of documents is seen ("31
  proposed rules", "27 were published");
- every other count: a `NOTE:` at most. A count that equals no figure in the
  block gets one, and so does a count that equals a figure in the block when
  the text names fewer documents by number. No line at all for a count no
  larger than the number of documents the text names, or for a remainder code
  can work out again in a sentence that says it is one ("the other 4 returned
  documents" after one of five was named; "the other 6 matches were not
  returned" of 11). Until the second pass a count that equalled no figure was
  a warning; it warned six honest answers of 39;
- a stated count of CFR parts, against the list the lookup returned;
- "the last N days", which stands only when a search in this run had its
  dates computed by the tool from that N;
- a phrase of two or more words in quotation marks, against the words of the
  tool results, your question and the search terms. Quotation marks claim
  "word for word", so an invented or reworded title in them gets a warning.
  The same title without quotation marks does not. Every string of a tool
  result may be quoted, and a phrase with "..." is compared piece by piece;
- a line of the model's text that starts like the kit's own (`WARNING:`,
  `NOTE:`, the heading of the block) is shown with "[written by the model,
  not by the kit]" in front, and a copy of the block's heading draws a warning.

> Corrected in round 5 (`REVIEW_NOTES_r5.md`): in the list above, a docket id
> ("FAA-2025-0491": letters and a hyphen, then a year) is compared whole, not
> one number at a time; "were matched by" counts as the sentence's own verb;
> "among", when it is a sentence's only such word, excuses a count only within
> three words of it; a total said before excuses a restatement only when the
> restatement refers back to it ("all 31", "the 31"); the pieces of a
> quotation with "..." must stand in order inside one string of a tool result;
> a curly apostrophe, a no-break or a zero-width space no longer hides a line
> shaped like the kit's; and terminal control characters in the model's text
> are replaced by spaces before it is checked or shown.

A field marked `[TRUNCATED]` never counts as a source for numbers, dates or
references; the words that are shown of it may be quoted.

### Section 2: what a warning means, and warnings on honest text (with figures of rounds 2 and 3)

A warning means "not found in the tool results of this run". It does not mean
"false", and no warning does not mean "true". Warnings fire on honest text
too. Of the 72 real answers that readers called clean in the two passes (33
and 39), this code warns 4, all for a lookup that did fail. That figure is for
answers the rules were corrected on: the code before this correction warned 12
of the 39, ten of them wrongly, and the code before round 3 warned 9 of the
33. In the scripted runs for the round 2 correction 0 of 160 listings of real
records in four plain layouts and 0 of 23 other honest answers were warned,
and that is still so, but 6 of 40 listings that copied whole abstracts were,
because an abstract named another document's citation or an OMB control
number. A seventh, whose abstract counted "eight notices", was warned until
the second pass and draws a note now. The short link
`federalregister.gov/d/<number>` is warned too; it is real but is not the URL
the tool returned. So is a number the model worked out itself, such as a sum,
and a number taken from the part that is shown of a cut field. Two remainders
are not warned, because code can work them out again from the block: the
matches of a search less the documents it returned, and the documents returned
less the documents the text names.

### Section 2: when the model's text is replaced, and what is stored where

The model's text is replaced by fixed text, and none of it is shown, when no
tool result supports anything: no tool was called; every search came back
empty and no document was fetched; every lookup failed (the text says what
failed); or the run stopped at the step limit. A search response without the
fields the tool expects is a failure, not "nothing found", and a tool call
with an argument the tool does not have is refused by name and not run.

Open each URL in the block before you rely on an answer, and read the title
of every document the model calls the newest or lists as an answer.
`50_invoke_hosted.py` prints the warnings before any text, stores the lists
the runtime reports, counts every warned or replaced call as flagged, and
then exits 1. A call with notes and no warning is not flagged.

What is stored where. The hosted entrypoint returns the block, the warnings,
the notes and the model's text as separate fields and as one text. With application
logs on, that response is stored in CloudWatch (see the last billing trap
below). Traces: the LangChain instrumentor records prompts and model output
in span attributes unless `TRACELOOP_TRACE_CONTENT` is `false`; that output
includes text the check withholds. `30_deploy.py` sets the variable to
`false` on the runtime and `agentcore_app.py` sets it again at start. This
was read in the instrumentor's source (version 0.62.4). What the spans hold
on AgentCore with it set was not seen, and the other instrumentations that
the AWS distribution switches on were not read.

### Section 2: billing traps

**Billing traps**

- An idle session still bills. The pricing page says you pay "during your
  session, which spans from microVM ready, initialization, active processing,
  idle periods, until session termination". CPU is not charged while the
  agent waits on the model or a tool, but memory is. The service default is 15
  minutes idle before a session ends, and 8 hours maximum life. This kit sets
  120 seconds and 900 seconds on the runtime, and `50_invoke_hosted.py` calls
  `StopRuntimeSession` on every session it opens, including after an error.
- Runtime prices, read 2026-10-07 from the raw page
  https://aws.amazon.com/bedrock/agentcore/pricing/ . The page's pricing
  table gives one Runtime price with no Region column and does not say which
  Regions it covers:
  - platform version V1, which is what you get by default: $0.0895 per
    vCPU-hour and $0.00945 per GB-hour;
  - platform version V2, consumption: $0.1276 per vCPU-hour and $0.0169 per
    GB-hour, and idle memory is reclaimed after 120 seconds;
  - billed per second on actual use, 1 second minimum, 128 MB memory minimum;
  - "Billing includes system overhead in addition to your application's
    resource usage", so a session bills somewhat more than your code uses;
  - "Network data transfer charges apply at standard EC2 rates";
  - AWS's own worked example on that page: a 10-minute session with 60
    seconds of active CPU comes to $0.006703 at V2 rates. This kit's sessions
    are far shorter.
- A deployed runtime with no session is not free. The same page: "direct code
  deployment bills for the size of the code artifacts you deployed at S3
  Standard rates", with the example "for a 100MB agent, this adds up to
  $0.0023/month". By that example this kit's 54 MB zip is about $0.0012 a
  month, and the copy in your own bucket bills at S3 rates as well. Fractions
  of a cent, but it runs until you tear down. Not checked against a bill.
- What a session costs if it is never stopped (a failed stop, a hard kill).
  Arithmetic on the list rates above and on the documented ceiling of 2 vCPU
  and 8 GB per session (quotas page, read 2026-10-07):
  - at this kit's settings (idle 120 s, lifetime 900 s): a session that only
    sits idle at an assumed 0.5 GB ends after 120 seconds and costs
    120 / 3600 x 0.5 x $0.00945 = $0.00016 on V1 ($0.00028 on V2). A session
    that stays busy at the ceiling for its whole life costs at most
    900 / 3600 x (2 x $0.0895 + 8 x $0.00945) = $0.064 on V1, and
    900 / 3600 x (2 x $0.1276 + 8 x $0.0169) = $0.098 on V2;
  - at the service defaults (idle 900 s, lifetime 28,800 s), which is what a
    runtime gets if no lifecycle setting is passed: idle
    900 / 3600 x 0.5 x $0.00945 = $0.0012 on V1, and a ceiling of
    8 x (2 x $0.0895 + 8 x $0.00945) = $2.04 on V1 or
    8 x (2 x $0.1276 + 8 x $0.0169) = $3.12 on V2, per session.
  `30_deploy.py` and `50_invoke_hosted.py` print the first pair before they
  act. The 0.5 GB is an assumption, not a measurement.
- Model tokens are a separate charge on the Bedrock bill, for local runs and
  for hosted runs alike. Prices are per 1,000,000 (1M) tokens. Read 2026-10-07
  from the price file behind https://aws.amazon.com/bedrock/pricing/ , which
  is
  https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/bedrock/USD/current/bedrock.json
  (published 2026-10-06), matched to the page's table "Geo Cross-region
  inference and in-region", Standard tier, columns "Price per 1M input
  tokens" and "Price per 1M output tokens", for us-east-1, us-east-2 and
  us-west-2:
  - Amazon Nova Micro, the default: $0.035 per 1M input tokens and $0.14 per
    1M output tokens;
  - Amazon Nova 2 Lite, the suggested alternative: $0.33 per 1M input tokens
    and $2.75 per 1M output tokens.
  Those are the prices for a plain model id or a `us.` inference profile. A
  `global.` inference profile has its own price: for Nova 2 Lite $0.30 per 1M
  input tokens and $2.50 per 1M output tokens, read the same day from the AWS
  Price List file
  https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/current/us-east-1/index.json
  (published 2026-10-06; rows `Nova2.0Lite-input-tokens-cross-region-global`
  and `Nova2.0Lite-output-tokens-cross-region-global`, priced per 1K tokens).
  That file has no global row for Nova Micro, so the kit holds no price for a
  `global.` Nova Micro id: `60_read_usage.py` then computes no token cost
  and asks for the two prices.
  For any other model, profile or Region, look the price up on that page. An estimate
  for the default run, by arithmetic and not by measurement (no model was
  ever called; four characters per token is assumed): one question with one
  search is about 3,500 input and 450 output tokens, about $0.0002 on Nova
  Micro, so the ten hosted calls are about $0.002. If every question ran to
  the step limit with the longest results the tools allow (12 searches of 10
  documents at about 3,000 characters each, sent again on every later model
  turn, about 230,000 input tokens in all) the bound is about $0.008 a
  question. Nova 2 Lite is roughly ten to twenty times that.
- CloudWatch: "Spans, logs, and metrics" are "Charged as per Amazon CloudWatch
  pricing" (AgentCore pricing page, read 2026-10-07). CloudWatch's own rates
  are not quoted here. The kit sets 7-day retention on the two log groups it
  creates and teardown deletes them.
- S3's own rate table is not quoted here; see the storage line above.
- AWS Free Tier: the offers list on https://aws.amazon.com/free/ marks Amazon
  Bedrock AgentCore "Paid plan exclusive" (read 2026-10-07). An account on the
  Free plan cannot run the hosted half. Moving to the Paid plan is your
  decision and is outside this kit.
- CloudWatch Transaction Search, needed only to view traces, is an
  account-wide switch. Once on, it stays on after teardown and changes how all
  X-Ray spans in the account are ingested and billed ("cost effective
  collection mode using Amazon CloudWatch Pricing"). This kit never turns it
  on or off.
- `APPLICATION_LOGS` records contain `request_payload` and `response_payload`,
  so your questions and the answers are stored in CloudWatch. Use
  `--no-app-logs` in step 8 to skip them.
- The optional gateway step: $0.005 per 1,000 API invocations, $0.025 per
  1,000 search calls, $0.02 per 100 tools indexed per month (same page, same
  date).

### Section 2: usage data

**Usage data is late, and its shape is not documented**

- AWS: "Resource usage data may be delayed by up to 60 minutes and precision
  might differ across metrics." A read taken a few minutes after the sessions
  can hold half the records in the logs and half in the metrics, and the two
  halves agree with each other. So `60_read_usage.py` treats an early read as
  a reason, not as a footnote: before 60 minutes have passed since the last
  session ended, its last line is `RESULT: NOT CROSS-CHECKED` and it exits 1,
  whatever the numbers say. Every run prints the time of the read in UTC and
  the minutes since the last session, and an early run prints the earliest
  time a read can be final.
- If you cannot wait, `--accept-early-read` lets an early read end
  `CROSS-CHECKED` when everything else holds. The RESULT line then says "read
  early at the owner's request, NOT final" with the minutes that had passed,
  and teardown repeats that warning. Do not quote such a figure as final.
- AWS does not say whether one usage record is an increment (add them up) or
  a running total (take the largest). In the first review's worked example,
  summing running totals put a 60-second session about 48 times too high.
  `60_read_usage.py` therefore prints both readings for every session and
  labels a cost `CROSS-CHECKED` only when all of this holds: the read is not
  early; there are usage records for every session, they say how much time
  they cover, and that is at least 90% of each session's wall-clock time; the
  CloudWatch metrics have data; and one reading agrees with the metric total
  within 10%, for vCPU-hours and for GB-hours. Records that carry no elapsed
  time count as partial. Otherwise its last line says `NOT CROSS-CHECKED, do
  not quote a session cost from this run` and it exits 1.
- The 90% and the 10% are this kit's choices, not AWS's. The RESULT line
  states how far apart the two sources are, and when that is more than 2% it
  gives both figures as a range and says to quote the range, not the lower
  figure alone. `--tolerance-percent` (1 to 50) changes the 10% and is echoed
  in the RESULT line.
- The cross-check compares hours, not dollars. It cannot catch the wrong
  platform version, and V2 rates are 43% higher for CPU and 79% higher for
  memory. Every rates line says whether the version is the one the service
  reported or is ASSUMED, and in the second case the RESULT line also gives
  the cost at the other version's rates.
- Teardown deletes the log group that holds the usage records. Do not tear
  down until you have a `CROSS-CHECKED` result written down. An idle runtime
  costs a fraction of a cent a month while you wait.

### Section 2: quotas

**Quotas.** None needs a request. Defaults read 2026-10-07 (source 12): 1,000
agents per account, 5,000 active sessions in US East (N. Virginia) and US West
(Oregon) and 2,500 elsewhere, 2 vCPU and 8 GB at most per session, a 15-minute
request timeout, a 100 MB payload limit, and a direct-deployment zip of at
most 250 MB zipped and 750 MB unzipped. Idle timeout and maximum lifetime for
a microVM runtime: 60 to 28,800 seconds.

### Section 2: things that can go wrong

> Round 4: the list below says "at most 15 requests per question". A round 4
> test rig measured 18 (its builder's report). The code and its comment were
> not changed; README section 8 says so.
> Later on 7 Oct 2026, the review measured 18 with the
> kit's own graph and a fake model, added a test, and corrected the comment.

**Things that can go wrong**

- The wrong Region in your shell. Settings come from the environment first
  and `config.env` second, so an exported AWS_REGION overrides config.env.
  `30_deploy.py` writes the Region, the name prefix and the account id of the
  deploy into `.state.json` (a local, git-ignored file), and every script that
  reads that file compares all three with the settings and the sign-in in use.
  On any mismatch it prints `STOPPED`, names both values, does nothing and
  ends with exit code 4. Account ids are only ever printed as their last four
  digits.
- A `.state.json` that cannot be read, or that names resources without saying
  which Region, prefix and account they are in, stops every script the same
  way (exit code 4). The kit never moves, renames, deletes or rewrites such a
  file: it may be the only record of where a runtime is billing. Section 5
  says how to tear down anyway.
- A lost `.state.json`. Teardown and the clean check then work by name in the
  Region and under the prefix in use, and only there. Both say so in their
  last lines. If the deploy was in another Region, nothing there is touched
  and nothing there is checked.
- Two accounts in one `.state.json` history. The clean check can only look
  into the account you are signed in to, so it stays `RESULT: INCOMPLETE`
  for as long as the file names the other account. That is permanent until
  you check the other account yourself and remove the file.
- Model access. Bedrock enables most models on first use if your principal has
  the AWS Marketplace permissions `aws-marketplace:Subscribe`, `Unsubscribe`
  and `ViewSubscriptions`. Anthropic models first need a one-time use-case
  form per account. The default here is an Amazon model, so no form.
- The default model, Amazon Nova Micro, was chosen because its model card
  confirms tool use and it is the smallest Amazon text model. Whether it fills
  in the search tool's arguments well was not tested, nor whether it accepts
  the tool's optional arguments as LangChain describes them. If it does not,
  set `MODEL_ID=us.amazon.nova-2-lite-v1:0` (tool use also confirmed on its
  card).
- Region. `us.amazon.nova-micro-v1:0` is a US geographic inference profile
  with source Regions us-east-1, us-east-2 and us-west-2. Elsewhere, choose a
  model id that works in your Region.
- The hosted start command. With `ENABLE_OTEL=true` the runtime is told to
  start `opentelemetry-instrument agentcore_app.py`, exactly as the documented
  example does. That command is a script in the zip's `bin/` folder, and
  `uv pip install --target` writes its first line as the path of the Python on
  the machine that built the zip, for example
  `#!/Users/<you>/kit/.venv/bin/python3`. That path does not exist in the
  runtime and would carry your user name into the upload. AWS's own packager
  rewrites such lines to `#!/usr/bin/env python3`; `20_package.py` now does
  the same for every `bin/` script that starts Python, then searches the whole
  zip for paths of the build machine and refuses to produce a zip if it finds
  one. Whether that is enough for the runtime to start the command was not
  tested on AgentCore. The fallback if the runtime fails to initialise: set
  `ENABLE_OTEL=false`, run `20_package.py` again, tear down and redeploy. The
  start command is then plain `agentcore_app.py`, which uses nothing in
  `bin/`. You lose traces, not logs or usage.
- The address the server listens on. The Runtime contract says host 0.0.0.0,
  port 8080. The SDK's `app.run()` picks 127.0.0.1 unless it detects Docker.
  The kit does not leave that to chance: `30_deploy.py` sets
  `KIT_BIND_HOST=0.0.0.0` on the hosted runtime and `agentcore_app.py` passes
  it to `app.run()`. On your machine it stays 127.0.0.1. Not tested on AWS.
- The execution role and the zip. Two AWS pages disagree. The direct code
  deployment page says the role "must include basic Amazon Bedrock AgentCore
  runtime permissions, S3 access permissions for your deployment package, and
  CloudWatch Logs permissions for observability". The permissions page's
  "direct deploy execution role", which this kit copies statement for
  statement, has no S3 statement. If `30_deploy.py` fails because the runtime
  cannot read the package, set `EXECUTION_ROLE_S3_READ=true` in `config.env`,
  run `90_teardown.py`, and deploy again: the role then also gets
  `s3:GetObject` on that one zip and nothing else.
- Platform version V2 must be enabled for the account and is documented for
  us-east-1, us-east-2, us-west-2, eu-west-1 and ap-northeast-1 (announcement
  of 18 September 2026). AWS's sample notes that an account without it gets
  `ValidationException: platformVersion is not enabled for this account`, that
  create takes minutes on V2, and that boto3 1.43.95 is the first release that
  knows the field.
- The latency figures are whole-call times measured on your machine. They
  include your network, the model and the Federal Register. The gap between a
  first call and a later call in the same session is an estimate of session
  start-up plus ordinary variation. It is not a measured cold start.
- Runtime names take letters, digits and underscores only, so the runtime is
  `<prefix>_kitc_fr_agent` while everything else is `<prefix>-kitc-...`.
- `runtimeSessionId` must be at least 33 characters. The script builds ids
  that are.
- A new IAM role takes a few seconds to become usable. `30_deploy.py` waits 15
  seconds; if create still fails on the role, run `90_teardown.py` and deploy
  again.
- A runtime that is still being created cannot be deleted. `90_teardown.py`
  then says so, leaves the runtime's bucket and role in place, keeps
  `.state.json` and exits 1. Give it a few minutes and run it again.
- In us-east-1, `CreateBucket` on a bucket you already own returns 200 and
  resets its ACLs instead of failing. The kit's bucket has no custom ACLs.
- The agent keeps no conversation memory. Each call stands alone, locally and
  hosted.
- "The last N days" is worked out in code from the clock of the machine that
  runs the tool (UTC on AgentCore Runtime), from N days back up to today, both
  ends included. Late in the evening in Washington that clock is already on
  the next day.
- The Federal Register API needs no key. No rate limit was found on its
  documentation page; be polite. The tools cap results at 10, run at most
  three tool calls per model turn (at most 15 requests per question) and send
  a User-Agent that names this kit.
- What the tools cut. A search returns at most 10 documents and says how many
  the API reported in total. An abstract is cut at 1,500 characters, a title
  at 600, and a lookup returns at most 50 CFR references and 20 docket ids. A
  cut text ends in `[TRUNCATED]` and a cut list comes with its full length.
  Of 200 live records read on 2026-10-07, 3 had an abstract longer than
  1,500 characters; at the 400 characters the first two versions kept in a
  search result it was 112, and a number from a cut abstract draws a
  warning. Two broad live searches on 2026-10-07 both reported a total of
  exactly 10,000, which looks like a ceiling in the API; its documentation
  does not state one.
- What round 3 costs in input tokens. The system prompt grew from 2,440 to
  4,632 characters, sent on every model turn. A search result carries two
  fixed sentences (about 600 characters) and two word-count fields per
  document (about 105 characters on average over the rehearsal's 146
  returned documents). Over the 47 tool results of the rehearsal that was
  17% more characters. Not measured in tokens, and not on a bill.
- `tests/record_fixtures.py` talks to the Federal Register only when you pass
  `--record`. Run without it, it prints what it would send and stops.
- Two different tools install a command called `agentcore`: the current
  Node.js CLI and the old Python starter toolkit. This kit uses neither.

### Section 3: paragraphs that were reworded

README lines 738 to 745:

```
1. Have an AWS account on the Paid plan (see the Free Tier line above) with a
   role or user that may create and delete IAM roles, S3 buckets, CloudWatch
   log groups and deliveries, and AgentCore runtimes, and may invoke Bedrock
   models. An administrator role through IAM Identity Center is the simple
   choice for a personal sandbox account. Do not use the root user. AWS's
   managed policy for the AgentCore part is `BedrockAgentCoreFullAccess`.
2. Install the AWS CLI, version 2, and sign in on your machine. With IAM
   Identity Center the documented steps are (source 36):
```

### Section 4: steps that were reworded

README lines 789 to 793:

```
2. The graph with the fake model. No AWS. The Federal Register call is real.
   The fake "answer" is a listing of what the search returned, so the check
   in `finalize` has something to pass. Look at the parts of the answer:
   the block built by code, with its `Search words` line under each
   document, then the model's text under its label.
```

README lines 826 to 833:

```
9. Call the hosted agent: five sessions, the same question twice in each,
   every session stopped afterwards. A call whose answer was warned or
   replaced, or that reports a tool error, is listed with its warnings first
   and counted as failed, and the script then exits 1. A call that follows a
   failed call in its session is the first to reach the microVM, so it is
   left out of both latency lines and counted on a line of its own. The
   script prints when it started and finished (UTC) and the earliest time a
   usage read can be final.
```

README lines 838 to 845:

```
10. Read usage and cost. Makes no change in AWS. Usage data can arrive up to
    60 minutes after a session ends. Run this now to see that records arrive;
    it will say `RESULT: NOT CROSS-CHECKED` because it is early. Run it again
    once 60 minutes have passed since the last session, and repeat until its
    last line starts `RESULT: CROSS-CHECKED`. Token prices for the two models
    this kit names are built in; for another model add
    `--input-usd-per-1m <price> --output-usd-per-1m <price>` with the prices
    per 1M tokens from the Bedrock pricing page.
```

README lines 852 to 858:

```
11. Look at the same sessions in the console: CloudWatch, GenAI Observability,
    the Bedrock AgentCore tab (Agents, Sessions, Traces views), at
    https://console.aws.amazon.com/cloudwatch/home#gen-ai-observability .
    The runtime's own output is in the log group
    `/aws/bedrock-agentcore/runtimes/<runtime id>-DEFAULT`; for a newly
    created runtime AWS documents the same group, log stream `spans`, as where
    its spans go.
```

### Section 5 as it stood

> Corrected after round 4: the passage below calls the verdict of
> `90_teardown.py` its "last line" (C12 above). The script prints one or two
> lines after the verdict, and the last is `Now prove it: python
> 99_verify_clean.py`. README section 5 says so now.
> Corrected in round 5 (F16): every other closing line now comes before the
> verdict, so the verdict is always the line right above `Now prove it`.

Read your usage first (step 10): teardown deletes the log groups that hold it.

    python 90_teardown.py --dry-run
    python 90_teardown.py
    python 99_verify_clean.py

What teardown will not do, first.

- It works in one place: the Region and the name prefix in use, in the
  account you are signed in to. It does not go looking in other Regions.
- It deletes only the S3 bucket named exactly for this account and this
  Region (`<prefix>-kitc-code-<account>-<Region>`). `ListBuckets` shows the
  buckets of every Region; a bucket with the kit's name for another Region is
  printed with its Region and left alone, because a deploy may be live there
  and reads its code from it.
- One IAM role name serves every Region. The role is deleted only when no
  bucket of this kit exists for another Region and no runtime or gateway of
  this kit is found in any other Region the script can name: the Regions in
  the role's own trust policy and in `.state.json`'s history. If one of those
  Regions cannot be checked, the role is kept. It cannot see a Region that
  none of those three sources name.
- It never moves, renames, deletes or rewrites a `.state.json` it could not
  read.
- `--dry-run` deletes nothing and exits 3, not 0.

`90_teardown.py` first compares `.state.json` with the settings in use. If the
file records a deploy in another Region, under another prefix or in another
account, it stops with exit code 4 and deletes nothing; remember that an
exported AWS_REGION overrides config.env. It stops the same way when the file
cannot be read, or names resources without saying where they are. To tear
down anyway, name the place yourself, both values:

    python 90_teardown.py --region <Region> --prefix <prefix>

That run works by name only, in that one Region, and leaves the file exactly
as it is. Its last line is `TEARDOWN INCOMPLETE` and its exit code is 5, not
0, even when every delete worked: the file that would say where else the kit
was deployed could not be used. The clean check stays `RESULT: INCOMPLETE`
until you have checked every Region you used and moved the file out of the kit
folder yourself. The same holds for any `.state.json.damaged-*` file that the
first version of this kit left behind: open it, check the Region it names,
then move it away.

Otherwise it finds resources by this kit's name prefix in every service the
kit touches, so it also works when `.state.json` is lost, in the Region and
under the prefix in use. It stops any session still recorded as open (a stop
that fails is tried again once the runtime is gone), then deletes log
deliveries, the gateway and its target if you made them, the runtime, any
workload identity left behind, the log groups, the objects in the bucket
(every version and delete marker, if the bucket is versioned) and the bucket,
and the IAM roles. A runtime or gateway that the state file names is also
asked for by id; if that call fails with an unfamiliar error, the list call
decides, and the record is cleared only when the resource is in neither. A
gateway is counted as gone only when AWS no longer returns it. It is safe to
run twice.

> Corrected in round 5 (F1 in `REVIEW_NOTES_r5.md`): for a runtime or gateway
> that the state file names and the listing did not show, the list call no
> longer decides. When the call by id fails for any reason other than "not
> found", the record is kept and teardown exits 1. Below, the exit-0 line can
> also follow a `NOTE:` that the tag listing could not be read (F15).

Its last lines and exit codes:

- "Teardown finished without errors", exit code 0: everything recorded or
  named here was deleted or confirmed absent, and the listings by name and by
  tag showed nothing else of this kit (the line starts "Teardown finished."
  and names the session when a stop call needed its second try);
- "Teardown finished, BUT n resource(s) of this kit remain", exit code 1: the
  listing or the tag listing showed something of this kit that this run did
  not delete, for example another Region's bucket or a deploy under another
  prefix. Each is listed, with the command to run for it;
- "Teardown finished, BUT it cannot say this kit is gone", exit code 1: there
  was no record of a deploy and the tag listing could not be read;
- "Teardown finished WITH ERRORS", exit code 1: a call failed, and
  `.state.json` was left as it was. A session that could not be stopped at
  either try counts, and a line starting `NOT STOPPED` says what it can cost;
- `TEARDOWN INCOMPLETE`, exit code 5: see above;
- when no deploy was recorded in a usable state file, the line also says "No
  deploy was recorded in a usable state file, so this is not proof for any
  other Region, prefix or account."

It prints when it started and finished (UTC) and, when the state file holds
the time of the deploy, the hours the runtime existed.

`99_verify_clean.py` is the check. It lists by name prefix and, separately,
by the tags `project=aws-kits` and `kit=kit-c`, in the Region and prefix in
use and in every other Region and prefix that `.state.json`'s history names
for the account you are signed in to. A runtime or gateway that the file
records as live is also asked for by id. Its last line starts `RESULT:`, names
the account (last four digits), the Regions and the prefixes it checked, and
ends with the time of the check in UTC and the exit code:

- `RESULT: CLEAN`, exit code 0: nothing found anywhere it looked, and nothing
  it could not look at. Every such line says it is not proof for any other
  Region, prefix or account, and says so in plain words when no state file
  was found or an earlier teardown ran without a record;
- `RESULT: NOT CLEAN`, exit code 1: something is left, listed above the line
  with where it is and the command that removes it;
- `RESULT: NOT VERIFIED`, exit code 1: a lookup failed, so a permissions error
  cannot pass for a clean account;
- `RESULT: INCOMPLETE`, exit code 5: nothing found where it looked, but the
  state file names another account, or cannot be read, or names resources
  without saying where they are, or a `.state.json.damaged-*` file is still
  in the folder; exit code 4 when the file records a live deploy somewhere
  other than the settings in use, in which case nothing was checked;
- `--dry-run` exits 3, not 0, because a dry run proves nothing.

What `RESULT: CLEAN` does not cover: a Region or prefix that this machine's
`.state.json` never recorded, for example a deploy made from another computer
or before the state file was deleted. If you deployed anywhere like that,
run the check there too: `AWS_REGION=us-west-2 python 99_verify_clean.py`.

What teardown leaves, because the kit did not create it: Transaction Search
and the `aws/spans` log group if you turned them on, CloudWatch metrics
already published, and your model access. `99_verify_clean.py` reports the
state of the first two as information; if it cannot read them it says so and
the verdict does not change. The local zip stays in `.build/`; add
`--clean-local` to remove it.

For a second check that does not depend on this kit's code, run the shared
audit with the same Region and prefix:

    python ../common/whats_running.py --region <the AWS_REGION in your config.env> --prefix <your KIT_PREFIX>

The bill is the final word. Check Billing and Cost Management the next day.

### Section 6 as it stood

Write these into `RESULTS_TEMPLATE.md` as you go. Every row there that asks
for a time or a duration quotes the words of the line a script prints, so
copy the figure from that line; do not time anything by hand.

- Date, Region, the account's last four digits, model id, the platform
  version the service reported (or that it reported none and the version was
  assumed), package versions, zip size, and whether the zip was built from a
  lock file.
- Local run: the question, the tool calls, the check result and its reasons,
  every `WARNING:` line, the searches as the block shows them, the documents
  in the block, model turns, input and output tokens, seconds. Also one thing
  you checked by opening a URL from the block, and whether the model's text
  agreed with it.
- Deployment: the two `[timing]` lines, for the runtime and for the DEFAULT
  endpoint, and whether the OpenTelemetry start command worked.
- Hosted calls: when the run started and finished, sessions, the whole-call
  time of each first call and of each repeated call (the values themselves),
  calls left out because an earlier call in their session failed, and every
  failed or flagged call with its warnings.
- Usage: the last line of `60_read_usage.py` word for word, the line that
  starts "This read:" with its UTC time and minutes after the last session,
  whether `--accept-early-read` was used, both readings of the usage logs,
  the metric totals, the runtime cost if and only if it was cross-checked and
  not read early, whether the platform version was reported or assumed, the
  token counts, and the token price per 1M tokens you used with its date.
- From the bill a day later: dollars for AgentCore, for Bedrock model use, for
  CloudWatch and S3.
- Teardown: its last line and exit code, the line "The runtime existed for",
  the last line of `99_verify_clean.py` word for word (it carries its UTC
  time and exit code), and what the shared audit listed.
- Ten answers read by hand against the block. No script does this. Ask 10
  different questions of your own with `10_run_local.py` (each is one more
  model run, billed per token; nothing is created), or use answers you already
  have to 10 different questions. Read each answer against the block above it
  and write down how many made a claim of one of three kinds that the block
  does not support: that a document is about what you asked (its title in the
  block does not show it; open its URL when the title leaves that open), that
  a document is "the newest", "the latest" or "the most recent" of its kind,
  or that nothing else exists ("only", "no other", "nothing was published").
  Write down how many of those answers carried a `WARNING:` line, and how many
  answers carried a `WARNING:` that was wrong. Section 2 has these figures for
  two stand-in models; yours are the first for the model you ran.
- Which UNVERIFIED items in section 8 turned out right or wrong.

### Section 7 as it stood

> Corrected in round 4: four passages under "You cannot say" are C4 to C7
> above. Corrected after it: the third sentence under "you can say" opens with
> C11 above.

After a complete run with your own numbers recorded, you can say:

- You deployed and operated an agent that the kit supplied: a LangGraph
  tool-calling graph that you read and ran against a model on Amazon Bedrock
  through the Converse API, and then hosted on AgentCore Runtime using direct
  code deployment with boto3. If you changed the graph or the tools, say what
  you changed.
- You ran a script that created the execution role from AWS's documented
  policy, you read that policy, and you can say what it allows.
- You called the local server with curl and saw the contract it serves
  (`POST /invocations` and `GET /ping` on port 8080), you built and uploaded
  an arm64 zip, and you worked with sessions: one microVM per session, a
  session id of at least 33 characters, the idle timeout and maximum lifetime
  you set, and what `StopRuntimeSession` is for. The SDK hides the rest of the
  contract from you.
- You timed first and later calls end to end from your machine, for this
  agent, in your Region, on the date you ran it, over a handful of sessions.
  That figure includes the network, the model and the Federal Register. It is
  not a measured cold start.
- You read per-session vCPU-hours and GB-hours from the usage logs and, if
  the script's last line said `CROSS-CHECKED` without the words "read early",
  turned them into a cost that agreed with the CloudWatch metrics within 10%,
  read at least 60 minutes after the last session. Quote it with the
  platform version, and say so if that version was assumed. If the line did
  not say that, you have no session cost to quote.
- You tore the deployment down and ran a check that found nothing under your
  prefix in the Regions and the account its result line names. If that line
  says no state file was found, say that too.
- If you did the optional step: you put an OpenAPI operation behind AgentCore
  Gateway and called it as an MCP tool.

You cannot say, on the strength of this kit:

- That you designed or wrote the agent. The kit did.
- That you ran an agent in production, at scale or under load. This is a
  handful of sessions.
- That the agent's answers are correct, or were evaluated. What you can say is
  narrower: each answer began with a list of documents built by code from the
  API's own fields, and the model's text was compared with the tool results
  for document numbers, Federal Register citations, other numbers of two or
  more digits, dates, URLs, counts of documents and phrases in quotation
  marks. Its wording, which agency did what, single digits and anything else
  with no digits in it were not checked, nor were numbers in words, two-digit
  ordinals and two digits that follow letters. Before your run the check had
  seen 120 answers from two stand-in models (Claude Haiku and Claude Sonnet),
  not from the model you ran, for tool calls a person's agent had chosen;
  readers called 25 of them misleading, all 25 from the smaller model, and the
  check as it is now passed 15 of those 25 with no warning.
- That an answer the check passed is right. A pass means that the numbers and
  identifiers in the model's text were found in the tool results. It says
  nothing about relevance, about "the newest", or about completeness.
- That a document the agent listed is about what you asked, that "the newest
  rule on X" in an answer is that, or that nothing else was published. These
  were the commonest serious errors in both rehearsal passes and no rule in
  the kit checks them. The block gives you each title and a count of search
  words to look at; the looking is yours. What you can say is what you counted
  by hand (section 6): of the 10 answers you read, how many made such a claim
  that the block does not support.
- That the prompt or the check makes a weak model safe to use. In the
  rehearsal the rewritten prompt moved the smaller stand-in from 13 misleading
  answers in 30 to 12, the check passed most of them, and the larger stand-in
  wrote none in 60. Which model you ran matters more than either, and the
  kit's default model was in neither pass.
- That the warnings are reliable on your model's text. The check put a wrong
  warning on 10 of 39 clean answers the first time it met text it had not been
  corrected on, and on 12 of 68 honest texts a reader wrote for round 4.
- That a count in an answer is a count of documents on a topic. A total from
  the search is a count of documents that match the search words.
- That the agent cannot invent a document or a claim. It can, in words.
- That you measured a cold start, or a latency distribution.
- That your account is clean beyond what the check's result line names. It
  looks under one prefix, in the Regions and the account it lists, and
  without a state file that is one Region.
- That you used the AgentCore CLI, the managed harness, a container
  deployment, AgentCore Memory, Identity with OAuth, Policy, Evaluations,
  Code Interpreter or Browser. None is in this kit.
- That you ran in a VPC, behind PrivateLink, in AWS GovCloud, or under any
  compliance boundary. The runtime here uses network mode PUBLIC in a
  commercial Region.
- That your latency or cost figures hold for other agents, models, Regions or
  dates. Quote them with their date and conditions.
- Anything about Bedrock Agents Classic from experience.
- Before you have run it: anything first-hand at all. Until then this is a
  kit that was written from documentation.

### Section 8: every AWS call that was not run, script by script

> Corrected in round 4: part of the second bullet of the list below is C10
> above.

**NOT RUN: every AWS call**

No request was sent to AWS by any script, test or tool while this kit was
written, reviewed or corrected. In particular, none of these has been
exercised:

- `00_check.py`: STS GetCallerIdentity; Bedrock GetInferenceProfile,
  GetFoundationModel, GetFoundationModelAvailability; AgentCore
  ListAgentRuntimes; X-Ray GetTraceSegmentDestination.
- `10_run_local.py`, `12_serve_local.py` without `--fake-model`: Bedrock
  Converse through `langchain-aws`. The kit has never called a model. The
  tool schemas have not met a real model: in both rehearsal passes an agent
  chose the tool calls. The prompt as it was before round 3 and the prompt
  as it is now were each read by two stand-in models as plain text. The
  answer check has seen 120 real answers from those two models and
  otherwise only text written for the tests and the acceptance runs. How
  the default model searches and writes, and how often the warnings fire on
  its honest answers, is not known.
- `30_deploy.py`: STS GetCallerIdentity; S3 CreateBucket, PutBucketTagging,
  PutObject; IAM CreateRole, GetRole, PutRolePolicy; AgentCore
  CreateAgentRuntime, GetAgentRuntime, ListAgentRuntimeEndpoints.
- `40_enable_observability.py`: STS GetCallerIdentity; Logs CreateLogGroup,
  PutRetentionPolicy, PutDeliverySource, PutDeliveryDestination,
  CreateDelivery, DescribeDeliveries; X-Ray GetTraceSegmentDestination.
- `50_invoke_hosted.py`: STS GetCallerIdentity; AgentCore InvokeAgentRuntime,
  StopRuntimeSession.
- `60_read_usage.py`: STS GetCallerIdentity; Logs FilterLogEvents; CloudWatch
  GetMetricStatistics.
- `90_teardown.py`, `99_verify_clean.py`: STS GetCallerIdentity; the list
  calls in `kit_resources.py`, also in a second Region; AgentCore
  GetAgentRuntime and GetGateway by id; IAM GetRole; S3 ListObjectVersions
  and DeleteObjects; the Resource Groups Tagging API GetResources; and every
  delete call.
- `optional_gateway/`: STS GetCallerIdentity; IAM CreateRole; AgentCore
  CreateGateway, GetGateway, CreateGatewayTarget, GetGatewayTarget,
  DeleteGatewayTarget, DeleteGateway; the signed MCP requests to the gateway
  URL.

### Section 8: the UNVERIFIED items in full

**UNVERIFIED: details not confirmed in a current AWS document**

Each is also marked `# UNVERIFIED:` where it appears in the code.

1. That the hosted runtime starts `opentelemetry-instrument` from the zip's
   `bin/` folder once its first line is `#!/usr/bin/env python3`. The
   documented example passes exactly this entry point, and AWS's own packager
   rewrites build-machine start lines in the same way, which is why the kit
   does. It was not run on AgentCore. Fallback: `ENABLE_OTEL=false`.
2. The JSON layout of a `USAGE_LOGS` record. The field names are documented
   (`session.id`, `elapsed_time_seconds`, `agent.runtime.vcpu.hours.used`,
   `agent.runtime.memory.gb_hours.used`); whether they are nested is not
   shown, so the parser looks at any depth.
3. That the log delivery source for a runtime takes the runtime ARN (AWS's
   example is generic across AgentCore resource types); whether each usage
   record is an increment or a running total; and how often a record is
   written. `60_read_usage.py` prints both readings, guesses from
   `elapsed_time_seconds`, and calls a figure cross-checked only when the
   read is at least 60 minutes after the last session, the CloudWatch metric
   total agrees within 10% and the records cover at least 90% of each
   session's wall-clock time. If AgentCore writes records only for part of a
   session, or without `elapsed_time_seconds`, that test will keep saying
   `NOT CROSS-CHECKED`, and you will have no session cost to quote from this
   kit.
4. Whether a span record carries the runtime session id as plain text. AWS
   documents that a newly created runtime sends spans to the `spans` stream of
   its own log group, and older ones to `aws/spans`; the script counts both.
   Either count may read zero even when traces exist; the console view is the
   fallback.
5. Whether AgentCore deletes a runtime's or a gateway's workload identity
   when the parent is deleted. Teardown lists again afterwards and deletes any
   that remain. Likewise whether deleting a runtime ends its open sessions:
   teardown stops them first, and tries again afterwards if a stop failed.
6. Which AgentCore resource types the Resource Groups Tagging API returns.
   The by-name checks do not depend on it.
7. That a direct-code runtime reaches the server on 0.0.0.0:8080. The kit now
   passes that host explicitly through `KIT_BIND_HOST`, set at deploy. AWS's
   own direct-code samples call `app.run()` with no arguments, and the SDK
   would then pick 127.0.0.1 outside Docker; which of the two the managed
   runtime needs was not tested.
8. Optional gateway: that a gateway service role with no permissions policy is
   enough for a public OpenAPI target; the SigV4 signing name
   `bedrock-agentcore` for gateway calls (taken from AWS sample code, the
   documentation shows a bearer token); that a new gateway accepts
   `MCP-Protocol-Version: 2025-11-25` without an `initialize` call; and the
   exact tool name `federal-register___getAgency`.
9. What a deployed runtime with no session really bills. The pricing page
   says the code artifact bills at S3 Standard rates and gives 100 MB as
   $0.0023 a month; whether that is in addition to the copy in your own
   bucket, and how "system overhead" shows up in a session's usage, has not
   been seen on a bill.
10. CloudWatch's and S3's own rate tables: not read, so not quoted. Model
    token prices are quoted for Nova Micro and Nova 2 Lite only, in three US
    Regions.
11. Whether the execution role needs S3 access to the deployment package.
    Two AWS pages disagree (section 2). The default follows the permissions
    page; `EXECUTION_ROLE_S3_READ=true` adds the one statement.
12. Whether Amazon Nova accepts the search tool's optional arguments in the
    form LangChain sends them (each optional argument allows a null value).
    No model was called through Bedrock.
13. That `GetAgentRuntime` echoes `platformVersion` and the lifecycle
    settings. Where it does not, the kit uses what the deploy asked for and
    says on every rates line that the version is ASSUMED.
14. What the spans hold on AgentCore with `TRACELOOP_TRACE_CONTENT` set to
    `false`. The setting was read in the source of
    `opentelemetry-instrumentation-langchain` 0.62.4; no span was produced
    here, and the other instrumentations the AWS distribution switches on
    were not read. Look at one trace before you rely on it.
15. The error code AgentCore gives for a runtime or gateway that does not
    exist. The API pages document `ResourceNotFoundException`; for any other
    answer teardown asks the list call, and treats the resource as gone only
    when it is in neither.

> Corrected in round 5: only for a resource this run listed and deleted. A
> recorded one that the listing did not show keeps its record (F1).

16. That S3 `DeleteObjects` accepts the version id "null" for an object in a
    bucket whose versioning was switched on after the object was written. It
    is sent only from the second round of emptying on, which a bucket that
    was never versioned does not reach.
17. That the Federal Register API caps a search total at 10,000. Two broad
    live searches reported exactly that figure; the API documentation states
    no ceiling. The tool passes such a total on with a note.

### Section 9 as it stood: the 42 sources

Every source was read on 2026-10-07. AWS API reference pages cited next to
each call in the code were read the same day and are not repeated here.

AWS documentation and pricing

1. Bedrock Agents Classic maintenance mode:
   https://docs.aws.amazon.com/bedrock/latest/userguide/agents-classic-maintenance-mode.html
2. AgentCore pricing: https://aws.amazon.com/bedrock/agentcore/pricing/
3. AWS Free Tier offers list: https://aws.amazon.com/free/
4. Use any agent framework (the LangGraph example):
   https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/using-any-agent-framework.html
5. Runtime HTTP protocol contract:
   https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-http-protocol-contract.html
6. Direct code deployment for Python:
   https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html
7. Runtime permissions (execution role and trust policy):
   https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html
8. How Runtime works, platform versions V1 and V2:
   https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-how-it-works.html
9. New AgentCore Runtime announcement, 18 September 2026:
   https://aws.amazon.com/about-aws/whats-new/2026/09/new-agentcore-runtime-generally-available/
10. Runtime sessions:
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html
11. Runtime versions and the DEFAULT endpoint:
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html
12. AgentCore quotas:
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html
13. AgentCore Regions:
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-regions.html
14. Interfaces for AgentCore (the CLI, the Python SDK):
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/develop-agents.html
15. Runtime observability data (metrics, usage logs, application logs, spans),
    including the 60-minute delay note:
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-runtime-metrics.html
16. Configure observability (log deliveries, Transaction Search, where a
    runtime's spans go):
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html
17. Observability get started:
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-get-started.html
18. View observability data:
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-view.html
19. Supported frameworks for instrumentation (LangGraph):
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/supported-frameworks.html
20. Enable Transaction Search (CloudWatch):
    https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Enable-TransactionSearch.html
21. Bedrock model access:
    https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html
22. Amazon Nova Micro model card:
    https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-micro.html
23. Amazon Nova 2 Lite model card:
    https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-2-lite.html
24. Inference profiles:
    https://docs.aws.amazon.com/bedrock/latest/userguide/inference-profiles-support.html
25. Bedrock pricing, and the price file the page's tables are filled from
    (published 2026-10-06):
    https://aws.amazon.com/bedrock/pricing/
    https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/bedrock/USD/current/bedrock.json
26. AgentCore FAQs: https://aws.amazon.com/bedrock/agentcore/faqs/
27. Gateway: supported targets, OpenAPI targets, outbound and inbound
    authorization, service role, create, list tools, call tools:
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-supported-targets.html
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-schema-openapi.html
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-outbound-auth.html
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-inbound-auth.html
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-prerequisites-permissions.html
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-create-api.html
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-using-mcp-list.html
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-using-mcp-call.html

AWS code, cloned read-only on 2026-10-07 and read, not copied

28. `awslabs/agentcore-samples` at commit 3f2d283 (6 October 2026),
    https://github.com/awslabs/agentcore-samples :
    - `01-features/02-host-your-agent/01-runtime/01-hosting-agents/01-http-protocol/02-langgraph-bedrock/`
      (`README.md`, `agent.py`, `deploy.py`, `invoke.py`, `cleanup.py`): the
      current LangGraph runtime example and the pattern this kit follows;
    - `.../01-http-protocol/01-strands-bedrock/README.md`: platform version
      V2 and what is safe to do at import time;
    - `.../01-runtime/05-measure-your-runtime/README.md`: idle sessions are
      what you pay for; the CloudWatch namespace, metrics and dimensions;
    - `01-features/05-authenticate-and-authorize/08-okta-xaa-delegation-chain/deploy/02_create_gateway.py`:
      an OpenAPI gateway target with no credential provider;
    - `01-features/07-centralize-and-govern-your-ai-infrastructure/01-gateway/gatewaylabproject/streamable_http_sigv4.py`
      and `02-use-cases/01-conversational-agents/market-trends-agent/optimization/optimize_agent.py`:
      SigV4 signing for gateway calls;
    - `README.md` and `MIGRATION.md`: the move from the starter toolkit to the
      AgentCore CLI.
29. `aws/agentcore-cli` at commit dd6304e (5 October 2026, version 0.31.1),
    https://github.com/aws/agentcore-cli : `README.md`, `docs/commands.md`,
    `docs/PERMISSIONS.md`, `docs/container-builds.md`, `docs/frameworks.md`,
    the LangGraph template `src/assets/python/http/langchain_langgraph/base/`,
    and `src/lib/packaging/helpers.ts` (`isHardcodedShebang`,
    `rewriteUnixShebangs`): how AWS's packager makes `bin/` scripts portable.
30. `aws/bedrock-agentcore-sdk-python` at commit 99663b0 (version 1.24.1),
    https://github.com/aws/bedrock-agentcore-sdk-python :
    `src/bedrock_agentcore/runtime/app.py` (routes, entrypoint, run and the
    host it picks).
31. `aws/bedrock-agentcore-starter-toolkit` at commit 9d05dcb (version 0.3.14),
    https://github.com/aws/bedrock-agentcore-starter-toolkit : `README.md`
    ("no longer supported").
32. The AWS SDK service definitions in botocore 1.43.108 for
    `bedrock-agentcore-control`, `bedrock-agentcore`, `bedrock`, `logs`,
    `cloudwatch`, `s3`, `iam`, `sts`, `xray` and `resourcegroupstaggingapi`.

Other

33. LangChain documentation for the Bedrock chat models:
    https://docs.langchain.com/oss/python/integrations/chat/bedrock
34. Federal Register API documentation:
    https://www.federalregister.gov/developers/documentation/api/v1
35. PyPI, through `pip index versions`, for the pins in `requirements.txt`,
    and through `uv pip compile` for the two lock files.
36. AWS CLI: configuring IAM Identity Center sign-in (`aws configure sso`,
    `aws sso login`):
    https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html
37. Runtime lifecycle settings (defaults 900 and 28,800 seconds; 60 to 28,800
    for microVMs):
    https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html
38. The independent review of this kit, round 1, 2026-10-07: 27 findings with
    file, line and evidence, and eight experiment scripts whose cases are now
    in `tests/`.
39. The second independent review, round 2, 2026-10-07, by three readers: the
    answer check (189 scripted runs, 200 live Federal Register records), the
    numbers, and money and teardown (sequences C00 to C25 against a fake
    AWS). 27 findings for this kit.
40. AWS Price List file for Amazon Bedrock, us-east-1 (publication date
    2026-10-06T14:47:26Z), with the us-east-2 and us-west-2 files for
    comparison:
    https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonBedrock/current/us-east-1/index.json
41. `opentelemetry-instrumentation-langchain` 0.62.4, the wheel from PyPI:
    `opentelemetry/instrumentation/langchain/utils.py` (`should_send_prompts`
    and `TRACELOOP_TRACE_CONTENT`) and the package's own description.
42. This repository's kit B, `kitlib/aws.py`: its way of emptying a versioned
    bucket, read and written again here, not imported.

The research notes this kit started from were another reader's summary of AWS
pages on the same date. Nothing in this kit rests on them alone.
