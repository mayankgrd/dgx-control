"""Knowing what a listener IS (SDD-130, SDD-131)."""

from __future__ import annotations

import pytest

from dgxctl import services_catalog as sc


def test_every_entry_explains_itself():
    """An entry with no explanation defeats the point of the catalog."""
    for kind in sc.KINDS.values():
        assert kind.label, f"{kind.key}: no display label"
        assert kind.summary.endswith("."), f"{kind.key}: summary should read as a sentence"
        assert len(kind.summary.split()) >= 2, f"{kind.key}: summary is not an explanation"
        assert kind.category in sc.CATEGORY_ORDER, f"{kind.key}: unknown category"


def test_model_servers_declare_an_openai_api_path():
    for key in ("vllm", "sglang", "llama.cpp", "ollama", "lmstudio", "tgi"):
        kind = sc.get(key)
        assert kind.category == sc.LLM
        assert kind.api_path == "/v1", f"{key} should expose an OpenAI base URL"


@pytest.mark.parametrize(
    "key", ["ssh", "dns", "mdns", "cups", "tailscale", "docker-proxy", "iron-proxy", "ipykernel"]
)
def test_infrastructure_is_categorised_as_such(key):
    assert sc.get(key).category == sc.INFRA
    assert sc.INFRA in sc.HIDDEN_BY_DEFAULT


@pytest.mark.parametrize("key", ["hermes", "hermes-gateway", "openclaw"])
def test_agents_are_categorised_as_agents(key):
    assert sc.get(key).category == sc.AGENT


def test_unknown_falls_back_cleanly():
    kind = sc.get("something-nobody-has-heard-of")
    assert kind.category == sc.UNKNOWN
    assert kind.summary


def test_hermes_explains_that_a_browser_is_the_wrong_client():
    kind = sc.get("hermes")
    assert kind.web is False
    assert "401" in kind.note and "Desktop" in kind.note


# --- classification (SDD-131) ------------------------------------------------


def test_notebook_kernel_ports_are_infrastructure_not_services():
    """The live case: one kernel held eight ZMQ ports, each listed as a separate service."""
    cmd = "/home/u/jupyterlab/.venv/bin/python3 -m ipykernel_launcher -f /run/kernel-abc.json"
    for port in (35731, 40179, 46779, 46905):
        assert sc.get(sc.classify(cmd, "python3", port)).category == sc.INFRA


def test_tailscale_own_listeners_are_infrastructure():
    assert sc.get(sc.classify("", "", 443)).key == "tailscale"
    assert sc.get(sc.classify("", "", 41641)).key == "tailscale"
    assert (
        sc.get(sc.classify("/usr/sbin/tailscaled --state=/var/lib/tailscale")).category == sc.INFRA
    )


def test_hermes_internal_proxy_is_infrastructure_not_an_agent():
    kind = sc.get(sc.classify("/home/u/.hermes/bin/iron-proxy -config proxy.yaml", "", 9090))
    assert kind.key == "iron-proxy" and kind.category == sc.INFRA


def test_the_command_line_beats_a_port_hint():
    """A vLLM server on 8888 is a model server, not a notebook."""
    assert sc.classify("vllm serve Qwen/Qwen3-8B --port 8888", "", 8888) == "vllm"
    assert sc.classify("", "", 8888) == "jupyter"


def test_an_unreadable_command_line_degrades_to_the_port_hint():
    """`ss` shows no pid for another user's socket, so the port is the only evidence left."""
    assert sc.classify("", "", 22) == "ssh"
    assert sc.classify("", "", 11434) == "ollama"


def test_a_completely_unknown_listener_is_unknown():
    assert sc.classify("/opt/vendor/mystery-daemon --serve", "mystery", 57123) == "unknown"


def test_hermes_agent_and_gateway_are_distinguished():
    assert sc.classify("hermes gateway --config x") == "hermes-gateway"
    assert sc.classify("hermes serve --isolated --port 0") == "hermes"


def test_categories_have_display_labels_and_a_stable_order():
    assert set(sc.CATEGORY_LABELS) == set(sc.CATEGORY_ORDER)
    assert sc.CATEGORY_ORDER[0] == sc.LLM, "model servers are what people look for first"
    assert sc.CATEGORY_ORDER[-2:] == (sc.INFRA, sc.UNKNOWN)
