"""Check that a test file now collects exactly the intended tests.

usage: check_apply.py <project> <test file relative to project> <repo root>
Compares `pytest --collect-only` for that file with out/<project>/ids.json minus analysis.json['delete'].
Parametrize ids that carry an auto index (e.g. 'case3') may renumber after rows are removed, so
ids are also compared with digits masked; prints MISSING (should exist) and EXTRA (should be gone).
"""
import json
import os
import re
import subprocess
import sys

from paths import OUT_ROOT, PY  # noqa: E402
P, f, root = sys.argv[1:4]
out = f"{OUT_ROOT}/{P}"
ids = json.load(open(f"{out}/ids.json"))
delete = set(json.load(open(f"{out}/final.json" if os.path.exists(f"{out}/final.json") else f"{out}/analysis.json"))["delete"])
want = {t for t in ids if t.startswith(f + "::") and t not in delete}
proj = os.path.join(root, P)
r = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist",
                    "--collect-only", f], cwd=proj, capture_output=True, text=True,
                   env=dict(os.environ, PYTHONPATH=f"{proj}/src"))
have = {l for l in r.stdout.splitlines() if "::" in l}
mask = lambda s: re.sub(r"\d+", "#", s)
miss = sorted(t for t in want - have if mask(t) not in {mask(h) for h in have})
extra = sorted(t for t in have - want if t in delete or mask(t) not in {mask(w) for w in want})
if r.returncode not in (0, 5) and not have:
    print("COLLECTION ERROR:\n", r.stdout[-1500:], r.stderr[-800:])
    sys.exit(2)
print(json.dumps(dict(expected=len(want), collected=len(have), MISSING=miss, EXTRA=extra), indent=1))
sys.exit(1 if miss or extra else 0)
