"""The reachability matrix (SDD-133).

Every row is a real situation someone hits: a link that resolves on the viewer's own laptop
instead of the DGX is the failure this exists to prevent.
"""

from __future__ import annotations

import pytest

from dgxctl.reachability import (
    LAN,
    LOOPBACK,
    TAILNET,
    HostAddresses,
    classify_viewer,
    plan,
    service_scope,
)

HOST = HostAddresses(
    hostname="dgx-01",
    lan=["192.0.2.10", "192.0.2.11"],
    tailnet_ip="100.64.0.1",
    tailnet_name="dgx-01.example.ts.net",
)


# --- where is the viewer? ----------------------------------------------------


@pytest.mark.parametrize("origin", ["127.0.0.1", "localhost", "::1"])
def test_loopback_origins(origin):
    assert classify_viewer(origin, HOST) is LOOPBACK


@pytest.mark.parametrize("origin", ["dgx-01.example.ts.net", "100.64.0.1", "100.90.3.4"])
def test_tailnet_origins(origin):
    assert classify_viewer(origin, HOST) is TAILNET


@pytest.mark.parametrize("origin", ["192.0.2.10", "192.0.2.50", "192.168.1.20", "dgx-01"])
def test_lan_origins(origin):
    assert classify_viewer(origin, HOST) is LAN


# --- what can reach the service at all? --------------------------------------


@pytest.mark.parametrize("bind", ["0.0.0.0", "::", "*", ""])
def test_wildcard_binds_are_reachable_from_anywhere(bind):
    assert service_scope(bind) == "all"


@pytest.mark.parametrize("bind", ["127.0.0.1", "::1", "172.17.0.1", "172.18.0.1"])
def test_loopback_and_docker_bridges_are_host_only(bind):
    """A Docker bridge address is reachable from the host and its containers — never from
    anywhere a person is sitting."""
    assert service_scope(bind) == "host-only"


def test_tailnet_bind_is_tailnet_only():
    assert service_scope("100.64.0.1") == "tailnet-only"


# --- the matrix --------------------------------------------------------------


def test_lan_viewer_all_interfaces_links_to_the_lan_address():
    p = plan("0.0.0.0", 6006, "192.0.2.50", HOST)
    assert [r.url for r in p.routes] == [
        "http://192.0.2.10:6006/",
        "http://192.0.2.11:6006/",
    ], "both LAN addresses should be offered; this machine has two"
    assert p.forward_command is None


def test_lan_viewer_loopback_service_forwards_naming_the_lan_address():
    p = plan("127.0.0.1", 8010, "192.0.2.50", HOST)
    assert p.routes == []
    assert p.forward_command == "ssh -N -L 8010:127.0.0.1:8010 192.0.2.10"
    assert p.forward_url == "http://127.0.0.1:8010/"


def test_tailnet_viewer_all_interfaces_links_to_the_magicdns_name():
    p = plan("0.0.0.0", 6006, "dgx-01.example.ts.net", HOST)
    assert p.primary.url == "http://dgx-01.example.ts.net:6006/"


def test_tailnet_viewer_loopback_service_forwards_via_the_tailnet_name():
    p = plan("127.0.0.1", 11434, "100.64.0.1", HOST)
    assert p.forward_command == "ssh -N -L 11434:127.0.0.1:11434 dgx-01.example.ts.net"


def test_loopback_viewer_is_told_both_possibilities():
    """NVIDIA Sync and SSH tunnels both produce a 127.0.0.1 origin, and the page cannot tell
    that from a browser running on the DGX. It must state both."""
    p = plan("127.0.0.1", 8010, "127.0.0.1", HOST)
    assert p.primary.url == "http://127.0.0.1:8010/"
    assert "on the DGX itself" in p.primary.label
    assert "NVIDIA Sync" in p.primary.caveat
    assert p.forward_command, "the forwarded case must still be offered"


def test_loopback_viewer_all_interfaces_service_gets_real_addresses_too():
    """Bound to 0.0.0.0, so a Sync user can skip forwarding and use the DGX's real address."""
    p = plan("0.0.0.0", 6006, "127.0.0.1", HOST)
    urls = [r.url for r in p.routes]
    assert "http://127.0.0.1:6006/" in urls
    assert "http://192.0.2.10:6006/" in urls
    assert "http://dgx-01.example.ts.net:6006/" in urls


def test_docker_bridge_service_is_treated_as_host_only():
    p = plan("172.17.0.1", 9090, "192.0.2.50", HOST)
    assert p.routes == []
    assert p.forward_command is not None


def test_tailnet_only_service_is_unreachable_from_the_lan_and_says_so():
    p = plan("100.64.0.1", 443, "192.0.2.50", HOST)
    assert p.routes == [] and p.forward_command is None
    assert "cannot be reached from where you are" in p.unreachable_reason


def test_forward_command_never_contains_a_placeholder():
    for origin in ("127.0.0.1", "192.0.2.50", "dgx-01.example.ts.net"):
        p = plan("127.0.0.1", 8010, origin, HOST)
        assert p.forward_command and "<" not in p.forward_command


def test_the_dashboard_itself_is_not_offered_a_forward():
    p = plan("127.0.0.1", 8770, "127.0.0.1", HOST, is_self=True)
    assert p.forward_command is None
    assert p.primary.url == "http://127.0.0.1:8770/"


def test_a_host_with_no_known_addresses_explains_rather_than_guessing():
    bare = HostAddresses(hostname="dgx", lan=[], tailnet_ip=None, tailnet_name=None)
    p = plan("127.0.0.1", 8010, "127.0.0.1", bare)
    assert p.forward_command is None
    assert "<your-dgx>" in p.unreachable_reason, "must tell the user what to substitute"


def test_path_is_honoured_in_every_url():
    p = plan("0.0.0.0", 8010, "192.0.2.50", HOST, path="/docs")
    assert all(r.url.endswith("/docs") for r in p.routes)


def test_viewer_position_is_stated_for_every_case():
    for origin in ("127.0.0.1", "192.0.2.50", "dgx-01.example.ts.net"):
        assert plan("0.0.0.0", 1, origin, HOST).viewer_note
