"""SQL mutants for the SQL files that tests open.  usage: gen_sql.py <project>  -> out/<project>_sql/mutants.json"""
import json, os, re, sys, collections
P = sys.argv[1]
from paths import OUT_ROOT, REPO  # noqa: E402
OUT = f"{OUT_ROOT}/{P}_sql"
os.makedirs(OUT, exist_ok=True)
audit = json.load(open(f"{OUT_ROOT}/{P}/fileaudit.json"))
ids = set(json.load(open(f"{OUT_ROOT}/{P}/ids.json")))
by_file = collections.defaultdict(set)
for t, fs in audit.items():
    for f in fs:
        if f.endswith(".sql"):
            by_file[f].add(t)
TOK = re.compile(r"""
 (?P<jinja>\{\{.*?\}\}|\{%.*?%\}|\{\#.*?\#\})
|(?P<lc>--[^\n]*)
|(?P<bc>/\*.*?\*/)
|(?P<str>'(?:[^']|'')*')
|(?P<qid>"[^"]*")
|(?P<num>\d+(?:\.\d+)?)
|(?P<word>[A-Za-z_][A-Za-z_0-9]*)
|(?P<op><=|>=|<>|!=|=>|->|::|\|\||[<>=+\-*/%(),.;])
|(?P<ws>\s+)
|(?P<other>.)
""", re.X | re.S)
FLIP = {"<": "<=", "<=": "<", ">": ">=", ">=": ">", "=": "<>", "<>": "=", "!=": "="}
out = []
for f, tests in sorted(by_file.items()):
    path = f"{REPO}/{P}/{f}"
    text = open(path, encoding="utf-8").read()
    b = text.encode()
    toks = []
    for m in TOK.finditer(text):
        k = m.lastgroup
        if k in ("ws", "lc", "bc"):
            continue
        toks.append((k, m.group(), len(text[:m.start()].encode()), len(text[:m.end()].encode())))
    n0 = len(out)
    def add(kind, s, e, repl, line_src):
        if b[s:e].decode() == repl:
            return
        ln = b[:s].count(b"\n") + 1
        out.append(dict(file=f, line=ln, at=ln, start=s, end=e, repl=repl, kind=kind, old=b[s:e].decode()[:60], new=repl[:60],
                        tests=sorted(tests), id=f"{f}:{ln}:{s}:{kind}:{len(out)}"))
    for i, (k, v, s, e) in enumerate(toks):
        lv = v.lower()
        prev = toks[i - 1] if i else None
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        if k == "op" and v in FLIP:
            add("cmp", s, e, FLIP[v], f)
        elif k == "op" and v in "+-" and prev and (prev[0] in ("num", "word", "str", "qid") or prev[1] == ")"):
            add("arith", s, e, "-" if v == "+" else "+", f)
        elif k == "op" and v in "*/" and prev and (prev[0] in ("num", "word") or prev[1] == ")"):
            add("arith", s, e, "/" if v == "*" else "*", f)
        elif k == "word" and lv in ("and", "or"):
            add("bool", s, e, "or" if lv == "and" else "and", f)
        elif k == "word" and lv == "is" and nxt and nxt[1].lower() == "null":
            add("null", s, nxt[3], "is not null", f)
        elif k == "word" and lv == "is" and nxt and nxt[1].lower() == "not" and i + 2 < len(toks) and toks[i + 2][1].lower() == "null":
            add("null", s, toks[i + 2][3], "is null", f)
        elif k == "word" and lv in ("left", "inner") and nxt and nxt[1].lower() in ("join", "outer"):
            add("join", s, e, "inner" if lv == "left" else "left", f)
        elif k == "word" and lv == "distinct" and prev and prev[1] == "(":
            add("distinct", s, e, "", f)
        elif k == "word" and lv in ("min", "max") and nxt and nxt[1] == "(":
            add("minmax", s, e, "max" if lv == "min" else "min", f)
        elif k == "word" and lv in ("asc", "desc"):
            add("order", s, e, "desc" if lv == "asc" else "asc", f)
        elif k == "word" and lv == "all" and prev and prev[1].lower() == "union":
            add("union", prev[2], e, "union", f)
        elif k == "num" and not (prev and prev[1] == "."):
            val = float(v) if "." in v else int(v)
            add("num", s, e, (str(val + 1) if val != 0 else "1"), f)
        elif k == "str" and len(v) > 2:
            add("str", s, e, "'XX" + v[1:-1] + "XX'", f)
    # drop strings immediately inside jinja already skipped (jinja is one opaque token)
print(len(out), dict(collections.Counter(m["kind"] for m in out)), "files:", len(by_file))
json.dump(out, open(f"{OUT}/mutants.json", "w"))
import shutil
for fn in ("ids.json", "contexts.json"):
    shutil.copy(f"{OUT_ROOT}/{P}/{fn}", f"{OUT}/{fn}")
tot = collections.Counter(len(set(m["tests"])) for m in out)
print("selected tests per mutant (distribution of counts):", sorted(tot.items())[:12])
