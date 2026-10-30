"""The grounding study of design section 24.12 (step N9): a compact re-measurement of a checker.

The checker admits a text for one or two cited catalogue sentences only if its words are function
words or words of a cited sentence that holds none of a list of loaded words. The study counts
the sentences that hold none, the texts the checker admits among all short ones, and which
hand-written harmful probes it admits. No model is run; the figures describe a checker's acceptance
space. Read docs/grounding-study.md; `python tests/grounding_study/run.py` writes it.

Hard ceilings: at most 12 files here, the data file included, and 60 KB of code, the
documents excluded; the study-tier tests (`pytest -m study tests/grounding_study`) take at most
20 s; no absolute path (everything is found from `__file__`).
"""
