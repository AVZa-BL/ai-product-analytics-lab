"""usage: hold_eval.py <project> -> out/<project>/final.json (same schema as analysis.json) + printed report"""
import collections
import json
import sys

from paths import OUT_ROOT  # noqa: E402
P = sys.argv[1]
OUT, HO = f"{OUT_ROOT}/{P}", f"{OUT_ROOT}/{P}_hold"
an = json.load(open(f"{OUT}/analysis.json"))
ids = json.load(open(f"{OUT}/ids.json"))
idset = set(ids)
kept = set(an["kept_cases"])
mut = {m["id"]: m for m in json.load(open(f"{HO}/mutants.json"))}
res = {}
for l in open(f"{HO}/results.jsonl"):
    r = json.loads(l)
    res[r["id"]] = r


def fn(t):
    return t.split("[")[0]


killers = {}
st = collections.Counter()
for mid, m in mut.items():
    r = res.get(mid)
    if m["tests"] is None:
        st["uncovered"] += 1
    elif r is None:
        st["notrun"] += 1
    elif r["exit"] == "timeout":
        st["timeout"] += 1
    elif r["failed"] and any(t in idset for t in r["failed"]):
        killers[mid] = {t for t in r["failed"] if t in idset}
        st["killed_by_full_suite"] += 1
    elif r["exit"] == 0:
        st["survived"] += 1
    else:
        st["invalid"] += 1
print(P, dict(st))


def greedy(universe, sets):
    left, chosen = set(universe), []
    while left:
        best = max(sorted(sets), key=lambda k: len(sets[k] & left))
        gain = sets[best] & left
        if not gain:
            break
        chosen.append(best)
        left -= gain
    return chosen


def lost(ms, keptset):
    return {m for m in ms if not (killers[m] & keptset)}


def additions(ms, keptset):
    need = lost(ms, keptset)
    sets = collections.defaultdict(set)
    for m in need:
        for t in killers[m]:
            sets[t].add(m)
    return set(greedy(need, sets))


allm = sorted(killers)
lostm = lost(allm, kept)
print(f"hold-out faults caught by the full suite: {len(allm)}; by the reduced suite: {len(allm) - len(lostm)} "
      f"({100 * (len(allm) - len(lostm)) / max(1, len(allm)):.1f}%); missed by it: {len(lostm)}")
byk = collections.Counter(mut[m]["kind"] for m in lostm)
tot = collections.Counter(mut[m]["kind"] for m in allm)
print("  missed by kind:", {k: f"{byk[k]}/{tot[k]}" for k in tot})
# cross-validation: learn additions on half A, measure on half B (and the reverse)
for a_half in (0, 1):
    A = [m for i, m in enumerate(allm) if i % 2 == a_half]
    B = [m for i, m in enumerate(allm) if i % 2 != a_half]
    add = additions(A, kept)
    before = len(lost(B, kept))
    after = len(lost(B, kept | add))
    print(f"  cross-validation (learn on half {a_half}): +{len(add)} tests; missed on the unseen half "
          f"{before}/{len(B)} -> {after}/{len(B)}")
add = additions(allm, kept)
final = kept | add
print(f"adding {len(add)} tests back for the hold-out faults -> keep {len(final)} of {len(ids)}")
fn_kept = {fn(t) for t in final}
deleted = [t for t in ids if t not in final]
del_fns = [f for f in dict.fromkeys(fn(t) for t in ids) if f not in fn_kept]
trim = collections.defaultdict(list)
for t in deleted:
    if fn(t) in fn_kept:
        trim[fn(t)].append(t)
json.dump(dict(kept_cases=sorted(final), added_by_holdout=sorted(add), delete=deleted, delete_functions=del_fns,
               trim=dict(trim), still_missed=sorted(lost(allm, final))), open(f"{OUT}/final.json", "w"), indent=1)
print(f"final: delete {len(deleted)} tests = {len(del_fns)} whole functions + {sum(len(v) for v in trim.values())} rows in {len(trim)} kept functions")
