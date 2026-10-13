# Decision memo

A decision memo separates what was observed from what is inferred, and states the boundary
of both. Every `##` heading in this file is required: the enforcement test parses them out
of this template and asserts each published memo carries them, so adding a heading here
makes it mandatory for every memo in the repository.

Scenarios add sections of their own and should. The live-strategy memo adds an inference
section and recommended next actions; the hybrid memo adds an executive summary, an
interpretation section and a recommended experiment. Those are deliberately absent from
this file so that they stay optional.

## Decision

The decision and who it binds. State what is being decided now and what is explicitly not
being decided. A recommendation to withhold, or to run an experiment first, is a decision.

## Observed facts

Values copied from the committed results artifact, not recalculated in prose. Name the
artifact. Where a governed mart publishes the number, copy it rather than restating it at
different precision.

## Assumptions and uncertainty

The population, eligibility and maturity rules the numbers depend on. Intervals, and what
they do and do not cover. Selection, confounding, and any respect in which the estimand is
narrower than it appears. State the direction of a suspected bias where it is arguable
from structure, and say plainly when it is not quantified.

## Data-quality qualification

Known defects, their containment, and what containment does not establish. Contained is
not the same as absent.

## Reproducibility

Input relations, the executable analysis, the results artifact, the code version and
execution timestamp, the runtime, and any seed. Enough that a reader can rebuild the
numbers and get the same answer.
