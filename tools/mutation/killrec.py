"""pytest plugin: restrict the run to the node ids in $SEL_FILE and write the failing node ids to $KILL_OUT."""
import json
import os

_failed = []


def pytest_collection_modifyitems(config, items):
    p = os.environ.get("SEL_FILE")
    if not p:
        return
    allowed = set(json.load(open(p)))
    keep = [i for i in items if i.nodeid in allowed]
    gone = [i for i in items if i.nodeid not in allowed]
    if gone:
        config.hook.pytest_deselected(items=gone)
    items[:] = keep


def pytest_runtest_logreport(report):
    if report.failed:
        _failed.append(report.nodeid)


def pytest_sessionfinish(session, exitstatus):
    out = os.environ.get("KILL_OUT")
    if out:
        json.dump({"failed": sorted(set(_failed)), "exit": int(exitstatus)}, open(out, "w"))
