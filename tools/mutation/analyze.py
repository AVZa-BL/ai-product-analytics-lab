"""usage: analyze.py <project>  -> out/<project>/{analysis.json, summary.txt}"""
import collections
import json
import sys

from paths import OUT_ROOT  # noqa: E402
P = sys.argv[1]
OUT = f"{OUT_ROOT}/{P}"
ids = json.load(open(f"{OUT}/ids.json"))
idset = set(ids)
mutants = {m["id"]: m for m in json.load(open(f"{OUT}/mutants.json"))}
results = {}
for line in open(f"{OUT}/results.jsonl"):
    r = json.loads(line)
    results[r["id"]] = r

status = {}
killers = {}
for mid, m in mutants.items():
    if m["tests"] is None:
        status[mid] = "uncovered"
        continue
    r = results.get(mid)
    if r is None:
        status[mid] = "notrun"
    elif r["exit"] == "timeout":
        status[mid] = "timeout"
    elif r["failed"]:
        status[mid] = "killed"
        killers[mid] = {t for t in r["failed"] if t in idset}
        if not killers[mid]:
            status[mid] = "invalid"      # failures not attributable to a collected test
    elif r["exit"] == 0:
        status[mid] = "survived"
    else:
        status[mid] = "invalid"
cnt = collections.Counter(status.values())


def fn(t):
    return t.split("[")[0]


def greedy(universe, sets):
    universe = set(universe)
    chosen = []
    left = set(universe)
    while left:
        best = max(sorted(sets), key=lambda k: len(sets[k] & left))
        gain = sets[best] & left
        if not gain:
            break
        chosen.append(best)
        left -= gain
    return chosen


U = {m for m, s in status.items() if s == "killed"}
# function level
fsets = collections.defaultdict(set)
for m in U:
    for t in killers[m]:
        fsets[fn(t)].add(m)
kept_fns = set(greedy(U, fsets))
# case level, restricted to the kept functions
csets = collections.defaultdict(set)
for m in U:
    for t in killers[m]:
        if fn(t) in kept_fns:
            csets[t].add(m)
kept_cases = set(greedy(U, csets))
all_fns = collections.OrderedDict((fn(t), None) for t in ids)
deleted = [t for t in ids if t not in kept_cases]
del_fns = [f for f in all_fns if f not in {fn(t) for t in kept_cases}]
trim = collections.defaultdict(list)       # kept function -> cases to drop
for t in deleted:
    if fn(t) in kept_fns:
        trim[fn(t)].append(t)

# which candidates ever failed for any mutant (for the evidence trail)
ever = collections.Counter()
for m in U:
    for t in killers[m]:
        ever[t] += 1
unique = collections.Counter()
for m in U:
    if len(killers[m]) == 1:
        unique[next(iter(killers[m]))] += 1

by_file = collections.defaultdict(lambda: dict(total=0, kept=0, kept_functions=0))
for t in ids:
    by_file[t.split("::")[0]]["total"] += 1
for t in kept_cases:
    by_file[t.split("::")[0]]["kept"] += 1

surv = collections.defaultdict(list)
for mid, s in status.items():
    if s in ("survived", "uncovered", "timeout"):
        m = mutants[mid]
        surv[m["file"]].append(dict(line=m["at"], kind=m["kind"], old=m["old"], new=m["new"], status=s))

json.dump(dict(
    status=dict(cnt), tests=len(ids), kept_cases=sorted(kept_cases), kept_functions=sorted(kept_fns),
    delete=deleted, delete_functions=del_fns, trim={k: v for k, v in trim.items()},
    killed_by_n={t: ever[t] for t in ids}, unique_kills={t: unique[t] for t in ids if unique[t]},
    survivors=surv, by_file=by_file), open(f"{OUT}/analysis.json", "w"), indent=1)
lines = [f"{P}: tests {len(ids)} -> keep {len(kept_cases)} ({len(kept_fns)} functions); delete {len(deleted)} "
         f"({len(del_fns)} whole functions, {sum(len(v) for v in trim.values())} parametrized cases in kept functions)",
         f"mutants: {dict(cnt)}"]
for f, d in sorted(by_file.items()):
    lines.append(f"  {f}: {d['total']} -> {d['kept']}")
open(f"{OUT}/summary.txt", "w").write("\n".join(lines))
print("\n".join(lines))
