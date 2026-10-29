"""Builders shared by the Specwright tests."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from tracewright.propose.documents import Document, load_documents

ROOT = Path(__file__).resolve().parent.parent
BRIEFS = ROOT / "examples" / "briefs"
REPLAYS = ROOT / "examples" / "replays"
SHOP = "01-shop-banner"


def documents(*names: str) -> tuple[Document, ...]:
    return load_documents([str(BRIEFS / f"{name}.md") for name in names])


def replay(name: str) -> Any:
    return json.loads((REPLAYS / f"{name}.json").read_text(encoding="utf-8"))


def shop_draft() -> dict[str, Any]:
    """The shop-banner draft (a copy, so a test may change it)."""
    return copy.deepcopy(replay(SHOP))


def claim(draft: dict[str, Any], path: str) -> dict[str, Any]:
    return next(c for c in draft["claims"] if c["path"] == path)


def without(draft: dict[str, Any], *paths: str) -> dict[str, Any]:
    draft["claims"] = [c for c in draft["claims"] if c["path"] not in paths]
    return draft


def text_document(name: str, text: str) -> Document:
    """A text document that is not a file, for a test that needs particular wording."""
    return Document(name=name, kind="text", text=text, data=None, sha256="0" * 64)
