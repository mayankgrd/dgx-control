"""Parsers, all against bytes captured from a live DGX Spark."""

from __future__ import annotations

import json

from dgxctl.collectors.gpu import read_meminfo
from dgxctl.collectors.tailscale import parse_status


def test_meminfo_reports_the_unified_pool_in_bytes(fixtures):
    mem = read_meminfo(str(fixtures / "meminfo.txt"))
    assert mem["MemTotal"] == 127600744 * 1024
    assert mem["MemAvailable"] == 52933648 * 1024
    assert mem["Cached"] == 44607808 * 1024


def test_reported_memory_never_exceeds_physical(fixtures):
    """Unified memory: GPU and system memory are the SAME pool. Summing double-counts."""
    mem = read_meminfo(str(fixtures / "meminfo.txt"))
    used = mem["MemTotal"] - mem["MemAvailable"]
    assert 0 <= used <= mem["MemTotal"]


def test_tailscale_status_parses_real_json(fixtures):
    section = parse_status(json.loads((fixtures / "tailscale_status.json").read_text()))
    assert section.backend_state == "Running"
    assert section.self_hostname == "dgx-spark-01"
    assert section.self_dns_name.endswith(".ts.net")
    assert not section.self_dns_name.endswith(".")
    assert "100.64.0.1" in section.self_ips
    assert len(section.peers) == 3


def test_tailscale_parser_tolerates_a_schema_change():
    """Fields move between Tailscale versions; a missing key must not crash the collector."""
    section = parse_status({"BackendState": "Stopped"})
    assert section.backend_state == "Stopped"
    assert section.self_ips == [] and section.peers == []
    assert parse_status({}).backend_state == "Unknown"


def test_model_config_extracts_serving_facts(tmp_path):
    from dgxctl.collectors.models import read_model_config

    (tmp_path / "config.json").write_text(
        json.dumps(
            {
                "architectures": ["Qwen3MoeForCausalLM"],
                "max_position_embeddings": 262144,
                "num_experts_per_tok": 8,
                "quantization_config": {"quant_method": "modelopt_fp4"},
            }
        )
    )
    cfg = read_model_config(tmp_path)
    assert cfg["max_position_embeddings"] == 262144
    assert cfg["quantization"] == "modelopt_fp4"
    assert "MoE" in cfg["architecture"]


def test_malformed_model_config_does_not_raise(tmp_path):
    from dgxctl.collectors.models import read_model_config

    (tmp_path / "config.json").write_text("{ not json at all")
    assert read_model_config(tmp_path) == {}
    assert read_model_config(tmp_path / "nope") == {}


def test_credential_files_are_never_read(tmp_path):
    """Spec S9: a token or .env inside a scan root must never be opened."""
    from dgxctl.collectors.models import CREDENTIAL_NAMES, _dir_size

    (tmp_path / "weights.safetensors").write_bytes(b"x" * 100)
    (tmp_path / "token").write_text("hf_secretvalue")
    (tmp_path / ".env").write_text("API_KEY=secret")
    assert "token" in CREDENTIAL_NAMES and ".env" in CREDENTIAL_NAMES
    size, _ = _dir_size(tmp_path)
    assert size == 100, "credential files must not even be sized"


def test_ollama_list_parsing(fixtures, monkeypatch):
    from dgxctl.collectors import models as models_mod

    monkeypatch.setattr(
        models_mod, "run_cmd", lambda *a, **k: (fixtures / "ollama_list.txt").read_text()
    )
    collector = models_mod.ModelCollector(hf_cache=str(fixtures))
    out = collector._ollama()
    assert {m.id for m in out} == {"qwen3.5:4b", "nemotron-3-super:latest"}
    assert next(m for m in out if m.id == "qwen3.5:4b").size_bytes == 3_400_000_000


async def test_dual_stack_daemon_is_one_service_not_two():
    """Live finding: sshd on 0.0.0.0 and :: was listed twice."""
    from dgxctl.collectors.services import ServiceCollector

    listeners = [
        {
            "protocol": "tcp",
            "bind_ip": "0.0.0.0",
            "port": 6006,
            "exposure": "all",
            "pid": None,
            "process": None,
        },
        {
            "protocol": "tcp",
            "bind_ip": "::",
            "port": 6006,
            "exposure": "all",
            "pid": None,
            "process": None,
        },
    ]
    out = await ServiceCollector(lambda: listeners, lambda: [], lambda: []).collect()
    assert len(out["services"]) == 1


async def test_infrastructure_is_not_shown_as_a_service_but_is_still_reported():
    """Hidden, never dropped: the payload must stay an honest account of what is listening."""
    from dgxctl.collectors.services import ServiceCollector

    def listener(port, process=None):
        return {
            "protocol": "tcp",
            "bind_ip": "0.0.0.0",
            "port": port,
            "exposure": "all",
            "pid": None,
            "process": process,
        }

    # 8010 is not a well-known port: a model server is identified by its command line.
    listeners = [listener(p) for p in (22, 53, 5353, 41641)] + [listener(8010, "vllm")]
    out = await ServiceCollector(lambda: listeners, lambda: [], lambda: []).collect()

    shown = [s for s in out["services"] if s["notable"]]
    assert [s["port"] for s in shown] == [8010], "only the model server is a service here"
    assert len(out["services"]) == 5, "the rest are hidden, not discarded"
    assert {s["category"] for s in out["services"] if not s["notable"]} == {"infrastructure"}


async def test_unrecognised_listeners_are_hidden_and_labelled_as_such():
    """Requirement: everything in the default view explains what it is. Anything dgxctl
    cannot identify therefore does not belong there."""
    from dgxctl.collectors.services import ServiceCollector

    listeners = [
        {
            "protocol": "tcp",
            "bind_ip": "127.0.0.1",
            "port": 42835,
            "exposure": "loopback",
            "pid": None,
            "process": None,
        },  # unidentifiable
        {
            "protocol": "tcp",
            "bind_ip": "127.0.0.1",
            "port": 11434,
            "exposure": "loopback",
            "pid": None,
            "process": None,
        },  # ollama
    ]
    out = await ServiceCollector(lambda: listeners, lambda: [], lambda: []).collect()
    by_port = {s["port"]: s for s in out["services"]}
    assert by_port[42835]["notable"] is False
    assert by_port[42835]["recognised"] is False
    assert by_port[42835]["category"] == "unknown"
    assert by_port[11434]["notable"] is True
    assert by_port[11434]["summary"], "a shown service must say what it is"


async def test_ssh_is_not_offered_as_a_browser_link():
    from dgxctl.collectors.services import ServiceCollector

    listeners = [
        {
            "protocol": "tcp",
            "bind_ip": "0.0.0.0",
            "port": 22,
            "exposure": "all",
            "pid": None,
            "process": None,
        }
    ]
    out = await ServiceCollector(lambda: listeners, lambda: [], lambda: []).collect()
    assert out["services"][0]["kind"] == "ssh"
    assert out["services"][0]["linkable"] is False


# --- declared services (SDD-104) --------------------------------------------


async def test_declared_service_is_shown_even_when_offline():
    """R12.2: hiding it would hide its link and its launch control too."""
    from dgxctl.collectors.services import ServiceCollector
    from dgxctl.config import DeclaredService

    decl = [
        DeclaredService(
            id="openclaw",
            name="OpenClaw",
            port=8123,
            path="/",
            launch=["ollama", "launch", "openclaw"],
        )
    ]
    out = await ServiceCollector(lambda: [], lambda: [], lambda: [], declared=decl).collect()
    svc = out["services"][0]
    assert svc["name"] == "OpenClaw"
    assert svc["online"] is False
    assert svc["declared"] is True
    assert svc["launchable"] is True
    assert svc["notable"] is True


async def test_declared_service_merges_with_a_live_listener_on_its_port():
    from dgxctl.collectors.services import ServiceCollector
    from dgxctl.config import DeclaredService

    listeners = [
        {
            "protocol": "tcp",
            "bind_ip": "127.0.0.1",
            "port": 8123,
            "exposure": "loopback",
            "pid": None,
            "process": None,
        }
    ]
    decl = [DeclaredService(id="openclaw", name="OpenClaw", port=8123, kind="openclaw")]
    out = await ServiceCollector(lambda: listeners, lambda: [], lambda: [], declared=decl).collect()
    assert len(out["services"]) == 1, "a declared service must not duplicate its own listener"
    svc = out["services"][0]
    assert svc["name"] == "OpenClaw" and svc["online"] is True and svc["declared"] is True


async def test_declared_service_without_a_launch_command_is_not_launchable():
    from dgxctl.collectors.services import ServiceCollector
    from dgxctl.config import DeclaredService

    out = await ServiceCollector(
        lambda: [],
        lambda: [],
        lambda: [],
        declared=[DeclaredService(id="x", port=9001)],
    ).collect()
    assert out["services"][0]["launchable"] is False


def test_declared_launch_must_be_argv_not_a_shell_string():
    """Spec S8 reaches config too: a string here would become a shell injection point."""
    import pydantic
    import pytest as _pytest

    from dgxctl.config import DeclaredService

    with _pytest.raises(pydantic.ValidationError):
        DeclaredService(id="x", port=1, launch="ollama launch openclaw")


async def test_declared_service_carries_its_id_for_the_launch_action():
    """Deriving the id from the display name breaks the moment a service is renamed."""
    from dgxctl.collectors.services import ServiceCollector
    from dgxctl.config import DeclaredService

    decl = [
        DeclaredService(
            id="openclaw",
            name="OpenClaw Assistant",
            port=8123,
            launch=["ollama", "launch", "openclaw"],
        )
    ]
    out = await ServiceCollector(lambda: [], lambda: [], lambda: [], declared=decl).collect()
    assert out["services"][0]["id"] == "openclaw"


# --- pyenv torch detection (live regressions) --------------------------------


def test_torch_version_strips_the_dist_info_suffix(tmp_path):
    """Live regression: "torch-2.9.0+cu130.dist-info" parsed to "2.9.0+cu130.dist"."""
    from dgxctl.collectors.pyenvs import torch_from_site_packages

    (tmp_path / "torch-2.9.0+cu130.dist-info").mkdir()
    version, gpu = torch_from_site_packages(tmp_path)
    assert version == "2.9.0+cu130"
    assert gpu is True, "a +cu local version tag is conclusive on its own"


def test_torch_cuda_detected_through_a_type_annotation(tmp_path):
    """Live regression: torch/version.py writes `cuda: Optional[str] = '13.0'`, and a naive
    `cuda\\s*[:=]` never matches it — so a GPU environment was reported as CPU."""
    from dgxctl.collectors.pyenvs import torch_from_site_packages

    (tmp_path / "torch-2.9.0.dist-info").mkdir()
    torch_dir = tmp_path / "torch"
    torch_dir.mkdir()
    (torch_dir / "version.py").write_text(
        "from typing import Optional\n"
        "__version__ = '2.9.0'\n"
        "debug = False\n"
        "cuda: Optional[str] = '13.0'\n"
        "hip: Optional[str] = None\n"
    )
    version, gpu = torch_from_site_packages(tmp_path)
    assert version == "2.9.0"
    assert gpu is True


def test_cpu_only_torch_is_not_reported_as_gpu_capable(tmp_path):
    from dgxctl.collectors.pyenvs import torch_from_site_packages

    (tmp_path / "torch-2.9.0.dist-info").mkdir()
    torch_dir = tmp_path / "torch"
    torch_dir.mkdir()
    (torch_dir / "version.py").write_text("cuda: Optional[str] = None\n")
    assert torch_from_site_packages(tmp_path) == ("2.9.0", False)


def test_no_torch_at_all(tmp_path):
    from dgxctl.collectors.pyenvs import torch_from_site_packages

    assert torch_from_site_packages(tmp_path) == (None, False)


def test_openai_base_url_is_a_path_not_a_full_url():
    """Live regression: composing the origin server-side produced "…/docs/v1" and "…//v1"."""
    from dgxctl import endpoints

    for kind in ("vllm", "sglang", "llama.cpp", "ollama"):
        base = endpoints.describe(kind, 8010, ["m"])["base_url"]
        assert base == "/v1", f"{kind} base_url must be a bare path, got {base!r}"
        assert "http" not in base and "·" not in base


async def test_unidentified_listeners_on_the_tailnet_address_are_tailscale_itself():
    """Live finding: :45077 and :54847 bound to the node's own tailnet address are the
    Tailscale daemon's ephemeral ports. Nothing else binds there."""
    from dgxctl.collectors.services import ServiceCollector

    listeners = [
        {
            "protocol": "tcp",
            "bind_ip": "100.64.0.1",
            "port": 45077,
            "exposure": "tailnet",
            "pid": None,
            "process": None,
        },
        {
            "protocol": "tcp",
            "bind_ip": "127.0.0.1",
            "port": 11000,
            "exposure": "loopback",
            "pid": None,
            "process": None,
        },
    ]
    out = await ServiceCollector(
        lambda: listeners,
        lambda: [],
        lambda: [],
        tailnet_fn=lambda: ({"100.64.0.1"}, "dgx.example.ts.net"),
    ).collect()
    by_port = {s["port"]: s for s in out["services"]}
    assert by_port[45077]["kind"] == "tailscale"
    assert by_port[45077]["category"] == "infrastructure"
    # A loopback listener we cannot identify stays honestly unknown.
    assert by_port[11000]["category"] == "unknown"


def test_advertised_addresses_are_preferred_over_detected_ones():
    """Someone who reaches their DGX as `dgx.lab.internal` wants that in a link and a forward
    command, not a raw address that may change."""
    from dgxctl import endpoints

    host = endpoints.host_addresses(
        {"100.64.0.1"}, "dgx.example.ts.net", advertise=["dgx.lab.internal"]
    )
    assert host["lan"][0] == "dgx.lab.internal"
    assert host["tailnet_name"] == "dgx.example.ts.net"


def test_advertised_addresses_do_not_discard_detected_ones():
    from dgxctl import endpoints

    detected = endpoints.lan_addresses()
    host = endpoints.host_addresses(advertise=["dgx.lab.internal"])
    for addr in detected:
        assert addr in host["lan"], "a detected address must still be offered"


def test_no_advertised_addresses_leaves_detection_unchanged():
    from dgxctl import endpoints

    assert endpoints.host_addresses()["lan"] == endpoints.lan_addresses()


async def test_advertised_address_actually_reaches_the_services_section():
    """A wiring test, not a logic test. `host_addresses` grew an `advertise` parameter and
    behaved correctly in isolation while the collector kept calling it without the argument —
    the same class of seam bug that made an earlier config-preservation feature inert."""
    from dgxctl.collectors.services import ServiceCollector

    out = await ServiceCollector(
        lambda: [], lambda: [], lambda: [], advertise=["dgx.lab.internal"]
    ).collect()
    assert out["host"]["lan"][0] == "dgx.lab.internal"
