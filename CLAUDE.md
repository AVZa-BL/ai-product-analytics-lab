# Working rules

- Every task: before adding or keeping a test, a helper, a config option, a CI job or a document,
  ask whether anything would break, or be missed, without it. If not, leave it out or delete it.
- Keep as little as possible. A test earns its place by guarding behaviour (a boundary, a
  reference value, a security property, an output format), not by repeating another test or by
  matching prose. Prefer one parametrized test to several copies.
- Plans and specs are scaffolding: delete a plan once its work has merged; git keeps it.
- Show evidence for a cut (coverage unchanged, or a mutation that is still caught) and say
  what remains unverified.
