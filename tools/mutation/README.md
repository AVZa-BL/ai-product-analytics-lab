# Mutation evidence for the test suites

Decides which tests are needed by breaking the source in small ways ("mutants") and recording
which tests fail for each. A test nothing else could replace stays; the rest are candidates for
removal. Stdlib only; run each tool with a Python that has the project's dev extras plus
`pytest-cov` (and `vulture` for `dead.py`), from the repository root. Results go to
`$MUT_OUT` (default `.mutation/`, git-ignored; it also holds copies of the repo, about 100 MB per worker).

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e 'referee[dev]' pytest-cov vulture            # per project: referee, tracewright, analytics-lab

python tools/mutation/run.py referee --workers 4            # mutants of src/ (hours); resumable
python tools/mutation/run.py referee --set hold --sample 700   # independent mutants, other operators
python tools/mutation/run.py referee --only guardrails --no-all   # one module family; skip import-time mutants (they need the whole suite)
MUT_PYTEST_ARGS="-o addopts=-ra -m study" python tools/mutation/run.py referee   # tests the project's addopts leave out (use another $MUT_OUT)
python tools/mutation/analyze.py referee                    # smallest covering set -> analysis.json
python tools/mutation/hold_eval.py referee                  # hold-out check + tests added back -> final.json
```

analytics-lab also has SQL models. Record which files each test opens, mutate those SQL files, and
combine the sets:

```bash
AUDIT_OUT=.mutation/analytics-lab/fileaudit.json PYTHONPATH=tools/mutation \
  python -m pytest -p fileaudit analytics-lab/tests         # run from analytics-lab/
python tools/mutation/gen_sql.py analytics-lab
python tools/mutation/run.py analytics-lab --set sql
python tools/mutation/union.py analytics-lab analytics-lab analytics-lab_sql --hold analytics-lab_hold
```

Referee's simulation studies carry the `study` marker, which its `pyproject.toml` leaves out of the
default run, so these tools do not run them. Tests that never fail for any mutant (`never_failed`
in `final.json`) check files, not code, so mutants cannot judge them. Judge each by hand: keep
one only if a realistic fault is caught by it, by no kept test, by the build-level check
(`dbt parse`, the CI scripts), and silently breaks something. `probe.py` runs one such fault
against the kept tests.

Applying the result: `delete_funcs.py` removes whole functions listed in `final.json`;
`mk_tasks.py` lists the parametrized rows left to remove; `check_apply.py` compares a file's collected
tests with the plan; `restore.py` moves tests back into the kept set; `dead.py` removes helpers that
nothing references any more (it leaves decorated functions, i.e. fixtures, alone).
Then confirm with `verify.py <project> [--set sql] --sample 400`: every sampled mutant the old suite
caught must still be caught.

What it cannot see: faults of a kind the mutation operators do not generate (a measured 2-4% of an
independent sample), SQL models no test touches, and anything outside the files it mutates.
