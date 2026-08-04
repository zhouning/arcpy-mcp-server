import ipaddress

import pytest

from arcpy_mcp_server.host_address import (
    AddressResolutionError,
    resolve_ipv4_network,
    resolve_server_ip,
)


def test_explicit_override_wins():
    assert resolve_server_ip({"ARCPY_MCP_SERVER_IP": "10.20.30.40"}) == "10.20.30.40"


@pytest.mark.parametrize(
    "value",
    ["127.0.0.1", "169.254.10.1", "0.0.0.0", "224.0.0.1", "::1"],
)
def test_override_rejects_unroutable_addresses(value):
    """These bind fine but no remote client can reach the gateway at them."""
    with pytest.raises(AddressResolutionError):
        resolve_server_ip({"ARCPY_MCP_SERVER_IP": value})


def test_override_rejects_malformed_value():
    with pytest.raises(AddressResolutionError):
        resolve_server_ip({"ARCPY_MCP_SERVER_IP": "192.168.1"})


def test_autodetects_a_routable_address():
    detected = resolve_server_ip({})
    parsed = ipaddress.ip_address(detected)
    assert not parsed.is_loopback
    assert not parsed.is_link_local


def test_falls_back_to_base_url_host(monkeypatch):
    monkeypatch.setattr(
        "arcpy_mcp_server.host_address._probe_default_route", lambda: None
    )
    resolved = resolve_server_ip(
        {"ARCPY_MCP_PUBLIC_BASE_URL": "https://203.0.113.55:8765"}
    )
    assert resolved == "203.0.113.55"


def test_dns_name_in_base_url_is_not_used_as_an_ip(monkeypatch):
    """A hostname needs no IP SAN, so it must not satisfy IP resolution."""
    monkeypatch.setattr(
        "arcpy_mcp_server.host_address._probe_default_route", lambda: None
    )
    with pytest.raises(AddressResolutionError):
        resolve_server_ip({"ARCPY_MCP_PUBLIC_BASE_URL": "https://gis.example.com:8765"})


def test_raises_when_nothing_is_resolvable(monkeypatch):
    monkeypatch.setattr(
        "arcpy_mcp_server.host_address._probe_default_route", lambda: None
    )
    with pytest.raises(AddressResolutionError, match="LAN address"):
        resolve_server_ip({})


def test_derives_firewall_scope():
    assert resolve_ipv4_network("192.168.50.170") == "192.168.50.0/24"
    assert resolve_ipv4_network("10.1.2.3", prefix=16) == "10.1.0.0/16"


def test_firewall_scope_rejects_ipv6():
    """A rotating IPv6 privacy address would make the rule wrong immediately."""
    with pytest.raises(AddressResolutionError):
        resolve_ipv4_network("2001:db8::1")
