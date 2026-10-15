import collections, json, sys
from paths import OUT_ROOT  # noqa: E402
P = sys.argv[1]
d = json.load(open(f"{OUT_ROOT}/{P}/final.json"))
ids = json.load(open(f"{OUT_ROOT}/{P}/ids.json"))
fn = lambda t: t.split("[")[0]
kept = set(d["kept_cases"])
by_file = collections.defaultdict(list)
for f, rm in d["trim"].items():
    keep = [t.split("::", 1)[1] for t in ids if fn(t) == f and t in kept]
    by_file[f.split("::")[0]].append(dict(function=f.split("::", 1)[1], remove=[t.split("::", 1)[1] for t in rm], keep=keep))
tasks = [dict(project=P, file=f, functions=v) for f, v in sorted(by_file.items())]
json.dump(tasks, open(f"{OUT_ROOT}/{P}/trim_tasks.json", "w"))
print(P, len(tasks), "files;", sum(len(t["functions"]) for t in tasks), "functions;", sum(len(x["remove"]) for t in tasks for x in t["functions"]), "rows;", len(json.dumps(tasks)), "bytes")
