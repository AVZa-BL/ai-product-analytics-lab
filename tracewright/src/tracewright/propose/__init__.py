"""Propose tracking for a new feature from its documents and the tracking that exists.

A model drafts the proposal; deterministic code checks it. Nothing here trusts the model's
output: it is parsed against a strict schema, its quoted evidence is searched for in the
documents, its names are compared with the existing plan, and the merged plan is run through
the same rules as `tracewright review-plan`. Problems go back to the model for repair, and
whatever cannot be repaired is reported, never hidden.
"""
