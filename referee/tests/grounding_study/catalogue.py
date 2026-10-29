"""The 81 sentences of the nine results rules, frozen "as of 8a7119b" and pinned by SHA-256.

The study reads only `catalogue.json`. `live_catalogue` rebuilds the same dictionary from the rules
now in `src/` so that a test can say when they have moved apart; it is also what
`python tests/grounding_study/run.py --refreeze AS_OF` writes. Sentences end at `.`, `!` or `?`
followed by white space and a capital letter, and are keyed `RES-001.title`, `RES-001.why.1` (from
`why_it_matters`) and `RES-001.do.2` (from `remediation`), as in design section 24.4.
"""

import hashlib
import json
import re
from pathlib import Path

from referee.rules import RESULTS_RULES

FROZEN = Path(__file__).resolve().parent / "catalogue.json"
FROZEN_SHA256 = "2f8689de5634620d51d0330cbceda78479299e8ece32465346abb7b9083b98be"
SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def live_catalogue(rules=RESULTS_RULES) -> dict[str, str]:
    sentences = {}
    for rule in rules:
        sentences[f"{rule.id}.title"] = rule.title
        for kind, text in (("why", rule.why_it_matters), ("do", rule.remediation)):
            for number, sentence in enumerate(SPLIT.split(text), 1):
                sentences[f"{rule.id}.{kind}.{number}"] = sentence
    return sentences


def frozen_text(sentences: dict[str, str], as_of: str) -> str:
    return json.dumps({"as_of": as_of, "sentences": sentences}, indent=1) + "\n"


def load_frozen(path: Path = FROZEN, sha256: str = FROZEN_SHA256) -> tuple[str, dict[str, str]]:
    """The label and sentences of the frozen file, refused unless its digest is the pinned one."""
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError(f"{path.name} is not the frozen file: its SHA-256 differs from the pin")
    frozen = json.loads(data)
    return frozen["as_of"], frozen["sentences"]


def differences(frozen: dict[str, str], live: dict[str, str]) -> list[str]:
    """The IDs missing from one side or worded differently on the two."""
    return sorted(i for i in frozen.keys() | live.keys() if frozen.get(i) != live.get(i))
