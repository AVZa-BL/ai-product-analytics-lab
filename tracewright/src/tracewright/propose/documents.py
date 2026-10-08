"""Read the documents a proposal is based on.

Documents are untrusted input: a design document may be pasted from anywhere, and it ends up in
a prompt. Loading therefore refuses rather than repairs (no truncation, no guessing an encoding,
no unknown formats) and records a SHA-256 of every file so a report states exactly what was read.

Text formats are read as UTF-8 and handed to the model as text, which also lets the evidence check
search them. PDFs are handed over as PDF documents; they cannot be searched, so quotes from them
are reported as unverifiable, not as verified.
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

TEXT_SUFFIXES = frozenset(
    {".md", ".markdown", ".txt", ".rst", ".csv", ".tsv", ".json", ".yaml", ".yml"}
)
PDF_SUFFIX = ".pdf"

MAX_TEXT_BYTES = 2_000_000
MAX_PDF_BYTES = 20_000_000
MAX_TOTAL_BYTES = 20_000_000
MAX_DOCUMENTS = 20

_UNSAFE_NAME = re.compile(r'[\x00-\x1f\x7f"\\<>]')


class DocumentError(ValueError):
    """A document cannot be used. The message names the file and what to do about it."""


@dataclass(frozen=True, kw_only=True)
class Document:
    name: str
    kind: Literal["text", "pdf"]
    text: str | None
    data: bytes | None
    sha256: str

    @property
    def size(self) -> int:
        return len(self.data) if self.data is not None else len((self.text or "").encode("utf-8"))

    def pdf_base64(self) -> str:
        if self.data is None:
            raise DocumentError(f"{self.name}: not a PDF")
        return base64.standard_b64encode(self.data).decode("ascii")


def load_document(path: str | Path) -> Document:
    """Read one document. Raises DocumentError for anything it will not guess about."""
    file = Path(path)
    if _UNSAFE_NAME.search(file.name):
        raise DocumentError(
            f"{file}: the file name contains a control character, quote, backslash, < or >; "
            "the name is quoted in the prompt and in evidence, so rename the file"
        )
    suffix = file.suffix.lower()
    if suffix not in TEXT_SUFFIXES and suffix != PDF_SUFFIX:
        allowed = ", ".join(sorted(TEXT_SUFFIXES | {PDF_SUFFIX}))
        raise DocumentError(
            f"{file}: unsupported format {suffix or '(no extension)'!r}; "
            f"supported: {allowed}. Convert other formats (for example .docx) to text or PDF first"
        )
    try:
        raw = file.read_bytes()
    except OSError as error:
        raise DocumentError(f"{file}: cannot be read: {error.strerror or error}") from error
    digest = hashlib.sha256(raw).hexdigest()
    if not raw.strip():
        raise DocumentError(f"{file}: is empty")

    if suffix == PDF_SUFFIX:
        if len(raw) > MAX_PDF_BYTES:
            raise DocumentError(
                f"{file}: is {len(raw):,} bytes; the limit for a PDF is {MAX_PDF_BYTES:,}"
            )
        if not raw.startswith(b"%PDF-"):
            raise DocumentError(f"{file}: does not look like a PDF (no %PDF- header)")
        return Document(name=file.name, kind="pdf", text=None, data=raw, sha256=digest)

    if len(raw) > MAX_TEXT_BYTES:
        raise DocumentError(
            f"{file}: is {len(raw):,} bytes; the limit for a text document is {MAX_TEXT_BYTES:,}. "
            "Split it, or pass only the sections about the feature (Tracewright never truncates)"
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise DocumentError(
            f"{file}: not valid UTF-8 (at byte offset {error.start}); re-save it as UTF-8"
        ) from error
    if "\x00" in text:
        raise DocumentError(f"{file}: contains NUL characters; it is not a text document")
    return Document(name=file.name, kind="text", text=text, data=None, sha256=digest)


def load_documents(paths: list[str] | tuple[str, ...]) -> tuple[Document, ...]:
    """Read several documents, in the order given, checking the set as a whole."""
    if not paths:
        raise DocumentError("at least one document is required (--doc PATH)")
    if len(paths) > MAX_DOCUMENTS:
        raise DocumentError(f"{len(paths)} documents given; the limit is {MAX_DOCUMENTS}")
    documents = tuple(load_document(path) for path in paths)
    names = [document.name for document in documents]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise DocumentError(
            f"two documents are named {repeated}; evidence is cited by file name, so give "
            "each document a distinct file name"
        )
    total = sum(document.size for document in documents)
    if total > MAX_TOTAL_BYTES:
        raise DocumentError(
            f"the documents total {total:,} bytes; the limit is {MAX_TOTAL_BYTES:,}"
        )
    return documents
