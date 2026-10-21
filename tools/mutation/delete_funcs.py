"""Remove whole test functions listed in analysis.json['delete_functions'] (and their decorators and the
comment block directly above them).  usage: delete_funcs.py <project> <repo root> [--final final_delete_functions.json]
Prints, per file, how many functions were removed.  Then run `ruff check --select F401 --fix` on the files.
"""
import ast
import collections
import json
import os
import re
import sys

from paths import OUT_ROOT  # noqa: E402
P, root = sys.argv[1], sys.argv[2]
src = f"{OUT_ROOT}/{P}/analysis.json"
if "--final" in sys.argv:
    src = sys.argv[sys.argv.index("--final") + 1]
dels = json.load(open(src))["delete_functions"]
per = collections.defaultdict(set)
for d in dels:
    parts = d.split("::")
    per[parts[0]].add(tuple(parts[1:]))
total = 0
for f, wanted in sorted(per.items()):
    path = os.path.join(root, P, f)
    text = open(path, encoding="utf-8").read()
    lines = text.splitlines(keepends=True)
    tree = ast.parse(text)
    cut = []

    def visit(body, prefix):
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and (*prefix, n.name) in wanted:
                first = min([n.lineno] + [d.lineno for d in n.decorator_list]) - 1
                while first > 0 and lines[first - 1].lstrip().startswith("#"):   # comment block right above
                    first -= 1
                cut.append((first, n.end_lineno))
            elif isinstance(n, ast.ClassDef):
                visit(n.body, (*prefix, n.name))
    visit(tree.body, ())
    for a, b in sorted(cut, reverse=True):
        del lines[a:b]
    new = "".join(lines)
    new = re.sub(r"\n{4,}", "\n\n\n", new)
    ast.parse(new)
    open(path, "w", encoding="utf-8").write(new)
    total += len(cut)
    print(f"{f}: removed {len(cut)}/{len(wanted)} functions")
print("total removed", total)
