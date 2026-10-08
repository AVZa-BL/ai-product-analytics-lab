"""Fixtures shared by the Tracewright test modules."""

import pytest


@pytest.fixture(autouse=True)
def no_real_credentials(monkeypatch):
    """No test may reach a real API: with no credentials in the environment, none can."""
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def raw_plan() -> dict:
    """A valid, finding-free plan as the plain dict a YAML file would load into."""
    return {
        "tracewright_plan_version": 1,
        "id": "checkout_funnel",
        "title": "Checkout funnel",
        "owner": "growth-analytics",
        "identity_keys": ["user_id"],
        "events": [
            {
                "name": "checkout_started",
                "description": "Checkout screen opened.",
                "trigger": "Screen shown.",
                "properties": [
                    {"name": "user_id", "type": "string", "required": True},
                    {"name": "cart_value", "type": "number"},
                ],
            },
            {
                "name": "order_completed",
                "description": "Payment confirmed.",
                "trigger": "Provider webhook.",
                "properties": [
                    {"name": "user_id", "type": "string", "required": True},
                    {"name": "cart_value", "type": "number"},
                    {"name": "method", "type": "enum", "allowed_values": ["card", "wallet"]},
                ],
            },
        ],
        "metrics": [{"name": "conversion", "events": ["checkout_started", "order_completed"]}],
    }
