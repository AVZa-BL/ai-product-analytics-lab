"""The router of the narration layer (design section 24.8): what a question is, and no word of it.

`route(question)` is a pure function that returns the `Understanding` of `render.py`; the page
prints that and never the question. Four steps, all linear in the length of the question:

1. Normalise: NFKC of the case-folded NFKC text, then each of U+0020, tab, line feed, carriage
   return and the categories Zs, Zl and Zp is one space and a run of spaces is one.
2. Unreadable (a decision of form): empty, over 500 characters, no letter, a character of
   category C or M (so no invisible character can split a word), or a word that mixes Latin
   letters with Cyrillic or Greek ones. The reason is one of `render.UNREADABLE_REASONS`.
3. Match. The words of the question are the runs of letters and digits (an apostrophe joins its
   neighbours, `re-run` is one word), with `^` before the first, `$` after the last, `,` for a
   clause boundary and `#` for a rule ID (`RES-004`, `res 004`, `ZZZ-123`). A pattern is a short
   sequence of steps: `(2, "call* declare*", "it this test")` is call or declare, or a word that
   begins so, then it, this or test, with at most two words between. A word ending in `*` is a
   prefix; an integer sets the number of words that may lie between a step and the one before it,
   for the steps that follow (0 when none is given). A pattern is matched by dynamic programming
   over the positions of the words, one pass for each step, so the time is linear in the question
   and nothing backtracks. The tables are data.
4. Decide. A refusal category beats an intent, and the categories matched are listed in the order
   of `render.CATEGORIES` (the order of precedence); then the intents (`checked`, `next_steps`,
   an explanation of a rule named, `summary`); then the default route. A question that matches a
   category and an intent is a refusal that keeps the intent, so that the refusal can say that an
   answerable part was not answered; a refusal keeps an explanation only for a rule ID written in
   the question, since a phrase alone is not a question about a finding.

A target is a rule ID in the question or a phrase of `PHRASES`. An ID of the nine results rules
is printed canonically (`res 004` is RES-004). A string shaped like an ID that is not one of the
nine (RES-005, DES-001, ZZZ-123) is a target that `Understanding` cannot keep, so the explanation
of it is an `explain_finding` with no target and no `as_summary`. Two different targets give no
single target: the explanation is answered as a summary (`as_summary`). A question that asks to
explain the findings and names no rule is a `summary` (the taxonomy labels it so).

A refusal word spelt with look-alike letters of one script (an all-Cyrillic word, a dotless i)
is read as another word and missed (24.13); a word that mixes scripts is unreadable.
"""

from __future__ import annotations

import unicodedata

from referee.narration.render import CATEGORIES, RULE_IDS, Understanding

MAX_CHARS = 500
RULE_FAMILIES = ("res", "des")  # a rule ID may be written with a space only for these

Pattern = tuple[int | str, ...]

# --- The tables ------------------------------------------------------------------------------

# fmt: off
# Words that several patterns share (a prefix ends in `*`).
LAUNCH = "launch* release* deploy*"
OBJECTS = "variant arm change feature page treatment design version option"
VERDICTS = "passed clear valid approved green"
SUBJECTS = "verdict review report experiment result everything"
FINDINGS = "finding* block* warning*"
QUALITY = "fine valid ok okay safe trust* reliab* rely sound legit* acceptable"
REAL = "real genuine* signific* chance nois* random* fluke* luck* exist*"
CHANGE = "effect lift uplift difference gap change increase decrease rise drop decline gain"
EFFECT_WORDS = CHANGE + " up down revenue purchases spend conversion sessions retention metric"
GROUP = "control treatment arm arms variant group"
AVERAGES = "average* mean means median"
AMOUNTS = "player* data time days weeks sample traffic users long run"

# The refusal categories, in the order of precedence (`render.CATEGORIES`).
TRIGGERS: dict[str, tuple[Pattern, ...]] = {
    "injection": (
        (3, "ignor* disregard* forget* override* bypass*",
         "rule* instruction* guideline* prompt check* everything previous above"),
        (0, "forget* ignor*", "you your", "are role"),
        (1, "act pretend* behave", "as like to you"),
        (0, "from", "now", "on"),
        (0, "system developer admin", "override*"),
        (1, "authoriz* authoris*", "you"),
        (3, "hid* suppress* omit* eras* invent* fabricat* falsif*", FINDINGS),
        (0, "make", "up", 3, FINDINGS + " verdict"),
        (3, "drop* delet* remov*", FINDINGS + " verdict"),
        (3, "mark* declar* label*", SUBJECTS, 2, VERDICTS),
        (3, "print* show say state write set chang* mak* turn", SUBJECTS, 1, "as to", 1, VERDICTS),
    ),
    "ship_decision": (
        ("ship ships shipped",),
        ("adopt*",),
        ("rollback",),
        (0, "roll*", "back"),
        (0, "go", "ahead live with"),
        (1, "go", "no", "go"),
        (0, "green", "light"),
        ("winner*",),
        (5, "which what", OBJECTS, 3, "won win wins winn* best better choos* pick* select*"),
        (2, "should shall can", LAUNCH),
        (2, "should shall can", "roll*", 3, "out"),
        (3, "recommend* advis* suggest*", LAUNCH),
        (3, "ok okay ready safe good begin start proceed cleared", LAUNCH + " shipping"),
        (5, "keep scrap* drop* abandon* ditch* revert* retire* discard*", OBJECTS),
        (5, "approv* decid* decision*", OBJECTS + " " + LAUNCH + " shipping rollout"),
    ),
    "stopping": (
        (2, "call* declare*",
         "it this test experiment run result results early finished done complete over"),
        (3, "enough", AMOUNTS + " read conclude"),
        (3, AMOUNTS, "enough"),
        ("sufficient* adequate*",),
        (1, "too", "early soon"),
        ("premature*",),
        ("stop* halt*",),
        ("extend* prolong* longer",),
        ("wait*",),
        ("peek*",),
        (1, "another more additional", "week* day* month* player* data"),
        (2, "continu*", "running collecting"),
        (2, "end finish* wrap", "test experiment trial run study here now today up it this"),
        (0, "we", "done finished conclude"),
        (3, "allowed permitted", "look read see view analys* analyz* interpret"),
    ),
    "reassurance": (
        ("confirm* reassur*",),
        (1, "right correct agreed yes yeah no ok okay", "$"),
        (0, "doesnt isnt arent wasnt werent", "it they that this", 1, "$"),
        (0, "^ , or and but", "is are was were can could", 8, QUALITY),
        (0, "^ , or and but", "does do", 2, "look* seem*", 3, QUALITY),
        (2, "nothing", "worry wrong broken concern"),
        (2, "worth", "worrying worry bother"),
        (3, "enough small tiny minor safe fine", "ignor*"),
        ("ignorable negligible harmless trustworthy",),
        (2, "all", "good fine clear ok okay"),
        (3, "say tell assure promise", "fine ok okay good safe valid"),
    ),
    "effect_reality": (
        (0, "^ , or and but", "is are was were does do did can could will would", 6,
         REAL + " variation"),
        (5, "whether if", REAL),
        (3, "effect lift uplift difference gain impact improvement increase", REAL),
        (0, "is are was were", "there", 3, "effect* difference lift uplift impact"),
        (1, "had has have", "an any no a", "effect impact difference"),
        ("statistically insignific*",),
    ),
    "effect_numbers": (
        (5, "what whats how give show tell report print list state provide", "estimat*"),
        (0, "point", "estimat*"),
        (0, "p", "value*"),
        (1, "confidence", "interval*"),
        ("ci",),
        (0, "how", "big* larg* strong* high*"),
        (0, "how", "much", 3,
         "lift uplift effect difference gain improvement increase better worse more less"),
        (0, "by", "how", "much"),
        (0, "what", "percent*"),
        (4, AVERAGES, GROUP),
        (4, GROUP, AVERAGES),
        (0, "effect", "size"),
        (1, "absolute relative percent*", "terms points difference lift"),
        (0, "standard", "error deviation"),
        (1, "results effect", "table"),
        (3, "variant treatment arm control", "lift uplift"),
        ("magnitude",),
    ),
    "causal": (
        ("caus*",),
        ("drove driv*",),
        ("novelty seasonality",),
        (0, "down", "to"),
        (4, "explain* account*", CHANGE),
        (3, "made make*", CHANGE),
        (2, "behind", CHANGE),
        ("attribut*",),
        ("responsible",),
    ),
    "forecast": (
        ("expect expecting expects",),
        ("forecast* predict* project* extrapolat* anticipat*",),
        ("future rollout* eventually tomorrow",),
        (0, "long", "run term"),
        (0, "full at to", "scale"),
        (4, "will happens happen",
         CHANGE + " impact result revenue conversion improvement growth metric"),
        ("holiday* season seasons",),
        ("month* year* quarter*",),
        (1, "next coming upcoming following later", "week*"),
        ("fade* decay* wane* persist*",),
        (1, "still", "be hold there"),
        ("generalis* generaliz* replicat*",),
    ),
    "subgroup": (
        ("android ios iphone ipad mobile desktop tablet* console* laptop*",),
        ("platform* device* countr* region* segment*",),
        ("demograph* geograph* locale*",),
        ("spender* payer* whale*",),
        ("returning",),
        (0, "new", "players users customers"),
        ("germany japan brazil india china canada france italy spain mexico australia korea "
         "russia britain uk usa europe asia africa america",),
    ),
    "other_analysis": (
        (0, "what", "if"),
        (3, "rerun* redo recompute* recalculat* reanalys* reanalyz* repeat*",
         "analysis comparison test* calculation model estimate* numbers interval* data"),
        (0, "instead", "of"),
        ("winsor* trim* bootstrap* wilcoxon bonferroni ttest anova ancova cuped regress* "
         "bayesian covariate* outlier* permutation*",),
        (0, "t", "test"),
        (0, "one two", "sided"),
        (3, "apply applying add use try",
         "correction* adjustment* filter* exclusion* window method model metric"),
        (4, "exclu* omit* remov* filter* drop*",
         "players users days week* data rows cohort*"),
        (2, "different another alternative other",
         "metric test method window period threshold model analysis approach definition"),
        ("assuming suppos* imagin* hypothetical* simulat*",),
    ),
    "data_access": (
        (1, "player* user*", "id ids identifier*"),
        (0, "which", "players users"),
        (3, "raw", "data events export table* file* logs"),
        ("row* download* csv record* dataset*",),
        (1, "export", "file* folder*"),
        (1, "exposure assignment event* outcome* purchase*", "log* table*"),
        (3, "who", "was were exposed assigned bought purchased"),
        (4, "where", "data file* export"),
    ),
    "rewording": (
        ("plain* simpl* shorter shorten jargon layman* layperson eli5 tldr",),
        (1, "tl", "dr"),
        (0, "like", "im", "five"),
        ("rephras* reword* rewrit* paraphras* restat* translat* tone casual* friendl* formal*",),
        ("bullet*",),
        (2, "for", "boss manager director executive* ceo stakeholder* audience kids colleague* "
                   "partner* client* investor* board standup team"),
        (2, "in", "sentence* paragraph* words"),
        (1, "as", "list table email slide* json csv markdown"),
        (3, "put turn convert reformat format", "email slide* table list json pdf"),
    ),
}

# The intents. `checked` is tried first, then `next_steps`; a question that names a rule is an
# explanation; `summary` is the last.
INTENTS: dict[str, tuple[Pattern, ...]] = {
    "checked": (
        (3, "which what how", "check* rule* test*",
         "ran run made perform* execut* cover* includ* appl* done missing use* passed failed"),
        (3, "did does has have", "review referee report you",
         "test* check* look* cover* verif* examin* inspect* assess* includ*"),
        (3, "did does has have", "review referee report you", 1, "run ran", 3,
         "rule* analys* guardrail* everything all"),
        ("skipped",),
        (1, "never", "ran run checked tested covered performed"),
        (2, "what", "checked tested covered examined"),
        (4, "was were",
         "checked tested covered examined verified included run ran applied performed done"),
    ),
    "next_steps": (
        ("fix* repair* remediat* resolv* address* steps",),
        (0, "what", "order"),
        (0, "next", "step"),
        (3, "should must need needs", "do change"),
        ("advis* advice recommend* suggest* actions",),
        ("rerun* retest*",),
        (2, "run running", "again"),
        (3, "before", "run running repeat* again"),
    ),
    "summary": (
        ("finding* block* warning* overview summar* overall verdict* picture sever* serious* "
         "problem* issue* wrong",),
        (3, "review report experiment",
         "find found say says show shows contain contains conclude concluded"),
        (3, "tell describe walk give", "review report experiment"),
    ),
}

# Phrases that point at one of the nine results rules, from their titles (24.8).
PHRASES: dict[str, tuple[Pattern, ...]] = {
    "RES-001": (("srm",), (0, "sample", "ratio", "mismatch"), ("allocation*",)),
    "RES-002": (
        (2, "fewer", "players", "than"),
        (0, "sample", "size*"),
        ("underpowered",),
        (0, "too", "few"),
    ),
    "RES-003": (("duration*",), (0, "run", "length"), (0, "too", "short"), (3, "ran", "less")),
    "RES-004": (("guardrail*",), ("tolerance*",)),
    "RES-007": (("cohort*",), (0, "first", "exposure")),
    "RES-008": (("skew*",), (1, "heavy", "tail tails tailed"), (0, "revenue", "like")),
    "RES-011": (("drift*",), ("weekly",), (0, "week", "by to", "week")),
    "RES-012": ((1, "late", "exposed exposure"), (0, "first", "purchase")),
    "RES-013": (("configur*",),),
}

# These patterns of a category count only when the question names no rule: "Why does RES-001
# block?" is an explanation and not `causal` (24.8).
WHEN_NO_RULE_NAMED: dict[str, tuple[Pattern, ...]] = {
    "causal": (
        (6, "why because", EFFECT_WORDS),
        (6, EFFECT_WORDS, "because due"),
    ),
}
# fmt: on
# A category that is not matched when the question names this rule: a question about the finding
# on cohorts of first exposure is an explanation of it, not a question about a subgroup (24.8).
EXPLANATION_OF: dict[str, str] = {"subgroup": "RES-007"}

# --- Matching --------------------------------------------------------------------------------

Step = tuple[int, frozenset[str], tuple[str, ...]]


def compile_pattern(pattern: Pattern) -> tuple[Step, ...]:
    """A pattern as steps `(words allowed between this step and the last, words, prefixes)`."""
    steps = []
    gap = 0
    for item in pattern:
        if isinstance(item, int):
            gap = item
        else:
            words = item.split()
            steps.append(
                (
                    gap,
                    frozenset(word for word in words if not word.endswith("*")),
                    tuple(word[:-1] for word in words if word.endswith("*")),
                )
            )
    return tuple(steps)


def _compile(table: dict[str, tuple[Pattern, ...]]) -> dict[str, tuple[tuple[Step, ...], ...]]:
    return {name: tuple(compile_pattern(pattern) for pattern in table[name]) for name in table}


_TRIGGERS = _compile(TRIGGERS)
_INTENTS = _compile(INTENTS)
_PHRASES = _compile(PHRASES)
_WHEN_NO_RULE_NAMED = _compile(WHEN_NO_RULE_NAMED)


def _at(word: str, step: Step) -> bool:
    return word in step[1] or (bool(step[2]) and word.startswith(step[2]))


def matches(words: list[str], steps: tuple[Step, ...]) -> bool:
    """Whether the steps follow one another in `words`, each within its gap of the last. One pass
    over the words for each step: `live[i]` says that the steps so far end at word `i`."""
    live = [_at(word, steps[0]) for word in words]
    for step in steps[1:]:
        live = [
            _at(word, step) and any(live[max(0, i - step[0] - 1) : i])
            for i, word in enumerate(words)
        ]
    return any(live)


def _any(words: list[str], patterns: tuple[tuple[Step, ...], ...]) -> bool:
    return any(matches(words, steps) for steps in patterns)


# --- Normalising and reading -----------------------------------------------------------------


def normalise(question: str) -> str:
    """NFKC of the case-folded NFKC text; U+0020, tab, line feed, carriage return and the
    categories Zs, Zl and Zp are one space, and a run of spaces is one. Another control
    character stays (it is category C)."""
    text = unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", question).casefold())
    spaced = "".join(
        " " if c in "\t\n\r" or unicodedata.category(c) in ("Zs", "Zl", "Zp") else c for c in text
    )
    return " ".join(part for part in spaced.split(" ") if part)


def _mixes_scripts(text: str) -> bool:
    scripts: set[str] = set()
    for char in text + " ":
        if char.isalpha():
            scripts.add(unicodedata.name(char, "?").split(" ", 1)[0])
        else:
            if "LATIN" in scripts and scripts & {"CYRILLIC", "GREEK"}:
                return True
            scripts = set()
    return False


def unreadable(text: str) -> str | None:
    """The reason (one of `render.UNREADABLE_REASONS`) that a normalised question cannot be
    read, or None."""
    if not text:
        return "empty"
    if len(text) > MAX_CHARS:
        return "too long"
    if not any(char.isalpha() for char in text):
        return "no letter"
    if any(unicodedata.category(char)[0] in "CM" for char in text):
        return "invisible or mark character"
    if _mixes_scripts(text):
        return "mixed scripts"
    return None


def _is_id_gap(between: str, family: str) -> bool:
    """Whether `between` can separate the letters and the digits of a rule ID."""
    dash = between.replace(" ", "")
    if dash == "":
        return between == " " and family in RULE_FAMILIES
    return len(dash) == 1 and (dash == "_" or unicodedata.category(dash) == "Pd")


def _is_letters(word: str) -> bool:
    return len(word) == 3 and all("a" <= c <= "z" for c in word)


def _is_digits(word: str) -> bool:
    return len(word) == 3 and all("0" <= c <= "9" for c in word)


def read(text: str) -> tuple[list[str], list[str]]:
    """The words of a normalised, readable question and the rule IDs in it (canonical, shaped
    like `RES-004`, in order). An ID is one word, `#`, among the others."""
    pieces: list[tuple[str, int, int]] = []  # (word or ",", start, end)
    word: list[str] = []
    start = 0
    for i, char in enumerate(text + " "):
        if char in "'\u2019":  # joins its neighbours
            continue
        if char.isalnum():
            start = start if word else i
            word.append(char)
            continue
        if word:
            pieces.append(("".join(word), start, i))
            word = []
        in_number = char == "." and 0 < i < len(text) - 1 and text[i - 1 : i + 2 : 2].isalnum()
        if char in ",;:!?" or (char == "." and not in_number):
            pieces.append((",", i, i + 1))
    for k in range(len(pieces) - 2, -1, -1):  # re-run, re-analyze: one word
        word_k, _, end = pieces[k]
        following = pieces[k + 1]
        if word_k == "re" and following[0] != "," and text[end : following[1]] == "-":
            pieces[k : k + 2] = [("re" + following[0], pieces[k][1], following[2])]
    words = ["^"]
    ids: list[str] = []
    k = 0
    while k < len(pieces):
        word_k, _, end = pieces[k]
        following = pieces[k + 1] if k + 1 < len(pieces) else None
        if len(word_k) == 6 and _is_letters(word_k[:3]) and _is_digits(word_k[3:]):
            ids.append(f"{word_k[:3]}-{word_k[3:]}".upper())
            words.append("#")
        elif (
            following is not None
            and _is_letters(word_k)
            and _is_digits(following[0])
            and _is_id_gap(text[end : following[1]], word_k)
        ):
            ids.append(f"{word_k}-{following[0]}".upper())
            words.append("#")
            k += 1
        else:
            words.append(word_k)
        k += 1
    return [*words, "$"], ids


def _targets(words: list[str], ids: list[str]) -> set[str]:
    """The rules the question names: IDs (of the nine or not) and phrases."""
    named = set(ids)
    named.update(rule for rule, patterns in _PHRASES.items() if _any(words, patterns))
    return named


def _categories(words: list[str], named: set[str]) -> tuple[str, ...]:
    found = []
    for category in CATEGORIES:
        patterns = _TRIGGERS[category]
        if not named:
            patterns += _WHEN_NO_RULE_NAMED.get(category, ())
        if EXPLANATION_OF.get(category) not in named and _any(words, patterns):
            found.append(category)
    return tuple(found)


def _intent(words: list[str], named: set[str]) -> tuple[str, str | None, bool] | None:
    """(intent, target, as_summary) of the answerable part of a question, or None."""
    for intent in ("checked", "next_steps"):
        if _any(words, _INTENTS[intent]):
            return intent, None, False
    if named:
        if len(named) > 1:
            return "explain_finding", None, True
        (only,) = named
        return "explain_finding", only if only in RULE_IDS else None, False
    if _any(words, _INTENTS["summary"]):
        return "summary", None, False
    return None


def route(question: str) -> Understanding:
    """What the page answers for `question`: an answer, a refusal (with the categories matched,
    none for the default route) or an unreadable question. Never raises for a `str`."""
    text = normalise(question)
    reason = unreadable(text)
    if reason is not None:
        return Understanding("unreadable", reason=reason)
    words, ids = read(text)
    named = _targets(words, ids)
    categories = _categories(words, named)
    intent = _intent(words, named)
    if categories:
        # a refusal keeps the intent of an answerable part, but a phrase alone does not make an
        # explanation of a finding one
        part = intent[0] if intent and (ids or intent[0] != "explain_finding") else None
        only = next(iter(named)) if len(named) == 1 else None
        return Understanding(
            "refusal", intent=part, target=only if only in RULE_IDS else None, categories=categories
        )
    if intent is None:
        return Understanding("refusal")
    return Understanding("answer", intent[0], target=intent[1], as_summary=intent[2])
