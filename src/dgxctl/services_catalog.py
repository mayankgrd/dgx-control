"""What dgxctl knows about the things that listen on this machine (spec R15).

A port number is not an answer to "what is running and how do I use it". Everything shown in
the default view has a name, a one-line explanation, and a category; anything this file cannot
identify is `unknown` and stays collapsed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

LLM = "llm"
NOTEBOOK = "notebook"
AGENT = "agent"
TOOL = "tool"
INFRA = "infrastructure"
UNKNOWN = "unknown"

CATEGORY_ORDER = (LLM, NOTEBOOK, AGENT, TOOL, INFRA, UNKNOWN)
CATEGORY_LABELS = {
    LLM: "Model servers",
    NOTEBOOK: "Notebooks",
    AGENT: "Agents",
    TOOL: "Tools",
    INFRA: "Infrastructure",
    UNKNOWN: "Unrecognised",
}
HIDDEN_BY_DEFAULT = (INFRA, UNKNOWN)


@dataclass(frozen=True)
class Kind:
    key: str
    label: str
    summary: str  # what this thing IS, in one line
    category: str
    ui_path: str = "/"  # what to open in a browser
    api_path: str | None = None  # OpenAI-compatible base, where there is one
    web: bool = True  # is a browser the right client at all?
    note: str | None = None


KINDS: dict[str, Kind] = {
    k.key: k
    for k in [
        Kind(
            "vllm",
            "vLLM",
            "OpenAI-compatible server for a local model.",
            LLM,
            ui_path="/docs",
            api_path="/v1",
        ),
        Kind(
            "sglang",
            "SGLang",
            "OpenAI-compatible server for a local model.",
            LLM,
            ui_path="/docs",
            api_path="/v1",
        ),
        Kind(
            "llama.cpp",
            "llama.cpp",
            "OpenAI-compatible server for GGUF models.",
            LLM,
            api_path="/v1",
        ),
        Kind(
            "ollama",
            "Ollama",
            "Local model runtime with an OpenAI-compatible API.",
            LLM,
            api_path="/v1",
            note="Also speaks its own API at /api.",
        ),
        Kind(
            "lmstudio",
            "LM Studio",
            "Desktop model runtime with an OpenAI-compatible API.",
            LLM,
            api_path="/v1",
        ),
        Kind("tgi", "Text Generation Inference", "Hugging Face model server.", LLM, api_path="/v1"),
        Kind("jupyter", "JupyterLab", "Notebook server with direct GPU access.", NOTEBOOK),
        Kind(
            "hermes",
            "Hermes",
            "Coding agent backend for Hermes Desktop and the CLI.",
            AGENT,
            web=False,
            note="Authenticates with a per-session token it prints at startup, so a browser "
            "gets 401 — that is expected. Connect with Hermes Desktop or `hermes`.",
        ),
        Kind(
            "hermes-gateway",
            "Hermes gateway",
            "Messaging gateway for Hermes (Signal, Telegram, Discord).",
            AGENT,
            web=False,
        ),
        Kind("openclaw", "OpenClaw", "Local coding agent.", AGENT),
        Kind("open-webui", "Open WebUI", "Browser chat front-end for local models.", AGENT),
        Kind("comfyui", "ComfyUI", "Node-based image generation UI.", TOOL),
        Kind("tensorboard", "TensorBoard", "Training run visualiser.", TOOL),
        Kind("gradio", "Gradio app", "Python-authored demo UI.", TOOL),
        Kind("streamlit", "Streamlit app", "Python-authored data app.", TOOL),
        Kind("ssh", "SSH", "Remote shell access to this machine.", INFRA, web=False),
        Kind("dns", "DNS resolver", "Local name resolution.", INFRA, web=False),
        Kind("mdns", "mDNS", "Local network service discovery.", INFRA, web=False),
        Kind("cups", "CUPS", "Printing service.", INFRA, web=False),
        Kind(
            "tailscale",
            "Tailscale",
            "Tailnet networking daemon and its own listeners.",
            INFRA,
            web=False,
        ),
        Kind(
            "docker-proxy", "Docker proxy", "Forwards a published container port.", INFRA, web=False
        ),
        Kind(
            "iron-proxy",
            "Hermes proxy",
            "Internal proxy used by the Hermes agent runtime.",
            INFRA,
            web=False,
        ),
        Kind(
            "ipykernel",
            "Notebook kernel",
            "ZMQ ports belonging to a running notebook kernel.",
            INFRA,
            web=False,
        ),
        Kind("dgxctl", "DGX Control", "This dashboard.", INFRA),
    ]
}

UNKNOWN_KIND = Kind(
    "unknown",
    "Unrecognised service",
    "dgxctl does not recognise this listener.",
    UNKNOWN,
)


def get(kind: str) -> Kind:
    return KINDS.get(kind, UNKNOWN_KIND)


# Matched against the listener's FULL command line, most specific first. Command line beats a
# port hint: a vLLM server on 8888 is a model server, not a notebook.
CMDLINE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ipykernel", re.compile(r"ipykernel_launcher|ipykernel\b", re.I)),
    ("iron-proxy", re.compile(r"iron-proxy", re.I)),
    ("hermes-gateway", re.compile(r"hermes\s+gateway", re.I)),
    ("hermes", re.compile(r"\bhermes\b", re.I)),
    ("vllm", re.compile(r"\bvllm\b", re.I)),
    ("sglang", re.compile(r"sglang", re.I)),
    ("llama.cpp", re.compile(r"llama[-_]?(server|cpp)", re.I)),
    ("ollama", re.compile(r"\bollama\b", re.I)),
    ("jupyter", re.compile(r"jupyter[-_]?lab|jupyter[-_]?notebook|\bjupyter\b", re.I)),
    ("comfyui", re.compile(r"comfy", re.I)),
    ("tensorboard", re.compile(r"tensorboard", re.I)),
    ("open-webui", re.compile(r"open[-_]?webui", re.I)),
    ("streamlit", re.compile(r"streamlit", re.I)),
    ("gradio", re.compile(r"gradio", re.I)),
    ("openclaw", re.compile(r"openclaw", re.I)),
    ("tailscale", re.compile(r"tailscaled?\b", re.I)),
    ("docker-proxy", re.compile(r"docker-proxy", re.I)),
    ("dgxctl", re.compile(r"\bdgxctl\b", re.I)),
    ("cups", re.compile(r"\bcupsd\b", re.I)),
    ("dns", re.compile(r"systemd-resolve|\bdnsmasq\b|\bnamed\b", re.I)),
    ("mdns", re.compile(r"avahi|mdns", re.I)),
    ("ssh", re.compile(r"\bsshd\b", re.I)),
]

# Only consulted when the command line says nothing — a root-owned socket shows no pid to an
# unprivileged `ss`, and then the port is the only evidence there is.
PORT_HINTS: dict[int, str] = {
    22: "ssh",
    53: "dns",
    443: "tailscale",  # tailscale serve binds :443 on the tailnet address
    631: "cups",
    1234: "lmstudio",
    5353: "mdns",
    6006: "tensorboard",
    7860: "gradio",
    8080: "open-webui",
    8188: "comfyui",
    8501: "streamlit",
    8888: "jupyter",
    11434: "ollama",
    41641: "tailscale",
}


def classify(cmdline: str = "", process: str = "", port: int | None = None) -> str:
    """Identify a listener. Command line first, process name next, port last."""
    for text in (cmdline, process):
        if not text:
            continue
        for key, pattern in CMDLINE_PATTERNS:
            if pattern.search(text):
                return key
    if port is not None and port in PORT_HINTS:
        return PORT_HINTS[port]
    return "unknown"
