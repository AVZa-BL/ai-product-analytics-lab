"""Remove top-level helpers/constants in tests/ that nothing references.  usage: dead.py <project dir>  (needs vulture)"""
import ast, re, subprocess, sys, os
proj = sys.argv[1]
total = 0
for _ in range(6):
    out = subprocess.run([sys.executable, "-m", "vulture", "tests", "--min-confidence", "60"], cwd=proj, capture_output=True, text=True).stdout
    items = []
    for l in out.splitlines():
        m = re.match(r"(tests/[^:]+):(\d+): unused (variable|function|class) '([^']+)'", l)
        if m and not m.group(4).startswith("test_"):
            f, ln, kind, name = m.groups()
            # truly unreferenced anywhere in tests/ or src/
            r = subprocess.run(["grep", "-rIw", "--include=*.py", "--", name, "tests", "src"], cwd=proj, capture_output=True, text=True)
            if len(r.stdout.strip().splitlines()) == 1:
                items.append((f, name))
    if not items:
        break
    byf = {}
    for f, n in items:
        byf.setdefault(f, set()).add(n)
    for f, names in byf.items():
        p = os.path.join(proj, f)
        text = open(p, encoding="utf-8").read()
        lines = text.splitlines(keepends=True)
        tree = ast.parse(text)
        cut = []
        for n in tree.body:
            nm = None
            if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and not n.decorator_list:  # fixtures are decorated
                nm = n.name
            elif isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                nm = n.targets[0].id
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                nm = n.target.id
            if nm in names:
                first = min([n.lineno] + [d.lineno for d in getattr(n, "decorator_list", [])]) - 1
                while first > 0 and lines[first - 1].lstrip().startswith("#"):
                    first -= 1
                cut.append((first, n.end_lineno, nm))
        for a, b, nm in sorted(cut, reverse=True):
            del lines[a:b]
            total += 1
            print("removed", f, nm)
        new = re.sub(r"\n{4,}", "\n\n\n", "".join(lines))
        ast.parse(new)
        open(p, "w", encoding="utf-8").write(new)
print("total", total)
