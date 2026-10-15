"""usage: union.py <project> <set1> [<set2> ...] --hold <holdset>
Cover over the union of several mutant sets (e.g. analytics-lab analytics-lab_sql), then add back tests for the
independent hold-out faults.  Writes out/<project>/final.json (same schema as hold_eval.py) and prints the report.
"""
import collections
import json
import sys

from paths import OUT_ROOT  # noqa: E402
args = sys.argv[1:]
P = args[0]
hold = args[args.index("--hold") + 1]
sets = [a for a in args[1:] if a != "--hold" and a != hold]
ids = json.load(open(f"{OUT_ROOT}/{P}/ids.json"))
idset = set(ids)
fn = lambda t: t.split("[")[0]


def load(setname):
    muts = {m["id"]: m for m in json.load(open(f"{OUT_ROOT}/{setname}/mutants.json"))}
    res = {}
    for l in open(f"{OUT_ROOT}/{setname}/results.jsonl"):
        r = json.loads(l)
        res[r["id"]] = r
    killers, cnt = {}, collections.Counter()
    for mid, m in muts.items():
        r = res.get(mid)
        if m["tests"] is None:
            cnt["uncovered"] += 1
        elif r is None:
            cnt["notrun"] += 1
        elif r["exit"] == "timeout":
            cnt["timeout"] += 1
        elif r["failed"] and any(t in idset for t in r["failed"]):
            killers[f"{setname}|{mid}"] = {t for t in r["failed"] if t in idset}
            cnt["killed"] += 1
        elif r["exit"] == 0:
            cnt["survived"] += 1
        else:
            cnt["invalid"] += 1
    return muts, killers, cnt


def greedy(universe, sets_):
    left, chosen = set(universe), []
    while left:
        best = max(sorted(sets_), key=lambda k: len(sets_[k] & left))
        gain = sets_[best] & left
        if not gain:
            break
        chosen.append(best)
        left -= gain
    return chosen


killers, report = {}, {}
for s in sets:
    _, k, c = load(s)
    killers.update(k)
    report[s] = dict(c)
print("mutant sets:", report)
U = set(killers)
fs = collections.defaultdict(set)
for m in U:
    for t in killers[m]:
        fs[fn(t)].add(m)
kept_fns = set(greedy(U, fs))
cs = collections.defaultdict(set)
for m in U:
    for t in killers[m]:
        if fn(t) in kept_fns:
            cs[t].add(m)
kept = set(greedy(U, cs))
print(f"cover over {len(U)} killed mutants: keep {len(kept)} of {len(ids)} tests")

# independent hold-out
hm, hk, hc = load(hold)
hall = sorted(hk)
def lost(ms, keptset): return {m for m in ms if not (hk[m] & keptset)}
miss = lost(hall, kept)
print(f"hold-out {dict(hc)}: reduced suite catches {len(hall) - len(miss)}/{len(hall)} "
      f"({100 * (len(hall) - len(miss)) / max(1, len(hall)):.1f}%)")
need = lost(hall, kept)
hs = collections.defaultdict(set)
for m in need:
    for t in hk[m]:
        hs[t].add(m)
add = set(greedy(need, hs))
final = kept | add
print(f"adding {len(add)} tests for the hold-out misses -> keep {len(final)} of {len(ids)}")

ever = set()
for m in killers:
    ever |= killers[m]
for m in hk:
    ever |= hk[m]
fk = {fn(t) for t in final}
deleted = [t for t in ids if t not in final]
del_fns = [f for f in dict.fromkeys(fn(t) for t in ids) if f not in fk]
trim = collections.defaultdict(list)
for t in deleted:
    if fn(t) in fk:
        trim[fn(t)].append(t)
never = [t for t in deleted if t not in ever]
redundant = [t for t in deleted if t in ever]
print(f"deleted {len(deleted)}: {len(redundant)} are redundant (they killed mutants, others kill them too), "
      f"{len(never)} never failed for any mutant")
json.dump(dict(kept_cases=sorted(final), added_by_holdout=sorted(add), delete=deleted, delete_functions=del_fns,
               trim=dict(trim), never_failed=never, redundant=redundant), open(f"{OUT_ROOT}/{P}/final.json", "w"), indent=1)
by = collections.Counter(t.split("/")[1] if t.count("/") else t for t in never)
print("never-failed tests by folder:", dict(by))
