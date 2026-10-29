"""Writes docs/grounding-study.md and .json, or re-freezes the catalogue (design section 24.12).

    python tests/grounding_study/run.py                    # the two documents, from the frozen file
    python tests/grounding_study/run.py --refreeze AS_OF   # catalogue.json from the live rules

After a re-freeze, put the SHA-256 it prints in `catalogue.FROZEN_SHA256` and run the first
command again.
"""

import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grounding_study import catalogue  # noqa: E402
from grounding_study.study import documents  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--refreeze", metavar="AS_OF", help="rewrite catalogue.json from the rules")
    args = parser.parse_args(argv)
    if args.refreeze:
        text = catalogue.frozen_text(catalogue.live_catalogue(), args.refreeze)
        catalogue.FROZEN.write_text(text, encoding="utf-8")
        print(f"FROZEN_SHA256 = {hashlib.sha256(text.encode()).hexdigest()!r}")
        return
    for path, text in documents().items():
        path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
