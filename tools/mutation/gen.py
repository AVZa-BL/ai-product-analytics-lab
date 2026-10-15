"""Generate source mutants (text-span replacements) for one Python file.

Each mutant: {id, file, line (enclosing statement's first line), start, end (byte offsets), repl, kind, old, new}
"""
import ast
import re

CMP = {
    ast.Lt: ("<=", r"<(?!=)"), ast.LtE: ("<", r"<="), ast.Gt: (">=", r">(?!=)"), ast.GtE: (">", r">="),
    ast.Eq: ("!=", r"=="), ast.NotEq: ("==", r"!="), ast.Is: ("is not", r"\bis\b(?!\s+not\b)"),
    ast.IsNot: ("is", r"\bis\s+not\b"), ast.In: ("not in", r"\bin\b"), ast.NotIn: ("in", r"\bnot\s+in\b"),
}
BIN = {
    ast.Add: ("-", r"\+"), ast.Sub: ("+", r"-"), ast.Mult: ("/", r"\*(?!\*)"), ast.Div: ("*", r"/(?!/)"),
    ast.FloorDiv: ("/", r"//"), ast.Mod: ("*", r"%"), ast.Pow: ("*", r"\*\*"),
}


HBIN = {
    ast.Add: ("*", r"\+"), ast.Sub: ("*", r"-"), ast.Mult: ("+", r"\*(?!\*)"), ast.Div: ("-", r"/(?!/)"),
    ast.FloorDiv: ("*", r"//"), ast.Mod: ("+", r"%"), ast.Pow: ("+", r"\*\*"),
}


def generate(path: str, mode: str = "train"):
    src = open(path, encoding="utf-8").read()
    b = src.encode("utf-8")
    tree = ast.parse(src)
    starts, pos = [], 0
    for ln in b.splitlines(keepends=True):
        starts.append(pos)
        pos += len(ln)
    starts.append(pos)

    def off(line, col):
        return starts[line - 1] + col

    def span(n):
        return off(n.lineno, n.col_offset), off(n.end_lineno, n.end_col_offset)

    parent = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            parent[c] = n

    def stmt_line(n):
        while n is not None and not isinstance(n, ast.stmt):
            n = parent.get(n)
        return n.lineno if n is not None else 1

    def in_annotation(n):
        c = n
        while c in parent:
            p = parent[c]
            if (isinstance(p, ast.arg) and p.annotation is c) or (isinstance(p, ast.AnnAssign) and p.annotation is c) \
                    or (isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)) and p.returns is c):
                return True
            c = p
        return False

    out = []

    def add(n, kind, s, e, repl):
        old = b[s:e].decode("utf-8", "replace")
        if old == repl:
            return
        mutated = b[:s] + repl.encode("utf-8") + b[e:]
        try:
            ast.parse(mutated.decode("utf-8"))
        except SyntaxError:
            return
        out.append(dict(file=path, line=stmt_line(n), start=s, end=e, repl=repl, kind=kind,
                        old=old[:80], new=repl[:80], at=n.lineno))

    def gap_sub(s, e, rx, repl, n, kind):
        seg = b[s:e].decode("utf-8", "replace")
        m = re.search(rx, seg)
        if not m:
            return
        # byte offset of match inside the gap
        bs = s + len(seg[:m.start()].encode("utf-8"))
        be = s + len(seg[:m.end()].encode("utf-8"))
        add(n, kind, bs, be, repl)

    for n in ast.walk(tree):
        if mode != "train" or in_annotation(n):
            continue
        if isinstance(n, ast.Compare):
            left = n.left
            for op, comp in zip(n.ops, n.comparators):
                repl, rx = CMP[type(op)]
                gap_sub(off(left.end_lineno, left.end_col_offset), off(comp.lineno, comp.col_offset), rx, repl, n, "cmp")
                left = comp
        elif isinstance(n, ast.BinOp) and type(n.op) in BIN:
            if isinstance(n.op, ast.Mod) and isinstance(n.left, ast.Constant) and isinstance(n.left.value, str):
                continue
            repl, rx = BIN[type(n.op)]
            gap_sub(off(n.left.end_lineno, n.left.end_col_offset), off(n.right.lineno, n.right.col_offset), rx, repl, n, "arith")
        elif isinstance(n, ast.BoolOp):
            word, other = ("and", "or") if isinstance(n.op, ast.And) else ("or", "and")
            for a, c in zip(n.values, n.values[1:]):
                gap_sub(off(a.end_lineno, a.end_col_offset), off(c.lineno, c.col_offset), rf"\b{word}\b", other, n, "bool")
        elif isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
            s, e = span(n.operand)
            add(n, "not", *span(n), "(" + b[s:e].decode() + ")")
        elif isinstance(n, (ast.If, ast.While, ast.IfExp)):
            s, e = span(n.test)
            add(n, "cond", s, e, "not (" + b[s:e].decode() + ")")
        elif isinstance(n, ast.Return) and n.value is not None and not (
                isinstance(n.value, ast.Constant) and n.value.value is None):
            add(n, "return", *span(n.value), "None")
        elif isinstance(n, ast.Expr) and isinstance(n.value, ast.Call):
            add(n, "stmt", *span(n), "pass")
        elif isinstance(n, ast.JoinedStr):
            if not isinstance(parent.get(n), ast.JoinedStr) and not isinstance(parent.get(n), ast.FormattedValue):
                add(n, "fstr", *span(n), repr("XX"))
        elif isinstance(n, ast.Constant):
            v = n.value
            p = parent.get(n)
            if isinstance(p, (ast.JoinedStr, ast.FormattedValue)) or (isinstance(p, ast.Expr)):
                continue
            if isinstance(v, bool):
                add(n, "bool_const", *span(n), "False" if v else "True")
            elif isinstance(v, (int, float)):
                add(n, "num", *span(n), repr(v + 1) if v != 0 else "1")
            elif isinstance(v, str) and v != "":
                add(n, "str", *span(n), repr("XX" + v + "XX"))
    for n in ast.walk(tree):
        if mode != "hold" or in_annotation(n):
            continue
        if isinstance(n, ast.Compare):
            flip = {ast.Lt: ">", ast.LtE: ">=", ast.Gt: "<", ast.GtE: "<="}
            rxs = {ast.Lt: r"<(?!=)", ast.LtE: r"<=", ast.Gt: r">(?!=)", ast.GtE: r">="}
            left = n.left
            for op, comp in zip(n.ops, n.comparators):
                if type(op) in flip:
                    gap_sub(off(left.end_lineno, left.end_col_offset), off(comp.lineno, comp.col_offset),
                            rxs[type(op)], flip[type(op)], n, "h_cmp")
                left = comp
        elif isinstance(n, ast.BinOp) and type(n.op) in HBIN:
            if isinstance(n.op, ast.Mod) and isinstance(n.left, ast.Constant) and isinstance(n.left.value, str):
                continue
            repl, rx = HBIN[type(n.op)]
            gap_sub(off(n.left.end_lineno, n.left.end_col_offset), off(n.right.lineno, n.right.col_offset), rx, repl, n, "h_arith")
        elif isinstance(n, ast.AugAssign) and type(n.op) in (ast.Add, ast.Sub):
            s0, e0 = span(n.value)
            seg_s = off(n.target.end_lineno, n.target.end_col_offset)
            gap_sub(seg_s, s0, r"\+=" if isinstance(n.op, ast.Add) else r"-=", "-=" if isinstance(n.op, ast.Add) else "+=", n, "h_aug")
        elif isinstance(n, ast.BoolOp) and len(n.values) == 2:
            add(n, "h_bool_first", *span(n), b[span(n.values[0])[0]:span(n.values[0])[1]].decode())
            add(n, "h_bool_last", *span(n), b[span(n.values[1])[0]:span(n.values[1])[1]].decode())
        elif isinstance(n, (ast.If, ast.While, ast.IfExp)):
            add(n, "h_true", *span(n.test), "True")
            add(n, "h_false", *span(n.test), "False")
        elif isinstance(n, ast.Return) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, bool):
            add(n, "h_retbool", *span(n.value), "False" if n.value.value else "True")
        elif isinstance(n, ast.Constant):
            v = n.value
            p = parent.get(n)
            if isinstance(p, (ast.JoinedStr, ast.FormattedValue, ast.Expr)):
                continue
            if isinstance(v, bool):
                continue
            if isinstance(v, int):
                add(n, "h_int", *span(n), repr(v - 1))
            elif isinstance(v, float):
                add(n, "h_float", *span(n), repr(v * 2) if v != 0 else "-1.0")
            elif isinstance(v, str) and v != "":
                add(n, "h_str", *span(n), '""')
    for i, m in enumerate(out):
        m["id"] = f"{path}:{m['at']}:{m['start']}:{m['kind']}:{i}"
    return out


if __name__ == "__main__":
    import sys
    ms = generate(sys.argv[1])
    from collections import Counter
    print(len(ms), Counter(m["kind"] for m in ms))
