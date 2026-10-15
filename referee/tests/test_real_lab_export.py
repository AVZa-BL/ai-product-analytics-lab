"""Referee against real lab output: the 5,000-player experiment, read from the committed CSVs.

The files in tests/data/hybrid_offer_page_5000 were written by DuckDB from the lab's generator
(seed 42; see PROVENANCE.md there), so these tests run on the format the lab produces and on the
planted problems the results rules will have to find, in CI and without the lab installed. The
figures are the ones the lab's readout document publishes, plus the cohort and version patterns
that design section 20.4 states.
"""

import json
import shutil
from pathlib import Path

import pytest

from referee import data
from referee.data import ExperimentData, load_export

FIXTURE = Path(__file__).parent / "data" / "hybrid_offer_page_5000"
EXPERIMENT = "hybrid_offer_page"
MANIFEST = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def export() -> ExperimentData:
    return load_export(FIXTURE, EXPERIMENT)


def _weeks(export: ExperimentData, *, by: str) -> dict[str, int]:
    """Weeks since the first assignment, by the week of assignment or of first exposure."""
    start = min(a.assigned_at for a in export.assignments)
    if by == "assignment":
        return {a.player_id: (a.assigned_at - start).days // 7 for a in export.assignments}
    first: dict[str, object] = {}
    for exposure in export.exposures:  # already ordered by player and time
        first.setdefault(exposure.player_id, exposure.exposed_at)
    return {player: (moment - start).days // 7 for player, moment in first.items()}


# --- The files themselves ----------------------------------------------------------------


def test_a_cut_through_the_last_line_of_the_real_exposures_is_refused(tmp_path: Path) -> None:
    for name in MANIFEST["files"]:
        shutil.copy(FIXTURE / name, tmp_path / name)
    path = tmp_path / data.EXPOSURES_FILE
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    path.write_text("".join(lines[:-1]) + "exposure_0003974,hybrid_", encoding="utf-8")

    with pytest.raises(data.DataError) as caught:
        load_export(tmp_path, EXPERIMENT)

    assert caught.value.problems == (
        "experiment_exposures.csv:3975: the file ends in the middle of a row "
        "(fewer fields than the header)",
    )
    assert data.list_experiment_ids(tmp_path) == (EXPERIMENT,)


# --- The planted problems, as the lab's readout document states them ----------------------


# --- What section 21 (Amendment 6) quotes from this export ---------------------------------


