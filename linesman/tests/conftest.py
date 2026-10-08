"""Fixtures shared by the Linesman test modules."""

import pytest


@pytest.fixture
def raw_plan() -> dict:
    """A valid, finding-free plan as the plain dict a YAML file would load into."""
    return {
        "linesman_plan_version": 1,
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
