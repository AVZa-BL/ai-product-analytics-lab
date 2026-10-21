"""pytest plugin: record, per test, the non-Python files it opens under the current directory -> $AUDIT_OUT."""
import collections
import json
import os
import sys

ROOT = os.getcwd()
cur = [None]
opened = collections.defaultdict(set)


def hook(event, args):
    if event == "open" and cur[0] and args and isinstance(args[0], (str, bytes, os.PathLike)):
        try:
            ap = os.path.abspath(os.fsdecode(args[0]))
        except Exception:
            return
        if ap.startswith(ROOT + os.sep) and not ap.endswith((".py", ".pyc", ".so")) and "__pycache__" not in ap \
                and "/data/" not in ap and "/target/" not in ap and "/logs/" not in ap:
            opened[cur[0]].add(os.path.relpath(ap, ROOT))


sys.addaudithook(hook)


def pytest_runtest_setup(item):
    cur[0] = item.nodeid


def pytest_runtest_logfinish(nodeid, location):
    cur[0] = None


def pytest_sessionfinish(session, exitstatus):
    out = os.environ.get("AUDIT_OUT")
    if out:
        json.dump({k: sorted(v) for k, v in opened.items()}, open(out, "w"))
