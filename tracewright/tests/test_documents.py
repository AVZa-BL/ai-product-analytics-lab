import pytest

from tracewright.propose.documents import (
    MAX_DOCUMENTS,
    MAX_TEXT_BYTES,
    DocumentError,
    load_document,
    load_documents,
)


def test_a_text_document_is_read_and_hashed(tmp_path):
    f = tmp_path / "gdd.md"
    f.write_text("# Title\nBody\n", encoding="utf-8")
    d = load_document(f)
    assert d.kind == "text" and d.text == "# Title\nBody\n" and d.name == "gdd.md"
    assert len(d.sha256) == 64


def test_a_utf8_bom_is_tolerated(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"\xef\xbb\xbfhello")
    assert load_document(f).text == "hello"


def test_a_pdf_is_kept_as_bytes(tmp_path):
    f = tmp_path / "gdd.pdf"
    f.write_bytes(b"%PDF-1.7\n...")
    d = load_document(f)
    assert d.kind == "pdf" and d.text is None and d.pdf_base64().startswith("JVBERi")


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("a.docx", b"PK", "unsupported format"),
        ("a", b"x", "unsupported format"),
        ("a.md", b"", "is empty"),
        ("a.md", b"   \n", "is empty"),
        ("a.md", b"\xff\xfe\xfa", "not valid UTF-8"),
        ("a.md", b"ab\x00cd", "NUL"),
        ("a.pdf", b"not a pdf", "does not look like a PDF"),
    ],
)
def test_documents_that_cannot_be_used_are_refused(tmp_path, name, content, message):
    f = tmp_path / name
    f.write_bytes(content)
    with pytest.raises(DocumentError, match=message):
        load_document(f)


def test_a_missing_file_is_refused(tmp_path):
    with pytest.raises(DocumentError, match="cannot be read"):
        load_document(tmp_path / "nope.md")


def test_an_oversized_document_is_refused_not_truncated(tmp_path):
    f = tmp_path / "big.md"
    f.write_bytes(b"x" * (MAX_TEXT_BYTES + 1))
    with pytest.raises(DocumentError, match="never truncates"):
        load_document(f)


def test_a_set_of_documents_needs_distinct_names_and_a_sane_size(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    one, two = tmp_path / "a" / "gdd.md", tmp_path / "b" / "gdd.md"
    one.write_text("one")
    two.write_text("two")
    with pytest.raises(DocumentError, match="distinct file name"):
        load_documents([str(one), str(two)])
    with pytest.raises(DocumentError, match="at least one"):
        load_documents([])
    many = []
    for i in range(MAX_DOCUMENTS + 1):
        f = tmp_path / f"d{i}.md"
        f.write_text("x")
        many.append(str(f))
    with pytest.raises(DocumentError, match="limit"):
        load_documents(many)


@pytest.mark.parametrize("name", ['a"b.md', "a<b>.md", "a\\b.md", "a\nb.md"])
def test_a_file_name_that_could_confuse_the_prompt_is_refused(tmp_path, name):
    f = tmp_path / name
    try:
        f.write_text("hello")
    except OSError:
        pytest.skip("the file system cannot hold this name")
    with pytest.raises(DocumentError, match="file name"):
        load_document(f)
