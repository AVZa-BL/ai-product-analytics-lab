"""The tokeniser, the loaded-word list and the function words of the grounding study.

A token is a chunk of the text between spaces and hyphens, lower-cased, with the punctuation
`. , ; : ! ? ( ) [ ] "` taken off both ends. A chunk of letters and apostrophes is a word and is
folded (`fold`); a chunk that holds anything else, a digit or a symbol (`%`, `_`, an inner `.`,
any character outside a to z), is a MARKER token and is left as it is. The checker rejects every
text that holds a marker, under every view: neither a digit nor a symbol can be typed into model
text in this design. What a view decides is whether a marker in a catalogue sentence loads it.
A token that holds a digit (0 to 9) is loaded under every view, whatever the list says: a number,
a rate or a rule ID is a claim of its own. A token that holds a symbol and no digit (a field name
such as `min_duration_days`, an inner `.`) is loaded under the full list only, where every
sentence is loaded anyway (the count is 0 whichever way a symbol is treated); under the two
ablations it is not, so that "digits only" means what it says.

The loaded words are the words that carry a decision, a condition, a negation, a modal, a limit, a
quantity, a comparison, a certainty, a cause, a severity or verdict, a unit, a position, an arm or
an ordinal. They are stored in the folded form the tokeniser produces (a trailing plural s is
folded, so `perhaps` is `perhap`). The list is one agent's judgement, written to be short rather
than complete: from the categories, cut for length, then read once against the sentences that the
qualifiers view left free. That read added `minimum`, `maximum`, `limit` and `part` (the last for
`part-way`, which the tokeniser splits); `minimum` and `part` took the count of those sentences
from 11 to 8. The contractions and four degree words were added then for coverage and moved no
count. A phrase such as `up to` or `at least` is not recognised, only its words. A view is a set
of categories:

  full        every category, and the markers (digits and symbols)
  qualifiers  negation, condition, limiter and modal, and the digit tokens
  digits      the digit tokens only
"""

import hashlib
import re

LOADED: dict[str, tuple[str, ...]] = {
    "negation": tuple(
        """no not never none nothing neither nor without cannot can't don't doesn't didn't isn't
        aren't wasn't weren't won't wouldn't shouldn't couldn't hasn't haven't lack absent missing
        miss unable fail failed failure""".split()
    ),
    "condition": tuple(
        """if unless until when whenever whether while once where otherwise else although though
        but however then assume depend either or""".split()
    ),
    "limiter": tuple(
        """only alone just merely solely except instead rather mostly mainly largely partly part
        somewhat slightly nearly almost roughly about around enough too very exactly entirely even
        minimum maximum limit""".split()
    ),
    "modal": tuple(
        """can could may might must should will would need require allow able possible impossible
        perhap maybe likely unlikely probably""".split()
    ),
    "decision": tuple(
        """decide decided decision ship launch stop stopped call continue proceed
        keep drop dropped reject accept approve adopt choose choice select pick conclude
        conclusion recommend advice register registered plan planned restart rerun fix correct
       """.split()
    ),
    "quantity": tuple(
        """zero one two three four five six seven hundred thousand million half
        double twice all every each any some many much few several both whole total average mean
        count rate share ratio percentage size sample number amount n estimate interval value
        power tolerance threshold pooled per""".split()
    ),
    "comparison": tuple(
        """more less most least fewer larger largest smaller smallest higher highest lower lowest
        greater better worse worst best large small high low than as like same equal unequal
        differ different difference compare comparison versus against relative exceed increase
        decrease rise fall reduce cut lift gain change changed shift drift reverse close match
        mismatch""".split()
    ),
    "certainty": tuple(
        """certain uncertain unclear unreliable unknown evidence proof prove show shown say tell
        indicate suggest imply seem appear know known noise chance reliable trust true false real
        actual exact rough measure measured""".split()
    ),
    "cause": tuple(
        """cause caused because since due why reason therefore thus hence so result lead led drive
        produce explain effect impact affect influence trigger triggered tied""".split()
    ),
    "verdict": tuple(
        """blocker block warning info finding verdict invalid valid caution clear pass breach harm
        harmful risk problem issue error wrong bad good win success severe serious fine
        acceptable safe flag significant significance underpowered""".split()
    ),
    "unit": tuple(
        """minute hour day week month year time period duration window cycle percent player user
        device session cluster unit event purchase revenue spend spent""".split()
    ),
    "position": tuple(
        """in on at over under above below before after between within beyond from to into
        through out up begin began start end side partway late early during point""".split()
    ),
    "arm": tuple(
        """arm control variant treatment group cohort population segment allocation assign
        assignment assigned bucket expose exposed exposure random randomisation
        randomization""".split()
    ),
    "ordinal": tuple(
        """first second third last next previous final initial earlier later primary
        secondary""".split()
    ),
}

VIEWS: dict[str, tuple[str, ...]] = {
    "full": tuple(LOADED),
    "qualifiers": ("negation", "condition", "limiter", "modal"),
    "digits": (),
}

# The only words a text may add to the words of the sentences it cites. None of them is a
# position, direction or comparison word, and none is a pronoun or conjunction that carries a
# negation or a quantity.
FUNCTION_WORDS: tuple[str, ...] = tuple(
    """a an the is are was were be been being do did have has had of for with and that which who
    it its this these those they their them we our you your there such""".split()
)

_CHUNK_EDGE = '.,;:!?()[]"'
_WORD = re.compile(r"[a-z']+")
_DIGIT = re.compile(r"[0-9]")


def fold(word: str) -> str:
    """A word as the lists store it: no edge apostrophes, no possessive, no trailing plural s."""
    word = word.strip("'")
    if word.endswith("'s"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def is_marker(token: str) -> bool:
    """A token that holds a digit or a symbol, that is, anything but letters and apostrophes."""
    return _WORD.fullmatch(token) is None


def has_digit(token: str) -> bool:
    return _DIGIT.search(token) is not None


def tokens(text: str) -> list[str]:
    out = []
    for chunk in text.lower().replace("-", " ").split():
        chunk = chunk.strip(_CHUNK_EDGE)
        chunk = chunk if is_marker(chunk) else fold(chunk)
        if chunk:
            out.append(chunk)
    return out


def loaded_words(view: str) -> frozenset[str]:
    return frozenset(word for category in VIEWS[view] for word in LOADED[category])


def loaded_tokens(text: str, view: str) -> list[str]:
    """The tokens of `text` that are loaded under `view`, in order."""
    words = loaded_words(view)
    marked = is_marker if view == "full" else has_digit  # a symbol alone loads under "full" only
    return [t for t in tokens(text) if marked(t) or t in words]


def is_free(text: str, view: str) -> bool:
    return not loaded_tokens(text, view)


def lexicon_sha256() -> str:
    """The digest of the list: its categories in order, each with its words sorted."""
    lines = (f"{name}: {' '.join(sorted(LOADED[name]))}" for name in LOADED)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
