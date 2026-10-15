"""Mutation run with a full kill matrix.  usage: run.py <project> [--limit N] [--workers N]

Run it with a Python that has the project's dev extras and pytest-cov installed.
Writes $MUT_OUT (default <repo>/.mutation)/<project>/{contexts.json, mutants.json, results.jsonl}; resumable.
"""
import argparse
import concurrent.futures as cf
import glob
import json
import os
import shutil
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen  # noqa: E402
from paths import H, OUT_ROOT, PY, REPO  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("project")
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--workers", type=int, default=4)
ap.add_argument("--fresh", action="store_true")
ap.add_argument("--set", default="train")
ap.add_argument("--sample", type=int, default=0)
a = ap.parse_args()
P = a.project
OUT = f"{OUT_ROOT}/{P}" + ("" if a.set == "train" else "_" + a.set)
TRAIN = f"{OUT_ROOT}/{P}"
os.makedirs(OUT, exist_ok=True)
if a.set != "train":
    for f in ("ids.json", "contexts.json"):
        shutil.copy(f"{TRAIN}/{f}", f"{OUT}/{f}")
WORK = f"{OUT_ROOT}/work"


def sh(cmd, cwd, env=None, timeout=None):
    e = dict(os.environ, **(env or {}))
    return subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True, timeout=timeout)


def copy_tree(dst):
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(REPO, dst, ignore=shutil.ignore_patterns(
        ".git", ".mutation", "__pycache__", ".pytest_cache", ".ruff_cache", ".coverage", "*.egg-info", "node_modules"))


# 1. collection + per-test coverage contexts (serial, on a pristine copy)
ctx_path = f"{OUT}/contexts.json"
if a.fresh or not os.path.exists(ctx_path):
    base = f"{WORK}/base"
    copy_tree(base)
    proj = f"{base}/{P}"
    env = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": f"{proj}/src"}
    r = sh([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist", "--collect-only"], proj, env)
    ids = [l for l in r.stdout.splitlines() if "::" in l]
    json.dump(ids, open(f"{OUT}/ids.json", "w"))
    rc = f"{OUT_ROOT}/cov.rc"
    open(rc, "w").write("[run]\nbranch = False\n[json]\nshow_contexts = True\n")
    t0 = time.time()
    r = sh([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist", "--cov=src", f"--cov-config={rc}",
            "--cov-context=test", f"--cov-report=json:{ctx_path}", "--tb=short"], proj, env)
    print("baseline+coverage:", round(time.time() - t0), "s;", r.stdout.strip().splitlines()[-1])
    assert r.returncode == 0, r.stdout[-2000:]
ids = json.load(open(f"{OUT}/ids.json"))
cov = json.load(open(ctx_path))["files"]
by_file = {}
for i in ids:
    by_file.setdefault(i.split("::")[0], []).append(i)

# 2. mutants
mut_path = f"{OUT}/mutants.json"
if a.fresh or not os.path.exists(mut_path):
    mutants = []
    for f in sorted(glob.glob(f"{REPO}/{P}/src/**/*.py", recursive=True)):
        rel = os.path.relpath(f, f"{REPO}/{P}")
        if os.path.basename(f) == "__main__.py":
            continue
        for m in gen.generate(f, a.set):
            m["file"] = rel
            m["id"] = m["id"].replace(f, rel)
            fcov = cov.get(rel, {}).get("contexts", {})
            ctxs = fcov.get(str(m["line"]))
            if ctxs is None:
                m["tests"] = None          # statement never executed by any test
            else:
                t = sorted({c.split("|")[0] for c in ctxs if c})
                m["tests"] = t if t else "ALL"   # '' context = executed at import time
            mutants.append(m)
    if a.sample:
        import random
        random.Random(7).shuffle(mutants)
        mutants = mutants[:a.sample]
    json.dump(mutants, open(mut_path, "w"))
mutants = json.load(open(mut_path))
from collections import Counter  # noqa: E402
print("mutants:", len(mutants), dict(Counter("uncovered" if m["tests"] is None else "ALL" if m["tests"] == "ALL" else "sel" for m in mutants)))

todo = [m for m in mutants if m["tests"] is not None]
res_path = f"{OUT}/results.jsonl"
done = set()
if os.path.exists(res_path) and not a.fresh:
    done = {json.loads(l)["id"] for l in open(res_path)}
todo = [m for m in todo if m["id"] not in done]
if a.limit:
    todo = todo[:a.limit]
print("to run:", len(todo))

# 3. workers
q = list(todo)
lock = threading.Lock()
outf = open(res_path, "a")
counter = {"n": 0, "t0": time.time()}


def worker(w):
    root = f"{WORK}/w{w}"
    copy_tree(root)
    proj = f"{root}/{P}"
    orig_cache = {}
    env = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONPATH": f"{proj}/src:{H}", "PYTHONHASHSEED": "0"}
    while True:
        with lock:
            if not q:
                return
            m = q.pop(0)
        path = f"{proj}/{m['file']}"
        if path not in orig_cache:
            orig_cache[path] = open(path, "rb").read()
        orig = orig_cache[path]
        mutated = orig[:m["start"]] + m["repl"].encode() + orig[m["end"]:]
        open(path, "wb").write(mutated)
        t0 = time.time()
        try:
            if m["tests"] == "ALL":
                sel, files, tmo = None, ["tests"], 600
            else:
                files_set = sorted({t.split("::")[0] for t in m["tests"]})
                sel = sorted({i for f in files_set for i in by_file.get(f, [])})
                files, tmo = files_set, 180
            e = dict(env, KILL_OUT=f"{root}/kill.json")
            if sel is not None:
                json.dump(sel, open(f"{root}/sel.json", "w"))
                e["SEL_FILE"] = f"{root}/sel.json"
            if os.path.exists(f"{root}/kill.json"):
                os.remove(f"{root}/kill.json")
            try:
                r = sh([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist", "-p", "killrec",
                        "--tb=no", *files], proj, e, timeout=tmo)
                k = json.load(open(f"{root}/kill.json")) if os.path.exists(f"{root}/kill.json") else {"failed": [], "exit": r.returncode}
                rec = dict(id=m["id"], failed=k["failed"], exit=k["exit"], n=len(sel) if sel else len(ids))
            except subprocess.TimeoutExpired:
                rec = dict(id=m["id"], failed=[], exit="timeout", n=len(sel) if sel else len(ids))
        finally:
            open(path, "wb").write(orig)
        rec["secs"] = round(time.time() - t0, 2)
        with lock:
            outf.write(json.dumps(rec) + "\n")
            outf.flush()
            counter["n"] += 1
            if counter["n"] % 100 == 0:
                el = time.time() - counter["t0"]
                print(f"{counter['n']}/{len(todo)} done, {el:.0f}s, eta {el / counter['n'] * (len(todo) - counter['n']):.0f}s", flush=True)


with cf.ThreadPoolExecutor(a.workers) as ex:
    list(ex.map(worker, range(a.workers)))
print("finished", counter["n"], "in", round(time.time() - counter["t0"]), "s")
