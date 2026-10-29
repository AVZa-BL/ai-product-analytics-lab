"""Specwright: drafts an experiment spec from a brief or a design document.

A model reads the documents and drafts the spec as a list of claims, each with its evidence: a
verbatim quote, an explicit "inferred", or "missing". Deterministic code then checks the draft:
the quotes are searched for in the documents, a number must be in its quote, approximate wording
is never turned into a number, the spec is built and read by Referee, the design rules are run,
and the sizes are worked out by Referee's power plan, never by the model. Problems go back to the
model for repair; what is left is reported as it is.

Passing the checks proves the draft is consistent with the documents and with Referee's rules. It
does not prove the experiment is well designed.
"""

__version__ = "0.1.0"
