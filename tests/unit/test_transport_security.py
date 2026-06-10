"""Unit tests for TransportSecuritySettings and related helpers."""

from __future__ import annotations

import pytest

from lauren_mcp._server._transport_security import (
    TransportSecuritySettings,
    _host_allowed,
    _origin_allowed,
)

# ---------------------------------------------------------------------------
# _host_allowed
# ---------------------------------------------------------------------------


def test_localhost_allowed_by_default():
    assert _host_allowed("localhost", []) is True


def test_localhost_with_port_allowed_by_default():
    assert _host_allowed("localhost:8080", []) is True


def test_127_0_0_1_allowed_by_default():
    assert _host_allowed("127.0.0.1", []) is True


def test_127_0_0_1_with_port_allowed_by_default():
    assert _host_allowed("127.0.0.1:3000", []) is True


def test_unknown_host_blocked_by_default():
    assert _host_allowed("evil.com", []) is False


def test_explicit_host_allowed():
    s = TransportSecuritySettings(allowed_hosts=["api.example.com"])
    assert _host_allowed("api.example.com", s.allowed_hosts) is True


def test_explicit_host_with_port_blocked_when_not_listed():
    s = TransportSecuritySettings(allowed_hosts=["api.example.com"])
    assert _host_allowed("api.example.com:8080", s.allowed_hosts) is False


def test_wildcard_port_allowed():
    s = TransportSecuritySettings(allowed_hosts=["api.example.com:*"])
    assert _host_allowed("api.example.com:8080", s.allowed_hosts) is True
    assert _host_allowed("api.example.com:443", s.allowed_hosts) is True


def test_wrong_host_blocked():
    s = TransportSecuritySettings(allowed_hosts=["api.example.com"])
    assert _host_allowed("evil.com", s.allowed_hosts) is False


def test_multiple_hosts_first_matches():
    allowed = ["host1.example.com", "host2.example.com"]
    assert _host_allowed("host1.example.com", allowed) is True
    assert _host_allowed("host2.example.com", allowed) is True
    assert _host_allowed("host3.example.com", allowed) is False


# ---------------------------------------------------------------------------
# _origin_allowed
# ---------------------------------------------------------------------------


def test_origin_matches_allowed_host():
    s = TransportSecuritySettings(allowed_hosts=["example.com"])
    assert _origin_allowed("https://example.com", s) is True


def test_origin_http_matches_allowed_host():
    s = TransportSecuritySettings(allowed_hosts=["example.com"])
    assert _origin_allowed("http://example.com", s) is True


def test_origin_explicitly_allowed():
    s = TransportSecuritySettings(allowed_origins=["https://app.example.com"])
    assert _origin_allowed("https://app.example.com", s) is True


def test_origin_not_in_list_blocked():
    s = TransportSecuritySettings(allowed_hosts=["example.com"])
    assert _origin_allowed("https://evil.com", s) is False


def test_origin_explicitly_allowed_overrides_host_check():
    """Origin listed in allowed_origins should pass even if not matching allowed_hosts."""
    s = TransportSecuritySettings(
        allowed_hosts=["other.example.com"],
        allowed_origins=["https://special.example.com"],
    )
    assert _origin_allowed("https://special.example.com", s) is True


# ---------------------------------------------------------------------------
# TransportSecuritySettings
# ---------------------------------------------------------------------------


def test_settings_are_frozen():
    s = TransportSecuritySettings()
    with pytest.raises(Exception):  # noqa: B017
        s.enable_dns_rebinding_protection = False  # type: ignore[misc]


def test_disabled_guard_allows_all():
    s = TransportSecuritySettings(enable_dns_rebinding_protection=False)
    assert s.enable_dns_rebinding_protection is False


def test_is_host_allowed_method_delegates():
    s = TransportSecuritySettings(allowed_hosts=["myhost.com"])
    assert s.is_host_allowed("myhost.com") is True
    assert s.is_host_allowed("evil.com") is False


def test_is_origin_allowed_none_is_same_origin():
    s = TransportSecuritySettings(allowed_hosts=["myhost.com"])
    assert s.is_origin_allowed(None) is True


def test_is_origin_allowed_matching():
    s = TransportSecuritySettings(allowed_origins=["https://myapp.com"])
    assert s.is_origin_allowed("https://myapp.com") is True
    assert s.is_origin_allowed("https://evil.com") is False


def test_default_settings_enable_protection():
    s = TransportSecuritySettings()
    assert s.enable_dns_rebinding_protection is True
    assert s.allowed_hosts == []
    assert s.allowed_origins == []
