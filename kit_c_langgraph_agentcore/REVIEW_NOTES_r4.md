# Kit C: review round 4 (2026-10-07), what was found and what was done

Four independent reports were written on this kit's code as it stood after
round 3. Three of them name kit C: a reader of what a user sees, a reader of
money safety, and a reader who ran the kits against a local AWS emulator. This
file lists every finding that names kit C, with what was done about it. The
README has the short form in the sections that hold each subject.

Nothing here was run against AWS, and no model was called.

## What is still wrong, first

- The answer check is again corrected on text it had just been shown. Round 4
  is the fourth time. The figures below for "this code" are for the reader's
  own texts, on which the rules were then corrected. They say what the code
  does on those texts and not what it will do on yours.
- Of the reader's 212 texts with planted unsupported content, 25 still pass
  with no warning. All 25 are of kinds the README lists as not seen: 4 numbers
  written as words, 1 two-digit ordinal ("the 83rd"), 1 number that follows
  letters ("FY27"), 12 search totals given as a count in a wording the rule
  does not read, 6 counts of what was returned in a wording the rule does not
  read, and 1 count whose noun is not a document word. In the reader's second
  batch 2 of 10 pass: a list heading with "the following 10 final rules", and
  a total with four words between the number and the noun.
- Two of the reader's sequences end with another exit code than the reader
  labelled, on purpose: g19 (see MINOR 2 below) and g20 (see m10).
- Two create calls are still not on record by id if the process dies right
  after the call: the log delivery and the gateway target. AWS gives each its
  id in the answer, which a dead process never reads. Their names are on
  record before the call, and teardown finds both by name.
- Whether deleting a runtime ends its open sessions is still not verified.
  Teardown now asks again after the runtime is gone and says what a session
  can cost if it outlived its runtime.

## Counts, before and after

The reader's suite (one command, labels fixed and hashed before the kit's
check ran on them; the label files are unchanged):

| Part | Frozen code | This code |
|---|---|---|
| Planted unsupported content passed with no warning | 50 of 212 | 25 of 212 |
| ... of the 188 inside the README's wording at the time | 26 | 2 (the ordinal and "FY27", now named as limits) |
| A warning names the planted item | 160 of 212 | 186 of 212 |
| Honest texts warned | 12 of 68 | 0 of 68 |
| Honest texts with a NOTE and no warning | 11 | 13 |
| Odd tool results: crashes / cases with a failed check | 2 / 13 of 34 | 0 / 0 of 34 |
| fr_tools checks failed | 2 of 59 | 0 of 59 |
| Usage: CROSS-CHECKED where labelled NOT / off label in any way | 2 of 10 / 4 of 24 | 0 of 10 / 0 of 24 |
| Teardown and clean check: wrong "clean" | 3 of 33 | 0 of 33 |
| ... every exit code as labelled | 30 of 33 | 31 of 33 |
| Second batch: planted passed / honest warned / hosted off label | 4 of 10 / 5 of 7 / 2 of 4 | 2 of 10 / 0 of 7 / 0 of 4 |

No text that was warned before passes now, and no honest text that passed
before is warned now. One sequence that matched its label before does not
now: g19 (below).

The 120 real answers of the two rehearsal passes, by the readers' blind labels
(passed / warned / replaced). Unchanged in every cell:

| Label | First pass, frozen | First pass, this code | Second pass, frozen | Second pass, this code |
|---|---|---|---|---|
| clean (33, 39) | 30 / 2 / 1 | 30 / 2 / 1 | 36 / 2 / 1 | 36 / 2 / 1 |
| minor (14, 9) | 11 / 3 / 0 | 11 / 3 / 0 | 9 / 0 / 0 | 9 / 0 / 0 |
| misleading (13, 12) | 6 / 6 / 1 | 6 / 6 / 1 | 9 / 2 / 1 | 9 / 2 / 1 |

The same answers are warned for the same reasons. Three rows changed in what
is shown and not in their outcome: the two "names none of the documents"
warnings have their new wording, and one clean answer of the second pass lost
a NOTE because it names a returned document by its complete title. A first
version of the rule for B1 did warn one clean answer of the second pass ("Five
documents matching the search ... are:", in answer to "the five newest"); the
rule was narrowed to the verb before anything else was built on it.

The earlier scripted suites: the 189 runs leave the same 5 with no warning and
no run changed its outcome; the 40 honest listings in each of four plain
layouts are not warned (0 of 160) and 6 of the 40 that copy whole abstracts
are, as before; the 79 runs of round 2 and the 60 of round 3 end as before.

The money reader's harness, kit C only (85 sequences, 37 checks):

| Count | Frozen code | This code |
|---|---|---|
| Wrong "clean" | 5 of 85 | 3 of 85, each with the limit in its closing line |
| ... with the state file intact | 1 of 58 | 0 of 58 |
| Script runs that printed a full account id | 7 of 286 | 0 of 286 |
| Create calls with nothing on record if the process dies | 11 of 11 | 2 of 11 (above) |
| Checks as expected (dry runs, flags, creates, account id, last lines) | 19 of 37 | 35 of 37 |

The three that remain are the documented limit: the state file is missing or
is an older copy, and the bucket and role that would give the deploy away were
removed by hand. One sequence that matched its label before does not now:
C054, for the same reason as g19. The two checks that remain are the log
delivery and the gateway target (above).

## Findings of the reader of what a user sees

- B1, "Ten documents matched the search ... among ..." passed. FIXED. When a
  sentence says with its own verb that the count matched ("ten documents
  matched", "the search matched ten documents"), a subset word excuses it only
  within three words of the count. "Five documents matching the search ...
  are:" heads a list and is not read this way. STATED AS A LIMIT: "The Coast
  Guard published the following 10 final rules ...:" still passes; the README
  says that "following", "these", "here are" and the like excuse a count.
- M1, a two-digit number joined to a word, a hyphen, a letter, "~", "No." or
  ":". FIXED for a unit or a label joined to the number ("a 60-day period",
  "an 83-page rule", "45mph", "$83M", "83T", "~83", "No.83", "Pages:83") and
  for a clock time ("11:59", compared whole). STATED AS A LIMIT for a
  two-digit ordinal ("the 83rd") and for two digits that follow letters
  ("FY27"): reading them warns "the 21st century" and "COVID-19" in honest
  text, which a test of round 2 pins. The label above the model's text and
  README sections 2 and 7 now name both.
- M2, lists with fields separated by a spaced dash. FIXED. A long dash, or a
  hyphen with a space on both sides, joins two numbers only when both are
  plain numbers; "2026-19964 - 2026-09-30" is a number and a date.
- M3, a warning for a CFR title the model never wrote. FIXED. A CFR reference
  in the model's text is read within one line. STATED AS A LIMIT: "amends 49"
  at the end of one line and "CFR part 571" at the start of the next is not
  read as a reference.
- M4, an honest heading line warned when the total stands one paragraph up.
  FIXED. "Here is" and "here are" are subset wording, and a larger total given
  as a count of matches in an earlier paragraph excuses a count unless the
  sentence says "only", "exactly" or the like.
- M5, teardown exited 0 while its tag listing showed a bucket of the kit under
  another prefix. FIXED. A name from the tag listing must match what was
  deleted as a whole.
- M6, the clean check printed CLEAN beside a state file naming a runtime that
  still exists. FIXED. It asks for the recorded runtime and gateway by id; one
  that exists is counted, and one that cannot be asked for makes the result
  NOT VERIFIED.
- M7, a URL without a scheme. FIXED for an address with a path
  ("regulations.gov/docket/X", "www.faa.gov/x", "//www.faa.gov/x").
  STATED AS A LIMIT: a host name with no path names a site and is not
  compared.
- m1, four date forms. FIXED: "15-Nov-2026", "November the 15th", "November
  fifteenth, 2026", "the fifteenth of November".
- m2, quotation marks. FIXED: guillemets, the German low-high pair, a curly
  mark closed by a straight one and the reverse, and a quotation that runs
  over one line break.
- m3, other false warnings. FIXED, all six: two returned numbers joined by one
  hyphen are compared one by one; the numbering column of a table is not a
  claim; a quotation with "..." is compared piece by piece; every string of a
  tool result may be quoted; a total may be referred to again after a sentence
  that gave it as a count of matches.
- m4, "nothing in it could be tied to the tool results". FIXED. A document is
  named by its number, its complete title or its URL. With one document in the
  block an unnamed text gets a NOTE. With several the WARNING stays and says
  only that code cannot tell which document the text is about.
- m5, the crash on an odd `cfr_references` entry. FIXED.
- m6, block fields copied uncleaned. FIXED in the tool (type, dates, URLs,
  citation, agency names and docket ids are put on one line, stripped of
  control characters, and cut when far longer than any real value) and again
  where the block is printed.
- m7, lines of the model's text shaped like the kit's own. FIXED. Such a line
  is shown with "[written by the model, not by the kit]" in front. A line that
  starts like the heading of the block or the label of the summary also draws
  a WARNING.
- m8, a failure inside the run reported as `invalid_input`. FIXED: it is
  `run_failed` now.
- m9, `60_read_usage.py`. FIXED, all four: mixed record layouts and a session
  with no end time end NOT CROSS-CHECKED; the token line says LOWER BOUND when
  a call reported no tokens and NOT A MEASURED COST when none did.
- m10, a log group that appears while the runtime is deleted. FIXED: the log
  groups are listed again once the runtime is gone. The reader's sequence g20
  was labelled exit code 1 for the group that was left; it is deleted now, and
  teardown and the clean check both end with exit code 0 and nothing left.
- m11, two error texts of the tool. FIXED.
- m12, real document numbers of a form the pattern does not read (2010-99,
  X94-61230). FIXED for naming: a returned number counts as named when the
  text holds it exactly. NOT CHANGED: such a number that no tool returned is
  still reported as a number and not as a document number.
- m13, the URL as the warning prints it. FIXED: as the model wrote it.

## Findings of the money reader that name kit C

- MAJOR 3, the full account id on the screen. FIXED. AWS's error text and
  every line a dry run prints go through a filter that shows a 12-digit number
  as its last four digits.
- MINOR 1, "finished without errors" after a stop call failed. FIXED. Teardown
  tries the stop again once the runtime is gone. If that fails too the exit
  code is 1 and a line says what an open session can cost. If it works the
  closing line says that the first call failed.
- MINOR 2, teardown beside a damaged state file with `--region` and `--prefix`
  exited 0. FIXED: the last line is TEARDOWN INCOMPLETE and the exit code is 5.
  This is the change behind g19 and C054: the two readers labelled the same
  run differently, one expecting 0 and one expecting 4 or 5.
- MINOR 5, the CLEAN line without "not proof" words. FIXED: every CLEAN line
  says what it is not proof of.
- MINOR 15, creates not on record. FIXED for 9 of 11; STATED AS A LIMIT for the
  log delivery and the gateway target (above).
- `30_deploy.py` exiting 2 after the runtime was created. FIXED: a stop after
  the first create call was sent is exit code 1, in the deploy, the
  observability step and the gateway step.

## Findings of the emulator reader that name kit C

- A failed hosted call printed the error code twice. FIXED: the code and what
  AWS said.
- One test sent a name lookup for a public host. FIXED: the tests refuse name
  lookups as well as connections.
- A lost answer to CreateAgentRuntime: the script said the runtime was in
  `.state.json` when it was not, and deploying again failed the same way.
  FIXED: the runtime's name is on record before the call, the closing line
  says that the id is on record only if AWS answered, and an "already exists"
  answer prints what to do (tear down, then deploy).
- A quoted `date_note` warned as "in no tool result". FIXED with m3.
- Exit code 0 with a damaged state file. FIXED with MINOR 2.

## Changed although no finding asked for it

- A number returned twice in one run with two different complete titles is
  shown with both titles in the block (it was one of the reader's failed
  checks, not a numbered finding).
- A clock time ("11:59") and a ratio ("10:1") are groups of numbers and are
  compared whole.
- The two parts of a range a tool returned ("parts 70-71") count as returned
  numbers when the text writes them apart.
- `50_invoke_hosted.py` prints the reason the runtime gave with its own named
  error, and flags a call whose text imitates the block.
- The warning for a URL field that the tool had to cut: a cut URL is not a
  returned URL.

## Tests

`tests/test_r4_answer_check.py` (98 tests) and `tests/test_r4_money.py` (41)
are new. Run against the frozen code, 65 of the first file's 98 tests and 36
of the second's 41 fail; the others pin limits and what had to stay. Eight
older tests were changed with the behaviour they pinned, and each says so
where it stands: the exit code and last line of a forced teardown, the words
on a CLEAN line, the printed form of a failed stop, the second listing of log
groups in four teardown tests, and the offline guard. `test_readme.py` has one
new test and was changed with the README. The whole suite, 970 tests, passed
on Python 3.13.16 and on Python 3.14.6.
