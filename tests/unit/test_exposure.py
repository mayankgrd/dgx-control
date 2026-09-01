"""The exposure classifier is the product's central safety signal."""

from __future__ import annotations

import json

import pytest

from dgxctl.collectors.containers import parse_ports
from dgxctl.collectors.util import classify_exposure, container_id_from_cgroup, is_finding, parse_ss
from dgxctl.schemas import Exposure

TAILNET = {"100.64.0.1", "fd7a:115c:a1e0::1111:2222"}


@pytest.mark.parametrize(
    ("addr", "expected"),
    [
        ("127.0.0.1", Exposure.loopback),
        ("::1", Exposure.loopback),
        ("127.0.0.53%lo", Exposure.loopback),  # zone suffix, real `ss` output
        ("0.0.0.0", Exposure.all),
        ("::", Exposure.all),
        ("[::]", Exposure.all),
        ("*", Exposure.all),
        ("", Exposure.all),  # empty means ALL, never "unknown"
        ("100.64.0.1", Exposure.tailnet),
        ("100.90.1.5", Exposure.tailnet),  # CGNAT range even without tailscale status
        ("fd7a:115c:a1e0::1111:2222", Exposure.tailnet),
        ("192.168.1.10", Exposure.lan),
        ("172.17.0.1", Exposure.lan),  # docker bridge
    ],
)
def test_classify_exposure(addr, expected):
    assert classify_exposure(addr, TAILNET) is expected


def test_wildcard_and_lan_are_findings_loopback_is_not():
    assert is_finding(Exposure.all)
    assert is_finding(Exposure.lan)
    assert is_finding(Exposure.tailnet)
    assert not is_finding(Exposure.loopback)


def test_parse_ss_against_real_capture(fixtures):
    rows = parse_ss((fixtures / "ss_tulnpH.txt").read_text(), TAILNET)
    assert rows, "parser produced nothing from real ss output"
    by_port = {(r["protocol"], r["port"], r["bind_ip"]): r for r in rows}

    # A live TensorBoard container publishing on all interfaces.
    wildcard = by_port[("tcp", 6006, "0.0.0.0")]
    assert wildcard["exposure"] is Exposure.all

    # IPv6 wildcard for the same port is also "all", not "unknown".
    assert by_port[("tcp", 6006, "::")]["exposure"] is Exposure.all

    # A vLLM server correctly bound to loopback.
    assert by_port[("tcp", 8010, "127.0.0.1")]["exposure"] is Exposure.loopback

    # A socket bound to the node's own tailnet address.
    assert by_port[("tcp", 45077, "100.64.0.1")]["exposure"] is Exposure.tailnet

    # sshd is root-owned, so an unprivileged `ss` shows no PID. That is normal.
    ssh = by_port[("tcp", 22, "0.0.0.0")]
    assert ssh["pid"] is None
    assert ssh["exposure"] is Exposure.all

    # ...but a process we own does carry its PID and name.
    owned = [r for r in rows if r["process"] == "hermes"]
    assert owned and all(r["pid"] for r in owned)


def test_parse_ss_strips_interface_zones(fixtures):
    rows = parse_ss((fixtures / "ss_tulnpH.txt").read_text(), TAILNET)
    assert not any("%" in r["bind_ip"] for r in rows)


def test_parse_ss_ignores_non_listening_and_garbage():
    assert parse_ss("tcp ESTAB 0 0 10.0.0.1:22 10.0.0.2:5555") == []
    assert parse_ss("garbage\n\n   \nnot a socket line") == []


def test_empty_hostip_means_all_interfaces(fixtures):
    """The single highest-stakes seam: an empty HostIp is 0.0.0.0, NOT loopback.

    Reading it as loopback would invert the safety signal this tool exists to provide.
    """
    ports = json.loads((fixtures / "docker_ports.json").read_text())
    bindings = parse_ports(ports["empty-hostip"], TAILNET)
    assert len(bindings) == 1
    assert bindings[0].host_ip == "0.0.0.0"
    assert bindings[0].exposure is Exposure.all


def test_wildcard_and_loopback_publishes_are_distinguished(fixtures):
    ports = json.loads((fixtures / "docker_ports.json").read_text())
    tb = parse_ports(ports["tb"], TAILNET)
    published = [b for b in tb if b.host_port]
    assert {b.exposure for b in published} == {Exposure.all}

    # An image-exposed but unpublished port must not be reported as reachable.
    unpublished = [b for b in tb if b.host_port is None]
    assert len(unpublished) == 1
    assert unpublished[0].container_port == 8888
    assert unpublished[0].exposure is Exposure.unknown

    vllm = parse_ports(ports["vllm-server"], TAILNET)
    assert vllm[0].exposure is Exposure.loopback


@pytest.mark.parametrize("name", ["cgroup_v2_docker.txt", "cgroup_v1_docker.txt"])
def test_container_id_from_cgroup_both_versions(fixtures, name):
    cid = container_id_from_cgroup((fixtures / name).read_text())
    assert cid == "834e93fa6923e1daed6ff96f9f0bab62f7008ec64c7af1e6727e8d5cf9a3b8ea"


def test_host_process_has_no_container(fixtures):
    assert container_id_from_cgroup((fixtures / "cgroup_host.txt").read_text()) is None
