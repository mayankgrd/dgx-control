#!/usr/bin/env python3
"""SDD-053 live verification: cross-check dgxctl's readings against the host's own tools.

Run ON the DGX:  python3 scripts/live_verify.py
The suite cannot see driver quirks, real cgroup layouts, or a genuinely exposed socket.
This can.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def _base() -> str:
    """Read the configured bind so this works whichever host dgxctl is listening on."""
    cfg = Path.home() / ".config/dgxctl/config.toml"
    host, port = "127.0.0.1", 8770
    if cfg.exists():
        import tomllib

        data = tomllib.loads(cfg.read_text())
        host = data.get("host", host)
        port = data.get("port", port)
    return f"http://{host}:{port}"


BASE = _base()
GiB = 2**30
failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}{f' — {detail}' if detail else ''}")
    if not ok:
        failures.append(label)


def sh(*argv: str) -> str:
    return subprocess.run(argv, capture_output=True, text=True).stdout.strip()


def fetch(path: str, token: str) -> dict:
    req = urllib.request.Request(f"{BASE}{path}", headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310
        return json.load(r)


def main() -> int:
    token = (Path.home() / ".config/dgxctl/token").read_text().strip()

    # Collectors populate on their own intervals, and the dependent ones wait for their
    # sources. Straight after a restart the snapshot is legitimately incomplete; waiting is
    # the correct behaviour, not treating a missing section as a failure.
    expected = {"gpu", "processes", "containers", "disk", "network", "services"}
    deadline = time.monotonic() + 90
    while True:
        S = fetch("/api/snapshot", token)["sections"]
        missing = expected - set(S)
        if not missing or time.monotonic() > deadline:
            break
        print(f"  waiting for {', '.join(sorted(missing))}…")
        time.sleep(5)
    if missing:
        print(f"\nSections never appeared after 90s: {sorted(missing)}")
        return 1

    print("\n1. Every collector reports a usable status")
    for name, env in sorted(S.items()):
        check(
            f"{name}: {env['status']}", env["status"] in ("ok", "unavailable"), env["error"] or ""
        )

    print("\n2. GPU readings agree with nvidia-smi")
    dev = S["gpu"]["data"]["devices"][0]
    smi = sh(
        "nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits"
    ).split(",")
    if len(smi) == 2:
        check(
            "temperature within 5C of nvidia-smi",
            abs(dev["temperature_c"] - float(smi[1])) <= 5,
            f"dgxctl={dev['temperature_c']} smi={smi[1].strip()}",
        )
    check(
        "driver version reported",
        bool(S["gpu"]["data"]["driver_version"]),
        str(S["gpu"]["data"]["driver_version"]),
    )

    print("\n3. Unified memory is one pool, never double-counted")
    mem = S["gpu"]["data"]["memory"]
    meminfo = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            meminfo[parts[0].rstrip(":")] = int(parts[1]) * 1024
    check(
        "used never exceeds physical",
        mem["used_bytes"] <= mem["total_bytes"],
        f"{mem['used_bytes'] / GiB:.1f} <= {mem['total_bytes'] / GiB:.1f} GiB",
    )
    check(
        "total matches /proc/meminfo",
        mem["total_bytes"] == meminfo["MemTotal"],
        f"{mem['total_bytes'] / GiB:.1f} GiB",
    )
    check(
        "reported as a unified pool",
        mem["unified"] is True,
        f"memory_source={dev['memory_source']}",
    )

    print("\n4. GPU processes attribute to their container (the PID-namespace seam)")
    procs = S["processes"]["data"]["gpu_processes"]
    smi_pids = {
        int(x)
        for x in sh("nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader").split()
        if x.strip().isdigit()
    }
    check(
        "every nvidia-smi compute PID is reported",
        smi_pids <= {p["pid"] for p in procs} or not smi_pids,
        f"smi={sorted(smi_pids)} dgxctl={sorted(p['pid'] for p in procs)}",
    )
    for p in procs:
        cg = Path(f"/proc/{p['pid']}/cgroup")
        in_container = cg.exists() and "docker-" in cg.read_text()
        print(
            f"        pid {p['pid']} {p['name'][:20]:20} "
            f"{(p['gpu_memory_bytes'] or 0) / GiB:5.1f} GiB → container={p['container_name']}"
        )
        if in_container:
            check(f"pid {p['pid']} resolved to a container", p["container_name"] is not None)

    print("\n5. Exposure findings agree with ss")
    findings = S["network"]["data"]["findings"]
    ss_nonloop = set()
    for line in sh("ss", "-tlnH").splitlines():
        parts = line.split()
        if len(parts) >= 4:
            local = parts[3]
            host, _, port = local.rpartition(":")
            host = host.strip("[]").split("%")[0]
            if not (host.startswith("127.") or host == "::1"):
                ss_nonloop.add(int(port))
    reported = {f["port"] for f in findings if f["protocol"] == "tcp"}
    for f in findings:
        print(
            f"        {f['exposure']:9} {f['bind_ip']:>26}:{f['port']:<6} "
            f"{f['process'] or f['container_name'] or '(owner not visible)'}"
        )
    check(
        "every non-loopback TCP port from ss appears as a finding",
        ss_nonloop <= reported,
        f"ss={sorted(ss_nonloop)} dgxctl={sorted(reported)}",
    )
    check(
        "no loopback socket is misreported as a finding",
        all(not f["bind_ip"].startswith("127.") for f in findings),
    )

    print("\n6. Container port bindings preserve the host bind address")
    for c in S["containers"]["data"]["containers"]:
        for p in c["ports"]:
            if p["host_port"]:
                real = sh("docker", "port", c["name"], f"{p['container_port']}/{p['protocol']}")
                print(
                    f"        {c['name'][:18]:18} {p['host_ip']}:{p['host_port']} "
                    f"({p['exposure']}) | docker port: {real.splitlines()[0] if real else '-'}"
                )
                if real:
                    check(
                        f"{c['name']}:{p['host_port']} bind matches docker",
                        p["host_ip"] in real or (p["host_ip"] == "0.0.0.0" and "0.0.0.0" in real),
                    )

    print("\n7. Docker and disk figures agree with the host")
    df_root = sh("df", "-B1", "--output=used,size,target", "/").splitlines()
    if len(df_root) > 1:
        used, size, _ = df_root[1].split()
        fs = next((f for f in S["disk"]["data"]["filesystems"] if f["mountpoint"] == "/"), None)
        if fs:
            check(
                "root filesystem size matches df",
                abs(fs["total_bytes"] - int(size)) < GiB,
                f"{fs['total_bytes'] / 2**40:.2f} TiB",
            )
    hf = sh("du", "-sb", str(Path.home() / ".cache/huggingface")).split()
    root = next((r for r in S["disk"]["data"]["sized_roots"] if "huggingface" in r["path"]), None)
    if hf and root and root["size_bytes"]:
        drift = abs(root["size_bytes"] - int(hf[0])) / int(hf[0])
        check(
            "HF cache size within 5% of du",
            drift < 0.05,
            f"dgxctl={root['size_bytes'] / GiB:.1f} du={int(hf[0]) / GiB:.1f} GiB",
        )

    print("\n8. Model inventory")
    m = S["models"]["data"]
    check("models discovered", len(m["models"]) > 0, f"{len(m['models'])} models")
    hub = Path.home() / ".cache/huggingface/hub"
    on_disk = (
        len([d for d in hub.iterdir() if d.name.startswith("models--")]) if hub.is_dir() else 0
    )
    hf_count = len([x for x in m["models"] if x["source"] == "huggingface"])
    check(
        "every HF cache entry is inventoried",
        hf_count == on_disk,
        f"dgxctl={hf_count} on-disk={on_disk}",
    )
    for x in m["models"][:3]:
        print(
            f"        {x['id'][:40]:40} {x['size_bytes'] / GiB:6.1f} GiB "
            f"ctx={x['max_position_embeddings']} quant={x['quantization']}"
        )

    print("\n9. Services and model serving")
    for s in S["services"]["data"]["services"][:10]:
        print(
            f"        {s['kind']:14} :{s['port']:<6} {s['exposure']:9} {s['health']:12} "
            f"{s['served_models']}"
        )
    check("at least one service discovered", len(S["services"]["data"]["services"]) > 0)

    print("\n10. Security posture")
    code = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", f"{BASE}/api/snapshot"],
        capture_output=True,
        text=True,
    ).stdout
    check("unauthenticated snapshot is rejected", code == "401", f"HTTP {code}")
    code = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", f"{BASE}/api/health"],
        capture_output=True,
        text=True,
    ).stdout
    check("health stays public", code == "200", f"HTTP {code}")
    code = subprocess.run(
        [
            "curl",
            "-s",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            f"{BASE}/api/stream?ticket={token}",
        ],
        capture_output=True,
        text=True,
    ).stdout
    check("the long-lived token is refused as a query parameter", code == "401", f"HTTP {code}")

    print("\n11. The UI is served from the same single port")
    html = subprocess.run(["curl", "-s", BASE], capture_output=True, text=True).stdout
    check("SPA served on the API port", '<div id="root">' in html)
    code = subprocess.run(
        ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", f"{BASE}/api/nope"],
        capture_output=True,
        text=True,
    ).stdout
    check(
        "unknown /api path 404s rather than serving the SPA", code in ("404", "401"), f"HTTP {code}"
    )

    print(f"\n{'=' * 64}")
    if failures:
        print(f"{len(failures)} check(s) FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("All live checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
