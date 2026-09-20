# Security policy

## Scope

This is a local portfolio project. It generates synthetic data, builds it with dbt into
a local DuckDB file, and publishes analysis artifacts. It has no deployment, no network
services, no authentication, and no production, customer, or employer data. There are no
released versions to support.

## Reporting a vulnerability

Report suspected issues through GitHub Security Advisories:
<https://github.com/AVZa-BL/ai-product-analytics-lab/security/advisories/new>

Expect an initial response within 14 days. Because the project is not deployed, fixes
land on `main` rather than in a patched release.

## Out of scope

Production hardening, orchestration, warehouse scaling and deployment are outside the
project's stated scope, as recorded in the README limitations.
