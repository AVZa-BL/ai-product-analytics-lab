"""Fixtures shared by the Tracewright test modules."""

import socket

import pytest

_REAL_CONNECT = socket.socket.connect


@pytest.fixture(autouse=True)
def isolated_from_real_credentials(monkeypatch, tmp_path_factory):
    """No test may reach a real API, whatever is installed on the machine running it.

    Credentials can come from ANTHROPIC_* variables or from a profile under the home directory
    (`ant auth login`), so both are removed. ANTHROPIC_CONFIG_DIR is deliberately not set: the SDK
    treats it as an explicit choice and fails differently. As a last line of defence, a connection
    to anything but this machine fails the test (the HTTP library the SDK uses is replaced by a
    mock transport wherever a test needs a response, and a mock opens no socket).
    """
    import os

    for name in [n for n in os.environ if n.startswith("ANTHROPIC_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("GOOGLE_SHEETS_ACCESS_TOKEN", raising=False)
    # Proxy variables are cleared so that tests which talk to a server on this machine do not
    # go through whatever proxy the machine running them is configured with.
    for name in [n for n in os.environ if n.lower().endswith("_proxy")]:
        monkeypatch.delenv(name, raising=False)
    home = tmp_path_factory.mktemp("home")
    for name in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(name, str(home))

    def guarded_connect(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else None
        if self.family != socket.AF_UNIX and host not in ("127.0.0.1", "::1", "localhost"):
            pytest.fail(f"a test tried to open a network connection to {address!r}")
        return _REAL_CONNECT(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


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
