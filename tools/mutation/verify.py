"""After the deletions: are the killed mutants still killed by the REDUCED suite?
usage: verify.py <project> [--sample N] [--workers N]     (uses the working tree as it is now)
"""
import argparse
import collections
import concurrent.futures as cf
import json
import os
import random
import shutil
import subprocess
import threading

from paths import H, OUT_ROOT, PY, REPO  # noqa: E402
ap = argparse.ArgumentParser()
ap.add_argument("project")
ap.add_argument("--sample", type=int, default=0, help="0 = every killed mutant")
ap.add_argument("--workers", type=int, default=4)
ap.add_argument("--set", default="")
a = ap.parse_args()
P = a.project
OUT = f"{OUT_ROOT}/{P}"
MUT = OUT + ("_" + a.set if a.set else "")
mutants = {m["id"]: m for m in json.load(open(f"{MUT}/mutants.json"))}
old_ids = set(json.load(open(f"{OUT}/ids.json")))
res = {}
for l in open(f"{MUT}/results.jsonl"):
    r = json.loads(l)
    res[r["id"]] = r
killed = [m for m, r in res.items() if r["failed"] and any(t in old_ids for t in r["failed"])]
random.Random(1).shuffle(killed)
if a.sample:
    killed = killed[:a.sample]


def copy_tree(dst):
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(REPO, dst, ignore=shutil.ignore_patterns(
        ".git", ".mutation", "__pycache__", ".pytest_cache", ".ruff_cache", ".coverage", "*.egg-info", "node_modules"))


base = f"{OUT_ROOT}/work/vbase"
copy_tree(base)
env0 = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": f"{base}/{P}/src"}
r = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist", "--collect-only"],
                   cwd=f"{base}/{P}", env=dict(os.environ, **env0), capture_output=True, text=True)
new_ids = [l for l in r.stdout.splitlines() if "::" in l]
by_file = collections.defaultdict(list)
for i in new_ids:
    by_file[i.split("::")[0]].append(i)
print(f"reduced suite: {len(new_ids)} tests; verifying {len(killed)} killed mutants")
q, lock, lost, done = list(killed), threading.Lock(), [], [0]


def worker(w):
    root = f"{OUT_ROOT}/work/v{w}"
    copy_tree(root)
    proj = f"{root}/{P}"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=f"{proj}/src:{H}", PYTHONHASHSEED="0",
               KILL_OUT=f"{root}/k.json", SEL_FILE=f"{root}/s.json")
    while True:
        with lock:
            if not q:
                return
            mid = q.pop()
        m = mutants[mid]
        path = f"{proj}/{m['file']}"
        orig = open(path, "rb").read()
        open(path, "wb").write(orig[:m["start"]] + m["repl"].encode() + orig[m["end"]:])
        try:
            if m["tests"] == "ALL":
                files, sel = ["tests"], new_ids
            else:
                files = sorted({t.split("::")[0] for t in m["tests"]})
                sel = [i for f in files for i in by_file.get(f, [])]
                files = sorted({i.split("::")[0] for i in sel})
            failed = []
            if sel:
                json.dump(sel, open(f"{root}/s.json", "w"))
                if os.path.exists(f"{root}/k.json"):
                    os.remove(f"{root}/k.json")
                try:
                    subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist", "-p", "killrec",
                                    "--tb=no", *files], cwd=proj, env=env, capture_output=True, text=True, timeout=600)
                    failed = json.load(open(f"{root}/k.json"))["failed"] if os.path.exists(f"{root}/k.json") else []
                except subprocess.TimeoutExpired:
                    failed = ["timeout"]
        finally:
            open(path, "wb").write(orig)
        with lock:
            done[0] += 1
            if not failed:
                lost.append(dict(id=mid, kind=m["kind"], file=m["file"], line=m["at"], old=m["old"], new=m["new"]))
            if done[0] % 200 == 0:
                print(done[0], "checked,", len(lost), "no longer killed", flush=True)


with cf.ThreadPoolExecutor(a.workers) as ex:
    list(ex.map(worker, range(a.workers)))
json.dump(lost, open(f"{MUT}/verify_lost.json", "w"), indent=1)
print(f"{P}: {len(killed) - len(lost)}/{len(killed)} killed mutants are still killed; {len(lost)} lost")
for x in lost[:30]:
    print("  LOST", x)
