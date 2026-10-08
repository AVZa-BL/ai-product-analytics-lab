"""Rules about what the data of a finished experiment shows (RES).

The data-fit rules of design section 21.4 arrive here one at a time; the effect rules follow
in the next change. A rule reads a `ResultsContext` and returns the evidence that triggered it.
"""

from __future__ import annotations

from referee.results import ResultsContext
from referee.rules.base import Rule

RESULTS_RULES: tuple[Rule[ResultsContext], ...] = ()
