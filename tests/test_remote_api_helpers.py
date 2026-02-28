import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from services.remote_api import _client_allowed, parse_allowed_cidrs


def test_parse_allowed_cidrs_normalizes_values():
    cidrs = parse_allowed_cidrs("192.168.1.0/24, 10.0.0.5/32")

    assert cidrs == ["192.168.1.0/24", "10.0.0.5/32"]


def test_client_allowed_matches_cidr_rules():
    allowlist = ["192.168.1.0/24", "10.0.0.5/32"]

    assert _client_allowed("192.168.1.22", allowlist) is True
    assert _client_allowed("10.0.0.5", allowlist) is True
    assert _client_allowed("10.0.0.6", allowlist) is False
    assert _client_allowed("not-an-ip", allowlist) is False
