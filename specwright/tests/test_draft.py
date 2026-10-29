"""A response is a draft only if every claim is well formed (strict parsing)."""

import copy
import json

import pytest

from specwright.draft import Draft, DraftError
from tests.helpers import claim, shop_draft


def with_claim(change) -> dict:
    data = shop_draft()
    change(data["claims"], data)
    return data


def set_(path: str, **fields):
    def apply(claims, _data):
        c = next(c for c in claims if c["path"] == path)
        for key, value in fields.items():
            if key in c["evidence"]:
                c["evidence"][key] = value
            else:
                c[key] = value

    return apply


def add(path: str, value, kind="inferred", **evidence):
    def apply(claims, _data):
        claims.append(
            {
                "path": path,
                "value": value,
                "evidence": {"kind": kind, "document": "", "quote": "", "note": "", **evidence},
            }
        )

    return apply


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        (add("design.nope", 1), "not a path a claim may use"),
        (add("arms[0].colour", "red"), "not a path a claim may use"),
        (add("design.alpha", 0.01), "stated twice"),
        (set_("design.alpha", value="0.05"), "must be a number value"),
        (set_("design.alpha", value=True), "must be a number value"),
        (set_("design.planned_duration_days", value=21.5), "must be a whole number"),
        (set_("design.sided", value="both"), "must be one of"),
        (set_("arms[0].is_control", value="yes"), "must be a boolean value"),
        (set_("owner", value=""), "must be a text value"),
        (set_("owner", value=None), "must be a text value"),
        (set_("design.alpha", quote=""), "needs the document's name and a quote"),
        (set_("design.alpha", kind="inferred"), "only document evidence has a document"),
        (set_("design.alpha", kind="missing", document="", quote=""), "has no value (null)"),
        (set_("design.alpha", kind="sometimes"), "evidence.kind must be one of"),
        (set_("design.alpha", value=float("inf")), "finite"),
        (set_("owner", value="x" * 1001), "longer than"),
        (add("arms[3].name", "d"), "indices must run 0, 1, 2"),
    ],
)
def test_a_malformed_claim_is_a_violation_that_names_it(change, fragment: str) -> None:
    with pytest.raises(DraftError) as raised:
        Draft.from_dict(with_claim(change))

    assert any(fragment in violation for violation in raised.value.violations)


@pytest.mark.parametrize(
    "change",
    [
        add("design.pre_period_covariate", None, kind="missing", note=""),
        add("design.start_utc", None, kind="ambiguous", note=""),
    ],
)
def test_a_missing_or_ambiguous_claim_must_say_what_to_ask(change) -> None:
    with pytest.raises(DraftError, match="needs a note saying what to ask"):
        Draft.from_dict(with_claim(change))


def test_every_violation_is_listed_not_only_the_first() -> None:
    data = shop_draft()
    data["claims"][0]["value"] = 5
    data["claims"][1]["path"] = "nope"
    data["extra"] = 1

    with pytest.raises(DraftError) as raised:
        Draft.from_dict(data)

    assert len(raised.value.violations) == 3


@pytest.mark.parametrize("text", ["not json", "[]", '{"claims": 3}', "{}"])
def test_a_response_that_is_not_a_draft_is_refused(text: str) -> None:
    with pytest.raises(DraftError):
        Draft.from_json(text)


def test_a_whole_number_written_as_a_float_is_read_as_an_integer() -> None:
    data = shop_draft()
    claim(data, "design.planned_duration_days")["value"] = 21.0

    draft = Draft.from_json(json.dumps(copy.deepcopy(data)))

    assert draft.by_path()["design.planned_duration_days"].value == 21
    assert isinstance(draft.by_path()["design.planned_duration_days"].value, int)
