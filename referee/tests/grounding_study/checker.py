"""The closed-vocabulary checker, and the bounded enumeration of the texts it admits.

A text is admitted for a cited set of one or two catalogue sentences when it holds no digit or
symbol and every word of it is a function word or a word of a cited sentence that is FREE under
the view in use (no loaded word, no marker). The words of a cited sentence that is not free add
nothing. The checker tests each word alone, so it cannot tell sense from word salad: the
enumeration shows how many texts that is. Harm is not computed here or anywhere in the study.
"""

from collections import Counter
from functools import reduce
from itertools import combinations, product
from operator import and_

from grounding_study.lexicon import FUNCTION_WORDS, is_free, is_marker, tokens

MAX_CITED = 2
MAX_TEXTS = 2_000_000


def vocabulary(cited, catalogue: dict[str, str], view: str) -> set[str]:
    words = set(FUNCTION_WORDS)
    for sentence_id in cited:
        if is_free(catalogue[sentence_id], view):
            words.update(tokens(catalogue[sentence_id]))
    return words


def check(text: str, cited, catalogue: dict[str, str], view: str = "full") -> str | None:
    """None when the text is admitted for the cited sentences, else the reason it is not."""
    if not 1 <= len(set(cited)) <= MAX_CITED:
        return "cites no sentence or more than two"
    words = tokens(text)
    if not words:
        return "holds no word"
    if any(is_marker(word) for word in words):
        return "holds a digit or a symbol"
    allowed = vocabulary(set(cited), catalogue, view)
    for word in words:
        if word not in allowed:
            return f"'{word}' is no function word and no word of a cited free sentence"
    return None


def enumerate_texts(catalogue: dict[str, str], view: str, max_texts: int = MAX_TEXTS) -> dict:
    """Every text of 1 to L words over the function words and the words of the free sentences.

    L is the largest length for which at most `max_texts` texts are enumerated in all. A text
    counts for a cited set (one free sentence, or two) when `check` would admit it and it holds a
    word that is no function word. Each content word carries a bit mask of the cited sets whose
    vocabulary holds it and a text's mask is the AND of its words' (a function word is all ones),
    which is the same test as `check` made once for every set.
    """
    free = [sentence_id for sentence_id, text in catalogue.items() if is_free(text, view)]
    cited_sets = [(i,) for i in free] + list(combinations(free, MAX_CITED))
    allowed = [vocabulary(cited, catalogue, view) for cited in cited_sets]
    content = sorted(set().union(*allowed) - set(FUNCTION_WORDS))
    size = len(FUNCTION_WORDS) + len(content)
    length, texts = 0, 0
    while cited_sets and texts + size ** (length + 1) <= max_texts:
        length += 1
        texts += size**length
    masks = [-1] * len(FUNCTION_WORDS)
    masks += [sum(1 << k for k, words in enumerate(allowed) if w in words) for w in content]
    function_only, alone, anyone = [], {i: [] for i in free}, []
    for n in range(1, length + 1):
        counts = Counter(reduce(and_, combo) for combo in product(masks, repeat=n))
        function_only.append(counts.pop(-1, 0))
        anyone.append(sum(c for mask, c in counts.items() if mask))
        for k, cited in enumerate(cited_sets[: len(free)]):
            alone[cited[0]].append(sum(c for mask, c in counts.items() if mask >> k & 1))
    return {
        "free": free,
        "vocabulary": size,
        "max_length": length,
        "texts": texts,
        "function_words_only": function_only,
        "alone": alone,
        "any": anyone,
    }
