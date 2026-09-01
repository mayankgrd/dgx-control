"""A guard against host-specific data reaching a public repository (SDD-140).

This is a regression test, not a one-off review: fixtures and examples are captured from real
machines, and it is easy for a real address or path to arrive with them. Patterns are built
from parts so that this file does not itself contain the strings it forbids.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).parent.parent.parent

# Files that legitimately contain example addresses, and binaries we cannot grep.
SKIP_SUFFIXES = {".png", ".jpg", ".ico", ".woff", ".woff2", ".lock"}
SKIP_NAMES = {"package-lock.json", "LOCAL.md"}

# Addresses that are explicitly reserved for documentation, or scrubbed placeholders.
ALLOWED_ADDRESSES = {
    # Scrubbed placeholders used in the captured fixtures.
    "fd7a:115c:a1e0::1111:2222",
    "fd7a:115c:a1e0::1000:1",
    "fd7a:115c:a1e0::1001:1",
    "fd7a:115c:a1e0::1002:1",
    "100.64.0.1",
    "100.64.0.10",
    "100.64.0.11",
    "100.64.0.12",
    "100.64.0.9",
    "192.0.2.10",
    "192.0.2.11",
    "192.0.2.50",  # RFC 5737 TEST-NET-1
    # The CGNAT network address itself, used structurally in the exposure classifier.
    "100.64.0.0",
    # Invented values in tests. Each entry here is a deliberate acknowledgement: a NEW
    # address appearing in the tree fails this test until someone confirms it is not real.
    "100.64.0.5",
    "100.90.1.5",
    "100.90.3.4",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "::",
}

TAILNET_ULA = re.compile(r"fd7a:115c:a1e0::[0-9a-f:]+", re.I)
TAILNET_V4 = re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b")
TS_NET_HOST = re.compile(r"\b([a-z0-9-]+)\.([a-z0-9-]+)\.ts\.net\b", re.I)
HOME_PATH = re.compile(r"/(?:home|Users)/([a-z][a-z0-9_.-]{1,30})/", re.I)
SECRETISH = re.compile(
    r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\bnodekey:[0-9a-f]{40,}"
    r"|\bdiscokey:[0-9a-f]{40,}"
)
# Placeholders that are meant to be read as examples, not real accounts.
ALLOWED_HOME_USERS = {"dgxuser", "user", "youruser", "nvidia", "u", "n", "jovyan", "root", "home"}
ALLOWED_TS_LABELS = {"example", "example-tailnet", "your-tailnet", "tailnet", "spark-2"}


def tracked_text_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split()
    files = []
    for rel in out:
        p = REPO / rel
        if p.suffix in SKIP_SUFFIXES or p.name in SKIP_NAMES or not p.exists():
            continue
        files.append(p)
    return files


def scan(pattern: re.Pattern) -> list[tuple[str, str]]:
    hits = []
    for f in tracked_text_files():
        try:
            text = f.read_text(errors="replace")
        except OSError:
            continue
        for m in pattern.finditer(text):
            hits.append((str(f.relative_to(REPO)), m.group(0)))
    return hits


def test_no_real_tailnet_addresses():
    """Tailscale's ULA prefix is universal; the node suffix identifies a specific machine."""
    bad = [(f, v) for f, v in scan(TAILNET_ULA) if v.lower() not in ALLOWED_ADDRESSES]
    assert not bad, f"real tailnet IPv6 addresses: {bad}"

    bad4 = [(f, v) for f, v in scan(TAILNET_V4) if v not in ALLOWED_ADDRESSES]
    assert not bad4, f"real tailnet IPv4 addresses: {bad4}"


def test_no_real_magicdns_hostnames():
    bad = [
        (f, v)
        for f, v in scan(TS_NET_HOST)
        if not any(label in v.lower() for label in ALLOWED_TS_LABELS)
    ]
    assert not bad, f"real MagicDNS hostnames: {bad}"


def test_no_personal_home_paths():
    bad = []
    for f, v in scan(HOME_PATH):
        user = HOME_PATH.search(v).group(1)
        if user.lower() not in ALLOWED_HOME_USERS:
            bad.append((f, v))
    assert not bad, f"paths naming a real account: {bad}"


def test_no_credentials_or_keys():
    assert not scan(SECRETISH), "credential-shaped strings in the tree"


def test_local_notes_are_not_tracked():
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split()
    assert "LOCAL.md" not in tracked, "machine-specific notes must stay untracked"
    for name in tracked:
        assert not name.endswith(("/token", ".env")), f"{name} looks like a secret"
