# `referee narrate`

`python -m referee narrate REPORT [--question TEXT] [--llm-command CMD] [--show-request]` answers a
question about a saved results report in the engine's own sentences. By default no model runs and
nothing leaves the machine. The page is advice, not a gate. **With `--llm-command`, the command you
name is sent the report's counts, p values, rates and allocations, and may send them anywhere** (see
"The model path").

## Use

`REPORT` is the JSON of `review-results --format json`. This makes the report of the README's
example, which is the committed `tests/golden/offer-page-results.json`:

```bash
python -m referee review-results examples/offer-page-results.yaml \
    tests/data/hybrid_offer_page_5000 --experiment-id hybrid_offer_page \
    --as-of 2026-06-30T00:00:00Z --format json > report.json   # exits 1: the verdict is invalid
python -m referee narrate report.json
python -m referee narrate report.json --question "Why does RES-001 block the review?"
```

Without `--question` the page is a summary of the review. An empty `--question ''` is a question,
not the summary: it gets the page for a question that could not be read (reason: empty), with status
0. A question that starts with `-` and has no space, such as `-why`, is read by argparse as an
option, so write it `--question=-why`.

A question is read by a router, a table of words and not a model, into one of four kinds the layer
answers about a report, one example each: a summary (`What did the review find?`), one finding
explained (`Why does RES-001 block the review?`), what to do next (`What should we fix before
running this again?`) and what was checked (`Which checks did this review run?`). Anything else gets
a refusal: a request for a decision or for agreement, for the effect's numbers, a forecast, a
breakdown the report does not hold, or a question the router does not recognise. The three questions
of the design are refused:

```bash
python -m referee narrate report.json --question "can we call it on day 3?"
python -m referee narrate report.json --question "arm C is significant in Germany, ship there?"
python -m referee narrate report.json --question "SRM is only 0.4%, fine, right?"
```

The first prints this, and exits with status 0:

```text
Report of experiment hybrid_offer_page, export taken 2026-06-30T00:00:00Z.
Verdict: invalid. Blocking rules: RES-001, RES-002. Findings: 2 blockers, 4 warnings, 0 info.
Question understood as: a question this layer does not answer (categories matched: stopping).

Do not read the effect. RES-001 blocks this review, and its remediation says to settle what it found before the effect is read.

RES-002 also blocks: `control` (926 analysed, 2,107 required), `variant_b` (969 analysed, 2,107 required) and `variant_c` (731 analysed, 2,107 required) are smaller than the registered sample size. Once the effect can be read, and if they are still smaller, report the result as underpowered: a small difference is not evidence of no effect.

Decided here: whether the rules object to reading this experiment's result as it stands. Not decided here: whether to ship, stop or continue the experiment. Referee is advisory, and that decision rests with the experiment's owner.

The memo's other sections are not part of this page.

This layer does not say whether an experiment may be stopped, called or read at the point it has reached.
Days observed: 21; days planned: 21.
Raised in this report, about the length and size of the run:
  [RES-002.title] Fewer players than the registered sample size
RES-003 ran and raised no finding.
A rule reads only what the export holds. This is not agreement with the question, and it does not say the effect is real.

Not a decision and not a gate. This page advises only; its exit status does not mean the experiment is valid.
```

Every page has the same frame: the report and its verdict, what the question was understood as (the
page never repeats its words), the Decision section of the report's memo, the body, and a footer.
A refusal says what the layer does not do and points into the report. A question over 500 characters,
or with an invisible character, a combining mark or a word that mixes Latin letters with Cyrillic,
Greek, Armenian, Coptic or Cherokee ones, gets a page that says why it could not be read.

## What the page guarantees

Every word on standard output is one of four things: a sentence of the rule catalogue (a title,
why it matters, what to do) whole and unchanged, with its ID; a string written by this layer's code;
a value of the report printed by code beside a label the code wrote (numbers rounded to six
significant digits, an arm's name with control characters written as escapes); or a sentence of the
memo's Decision section. The layer cannot shorten, join, define or explain a sentence, so it is not
plainer than the catalogue.

The guarantee has edges. The page defeats omission, not emphasis: it prints everything a question
permits for each finding, but cannot say which matters most. The router is not injection-proof and
its twelve categories are not complete, so a question answered when it should have been refused gets
the fixed page, which prints every finding. A refusal word spelt with look-alike letters of one
script (an all-Cyrillic word, a dotless i) is read as another word and missed. A letter with an
accent is matched as the plain letter. Refusals quote the catalogue's sentences and never reword
them. A terse question that holds no word of the report, such as `Give me a summary.`, is refused by
default; `narrate report.json` with no `--question` prints the summary. A rule named in a question
about its numbers makes the numbers its explanation (`How big is the difference between arms, given
RES-001?` is an explanation of RES-001). A forged report that is consistent with itself passes the
check below, and an arm's name is text someone chose.

## Exit status

| Status | Meaning |
| --- | --- |
| 0 | A page was printed: an answer or a refusal, whatever the verdict. A refusal exits 0 on an `invalid` report, where `review-results` exits 1. Also the output of `--show-request`. |
| 1 | `--llm-command` returned output that failed a check, and the narration was withheld: the page on standard output says which checks. It does not mean a blocker. |
| 2 | The report cannot be read, parsed or checked, or the arguments are unusable (`--llm-command` is empty or has a quote or backslash left open). The problems are on standard error: at most 1,000 are listed, with their exact number, and an arm's name is written as escapes. |
| 3 | Referee failed while making or writing the page or the request; a write that fails, such as a full disk or a closed pipe, is a failure too, and so is a request over 32 KiB or a word of the report found in the sheet (the egress assertion). Standard error names the exception's type; a failure while making the page leaves standard output empty. |
| 4 | The command of `--llm-command` failed. One line on standard error with a reason, `start`, `exit`, `timeout`, `empty`, `size` or `encoding`, and nothing on standard output. |

Nothing is written to standard output until the page is complete.

**Do not write `referee narrate report.json && ship`.** Status 0 means that a page was printed, not
that the experiment is valid or approved; every page ends by saying so.

## The model path

**`--llm-command` sends the report's counts, p values, rates and allocations to whatever the command
contacts.** The arms' names become `A1` (the control), `A2`, `A3`, which hides the names and nothing
else. The experiment's id, the metric names and the other free text of the report are not put in
what is sent, and a check before each request refuses to make it (status 3) if a word of the report
that Referee did not write is in it; a word that is also one of the engine's own (an arm named
`control`) could not be told apart, so the check is no proof. Your question is not sent: the command
is given the kind of question and the rule it names. `--show-request` prints what would leave.
Referee does not control what the command does with it.

The command chooses what leads, never what is said. For a summary, the next steps or the explanation
of one finding, `--llm-command CMD` runs `CMD` once and reads identifiers from its output; for every
other page, a refusal, `checked`, the explanation of a rule that raised nothing, and a report with
no finding, nothing is run, even with the option. The page then prints each finding in scope with
everything the question permits, what the command selected first under `Selected:` and the rest
under `Not selected by the narrator:`, in catalogue order: the command's order is not used, and its
output is never printed. This does not make the page relevant or plainer, and the labels are no
ranking.

The contract of the command, in six lines:

1. `CMD` is split into words as a POSIX shell splits it and run without a shell, in a session of its
   own, in Referee's environment, which Referee neither reads nor prints.
2. Standard input is one line of JSON, `{"max_tokens": N, "schema": "referee-narration-request/1",
   "system": "...", "user": "..."}`, at most 32 KiB, then the end of the input; you need not read it.
   `user` is the sheet, JSON as text: the task, the aliases, and for each finding in scope its
   sentences and facts, each with an identifier.
3. Standard output is one JSON object, `{"schema": "referee-narration-output/1", "findings":
   [{"id": "RES-001", "facts": [...], "sentences": [...]}]}`, of identifiers of the sheet only (no
   text, no number), at most 32 KiB of UTF-8, with exit status 0.
4. Standard error is discarded.
5. At most 120 seconds for the whole exchange, one attempt and no retry; when `CMD` has exited,
   what it left on standard output is read and nothing waits for a process it started.
6. A failure to start, a non-zero exit, a timeout, no output, more than 32 KiB or output that is not
   UTF-8 is status 4; output that breaks the contract (a rule that is not a finding, an identifier
   the sheet does not hold, a blocker or warning left out) is status 1 and prints the codes and
   rule IDs of what failed, never the output.

`--show-request` writes to standard output the exact bytes `CMD` would receive, one line of JSON, and
starts nothing. When no request would be made (the question is refused or is `checked`, it names a
rule that raised nothing, the report has no finding, or `--llm-command` is not given) it prints
`no request would be made for this question`. The status is 0 either way.

A file can stand in for the command, to replay a selection without a model: `cat FILE` reads
nothing and prints the file, and Referee does not wait for it to read. This is `selection.json`, a
hand-made selection with one reason for each blocker and warning of the committed report, and the
request that `--show-request` writes for the same question:

```bash
cat > selection.json <<'EOF'
{"schema": "referee-narration-output/1", "findings": [{"id": "RES-001", "facts": [], "sentences": ["RES-001.why.2"]}, {"id": "RES-002", "facts": [], "sentences": ["RES-002.why.1"]}, {"id": "RES-007", "facts": [], "sentences": ["RES-007.why.1"]}, {"id": "RES-008", "facts": [], "sentences": ["RES-008.why.1"]}, {"id": "RES-012", "facts": [], "sentences": ["RES-012.why.1"]}, {"id": "RES-013", "facts": [], "sentences": ["RES-013.why.1"]}]}
EOF
python -m referee narrate report.json --llm-command "cat selection.json" --show-request > request.json
python -m referee narrate report.json --llm-command "cat selection.json"
```

The first `python` line starts nothing and leaves `request.json`. The second prints the page of the
summary with the `Chosen by` lines of the model path and, after the Decision block, a block for each
finding, which starts like this:

```text
RES-001 blocker: Sample ratio mismatch: the arms are not the size the allocation promised
Selected:
  [RES-001.why.2] A mismatch this large means the arms were not formed as designed (a fault in assignment, in logging or in filtering), so who is in each arm may differ and a difference in the metrics can come from that.
Not selected by the narrator:
  [RES-001.why.1] Random assignment gives arms of the registered sizes, up to chance.
  [RES-001.why.3] No estimate of the effect can be trusted until the cause is known.
```

Referee ships no wrapper for a provider, no default command, no environment variable that names one
and no `--model` option: a command that calls a model is yours to write and to run, with your
credentials in your environment. The model path has never been run with a model. It has met only
fake narrators and a stub command, a Python script, so whether a model returns a valid selection is
not known.

What is not covered: what `CMD` does with files or the network; a process it starts that leaves its
session; Referee itself being killed (SIGTERM or SIGKILL), which leaves the command running (Ctrl-C
stops the command). The command has no controlling terminal, as it has a session of its own.

## What it reads

Only `REPORT`: no other file, no network and no process, and the page depends on no environment
variable (argparse and the numeric libraries read some while the process starts); with
`--llm-command`, for a page that needs a narrator, the one process is the command. `REPORT` must be
a regular file (a directory, a FIFO or a device is refused) of at most 5 MiB (5,242,880 bytes) with
no repeated key, and must be a report that this build of Referee could have written. A report whose
counts, verdict, blocking rules or finding text disagree with its findings is refused with status 2.
A forged report that is consistent with itself passes (design section 24.13), and the check does not
type every field: a malformed field that it does not cover, such as an `experiment_id` that is a
number, ends in status 3, with the type of the exception only.

## The 5 MiB bound

The committed report is 80,422 bytes. The one part that grows with the players is the list of those
assigned before a registered start, `population.ignored_before_start`: 24 bytes a player for the
lab's ids (`player_0002757`), and 28 more when RES-003 raises a finding, because its evidence holds
the list again. Of a report the size of the committed one, (5,242,880 - 80,422) / 24 is about
215,000 such players, and (5,242,880 - 80,422) / 52 about 99,000 with the second copy. The bytes a
player were measured by adding 1,000 ids to the committed report and to one fixture, not to every
report, and a report with more arms or findings starts larger. A larger report is refused with `the
report is longer than 5,242,880 bytes`.
