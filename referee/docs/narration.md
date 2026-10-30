# `referee narrate`

`python -m referee narrate REPORT [--question TEXT]` answers a question about a saved results report
in the engine's own sentences. No model runs and nothing leaves the machine. The page is advice, not
a gate.

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

Without `--question` the page is a summary of the review. A question is read by a router, a table of
words and not a model, into one of four kinds the layer answers about a report, one example each: a
summary (`What did the review find?`), one finding explained (`Why does RES-001 block the review?`),
what to do next (`What should we fix before running this again?`) and what was checked
(`Which checks did this review run?`). Anything else gets a refusal: a request for a decision or for
agreement, for the effect's numbers, a forecast, a breakdown the report does not hold, or a question
the router does not recognise. The three questions of the design are refused:

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
| 0 | A page was printed: an answer or a refusal, whatever the verdict. A refusal exits 0 on an `invalid` report, where `review-results` exits 1. |
| 2 | The report cannot be read, parsed or checked, or the arguments are unusable. The problems are on standard error: at most 1,000 are listed, with their exact number, and an arm's name is written as escapes. |
| 3 | Referee failed while making the page. Standard error names the exception's type; standard output is empty. |

Nothing is written to standard output until the page is complete. Statuses 1 and 4 are not used.

**Do not write `referee narrate report.json && ship`.** Status 0 means that a page was printed, not
that the experiment is valid or approved; every page ends by saying so.

## What it reads

Only `REPORT`: no other file, no environment variable, no network and no process. `REPORT` must be
a regular file (a directory, a FIFO or a device is refused) of at most 5 MiB (5,242,880 bytes) with
no repeated key, and must be a report that this build of Referee could have written: its counts, its
verdict and its blocking rules agree with its findings, and each finding has the catalogue's text.
A hand-edited report is refused with status 2, so a page never puts someone's words under the
engine's name.

There is no model path yet: a later step adds an optional `--llm-command`. Until it exists, nothing
leaves the machine.

## The 5 MiB bound

A report of 10 arms and 12 weeks is 0.76 MiB (a measurement of the pull request that added the
check, not repeated here), and the committed one is 80,422 bytes. The one part that grows with the
players is the list of those assigned before a registered start, `population.ignored_before_start`:
24 bytes a player for the lab's ids (`player_0002757`), and again in RES-003's evidence when that
rule raises a finding. About 185,000 such players fit, about half as many with the second copy. A
larger report is refused with `the report is longer than 5,242,880 bytes`.
