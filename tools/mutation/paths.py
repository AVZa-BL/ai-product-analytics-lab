"""Where things are: the repository, the output folder, and the Python that runs the tests."""

import os
import shlex
import sys

H = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(H))
OUT_ROOT = os.environ.get("MUT_OUT", os.path.join(REPO, ".mutation"))  # results; git-ignored
PY = sys.executable  # run the tools with the Python that has the project's dev extras and pytest-cov
# Extra pytest options for every run, e.g. MUT_PYTEST_ARGS="-o addopts=-ra" to include tests the project's own
# defaults leave out, or "-m study" to run only those.
PYTEST_ARGS = shlex.split(os.environ.get("MUT_PYTEST_ARGS", ""))
