"""Try ONE hand-made mutant and report which kept / candidate tests notice it.

usage: probe.py <project> --root <repo checkout> --file <path relative to project> --old TEXT --new TEXT
                [--occurrence N] [--tests nodeid ...]      (default: all kept + the candidates of --cand-file)
Replaces the N-th (default 1st) exact occurrence of TEXT in the file, runs the tests, restores the file.
Prints JSON: {kept_failing, candidate_failing, other_failing, applied}.
"""
import argparse
import json
import os
import subprocess
import sys

from paths import H, OUT_ROOT, PY  # noqa: E402
ap = argparse.ArgumentParser()
ap.add_argument("project")
ap.add_argument("--root", required=True)
ap.add_argument("--file", required=True)
ap.add_argument("--old", required=True)
ap.add_argument("--new", required=True)
ap.add_argument("--occurrence", type=int, default=1)
ap.add_argument("--candidates", nargs="*", default=None, help="candidate node ids (default: all deletion candidates)")
a = ap.parse_args()

out = f"{OUT_ROOT}/{a.project}"
an = json.load(open(f"{out}/final.json" if os.path.exists(f"{out}/final.json") else f"{out}/analysis.json"))
kept, cands = set(an["kept_cases"]), set(an["delete"])
run = sorted(kept | (set(a.candidates) if a.candidates else cands))
proj = os.path.join(a.root, a.project)
path = os.path.join(proj, a.file)
orig = open(path, encoding="utf-8").read()
idx, start = -1, 0
for _ in range(a.occurrence):
    idx = orig.find(a.old, start)
    if idx < 0:
        print(json.dumps({"applied": False, "error": f"occurrence {a.occurrence} of the text not found"}))
        sys.exit(1)
    start = idx + 1
mutated = orig[:idx] + a.new + orig[idx + len(a.old):]
try:
    if path.endswith(".py"):
        compile(mutated, path, "exec")
except SyntaxError as e:
    print(json.dumps({"applied": False, "error": f"mutant does not compile: {e}"}))
    sys.exit(1)
sel = os.path.join(proj, ".probe_sel.json")
killf = os.path.join(proj, ".probe_kill.json")
json.dump(run, open(sel, "w"))
files = sorted({t.split("::")[0] for t in run})
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=f"{proj}/src:{H}", SEL_FILE=sel, KILL_OUT=killf)
open(path, "w", encoding="utf-8").write(mutated)
try:
    subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist",
                    "-p", "killrec", "--tb=no", *files], cwd=proj, env=env, capture_output=True, text=True, timeout=900)
    failed = set(json.load(open(killf))["failed"]) if os.path.exists(killf) else set()
finally:
    open(path, "w", encoding="utf-8").write(orig)
    for f in (sel, killf):
        if os.path.exists(f):
            os.remove(f)
print(json.dumps(dict(applied=True, kept_failing=sorted(failed & kept), candidate_failing=sorted(failed & cands),
                      other_failing=sorted(failed - kept - cands)), indent=1))
