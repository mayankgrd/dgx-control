"""Preflight: which collectors will work on this host, and how to fix the ones that won't."""

from __future__ import annotations

import asyncio
from pathlib import Path

from dgxctl.collectors.base import have
from dgxctl.config import Settings
from dgxctl.docker_client import get_client, get_error
from dgxctl.schemas import DoctorCheck, DoctorReport, Status


async def run_doctor(settings: Settings) -> DoctorReport:
    checks: list[DoctorCheck] = []

    # NVML
    try:
        import pynvml

        await asyncio.to_thread(pynvml.nvmlInit)
        count = pynvml.nvmlDeviceGetCount()
        name = pynvml.nvmlDeviceGetName(pynvml.nvmlDeviceGetHandleByIndex(0))
        name = name.decode() if isinstance(name, bytes) else name
        try:
            pynvml.nvmlDeviceGetMemoryInfo(pynvml.nvmlDeviceGetHandleByIndex(0))
            mem_note = "NVML reports GPU memory"
            status = Status.ok
        except Exception:  # noqa: BLE001
            mem_note = (
                "NVML memory query unsupported (unified memory) - totals read from /proc/meminfo"
            )
            status = Status.degraded
        checks.append(
            DoctorCheck(name="nvml", status=status, detail=f"{count} device(s): {name}. {mem_note}")
        )
    except ImportError:
        checks.append(
            DoctorCheck(
                name="nvml",
                status=Status.unavailable,
                detail="nvidia-ml-py not installed",
                fix="pip install nvidia-ml-py",
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            DoctorCheck(
                name="nvml",
                status=Status.unavailable,
                detail=str(exc)[:200],
                fix="Check the NVIDIA driver is loaded (nvidia-smi)",
            )
        )

    # Docker
    client = await asyncio.to_thread(get_client)
    if client is None:
        checks.append(
            DoctorCheck(
                name="docker",
                status=Status.unavailable,
                detail=str(get_error())[:200],
                fix="Add your user to the `docker` group, then log out and back in",
            )
        )
    else:
        try:
            version = client.version().get("Version", "?")
            n = len(client.containers.list(all=True))
            checks.append(
                DoctorCheck(
                    name="docker",
                    status=Status.ok,
                    detail=f"Docker {version}, {n} container(s) visible",
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(DoctorCheck(name="docker", status=Status.degraded, detail=str(exc)[:200]))

    for binary, fix in (("ss", "apt install iproute2"), ("du", "part of coreutils")):
        checks.append(
            DoctorCheck(
                name=binary,
                status=Status.ok if have(binary) else Status.unavailable,
                detail=f"`{binary}` {'found' if have(binary) else 'not found'}",
                fix=None if have(binary) else fix,
            )
        )

    checks.append(
        DoctorCheck(
            name="tailscale",
            status=Status.ok if have("tailscale") else Status.unavailable,
            detail="tailscale CLI found" if have("tailscale") else "tailscale CLI not installed",
        )
    )

    hf = Path(settings.hf_cache).expanduser()
    checks.append(
        DoctorCheck(
            name="hf_cache",
            status=Status.ok if hf.is_dir() else Status.unavailable,
            detail=f"{hf} {'exists' if hf.is_dir() else 'does not exist'}",
            fix=None if hf.is_dir() else "Set hf_cache in config.toml if your cache is elsewhere",
        )
    )

    # The security posture check: this is the one that matters on a shared network.
    token_exists = settings.token_path.exists()
    if settings.is_loopback:
        checks.append(
            DoctorCheck(
                name="bind",
                status=Status.ok,
                detail=f"binding {settings.host}:{settings.port} (loopback only)",
            )
        )
    elif token_exists:
        checks.append(
            DoctorCheck(
                name="bind",
                status=Status.degraded,
                detail=f"binding {settings.host}:{settings.port} - reachable beyond this "
                f"host; token auth is active",
                fix='Prefer host = "127.0.0.1" plus an SSH tunnel where possible',
            )
        )
    else:
        checks.append(
            DoctorCheck(
                name="bind",
                status=Status.error,
                detail=f"binding {settings.host}:{settings.port} with NO token - "
                f"dgxctl will refuse to start",
                fix="dgxctl token --init",
            )
        )

    checks.append(
        DoctorCheck(
            name="control",
            status=Status.ok,
            detail=f"control actions {'ENABLED' if settings.control_enabled else 'disabled'}",
            fix=None if settings.control_enabled else "Set control_enabled = true to allow actions",
        )
    )

    report = DoctorReport(checks=checks)
    report.ok = not any(c.status == Status.error for c in checks)
    return report
