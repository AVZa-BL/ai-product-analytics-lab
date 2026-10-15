"""Where things are: the repository, the output folder, and the Python that runs the tests."""

import os
import sys

H = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(H))
OUT_ROOT = os.environ.get("MUT_OUT", os.path.join(REPO, ".mutation"))  # results; git-ignored
PY = sys.executable  # run the tools with the Python that has the project's dev extras and pytest-cov
