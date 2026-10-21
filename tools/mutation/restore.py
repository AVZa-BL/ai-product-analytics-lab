"""usage: restore.py <project> <id> [<id> ...]   ids are full node ids or function ids (all cases of the function)
Moves those tests from `delete` to `kept_cases` in out/<project>/final.json and recomputes the derived lists."""
import collections, json, sys
from paths import OUT_ROOT  # noqa: E402
P, want = sys.argv[1], sys.argv[2:]
ids = json.load(open(f"{OUT_ROOT}/{P}/ids.json"))
f = f"{OUT_ROOT}/{P}/final.json"
d = json.load(open(f))
fn = lambda t: t.split("[")[0]
add = {t for t in ids if t in want or fn(t) in want}
assert add, "nothing matched"
kept = set(d["kept_cases"]) | add
fk = {fn(t) for t in kept}
d["kept_cases"] = sorted(kept)
d["delete"] = [t for t in ids if t not in kept]
d["delete_functions"] = [x for x in dict.fromkeys(fn(t) for t in ids) if x not in fk]
trim = collections.defaultdict(list)
for t in d["delete"]:
    if fn(t) in fk:
        trim[fn(t)].append(t)
d["trim"] = dict(trim)
d.setdefault("restored_by_review", [])
d["restored_by_review"] = sorted(set(d["restored_by_review"]) | add)
json.dump(d, open(f, "w"), indent=1)
print(f"restored {len(add)} tests; keep {len(kept)} of {len(ids)}")
