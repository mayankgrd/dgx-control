"""Privileged status in doctor and the CLI (SDD-174)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from dgxctl import privileged as pv
from dgxctl.config import Settings
from dgxctl.schemas import Status


@pytest.mark.parametrize(
    "state,expected",
    [
        (pv.ENABLED, Status.ok),
        (pv.NOT_INSTALLED, Status.unavailable),
        (pv.DISABLED, Status.unavailable),
        (pv.NOT_PERMITTED, Status.degraded),
        (pv.INSECURE, Status.error),
    ],
)
async def test_doctor_reports_privileged_status(monkeypatch, state, expected):
    from dgxctl import doctor

    monkeypatch.setattr(
        doctor.pv,
        "inspect",
        lambda helper=None, mode="auto", runner=None: pv.HelperStatus(state, f"{state}!", "do X"),
    )
    report = await doctor.run_doctor(Settings())
    check = next(c for c in report.checks if c.name == "privileged")
    assert check.status == expected
    if state != pv.ENABLED:
        assert check.fix == "do X"


async def test_doctor_flags_an_insecure_helper_as_a_failure(monkeypatch):
    """A helper sudo would run as root that a user can modify is a root shell. Doctor must fail."""
    from dgxctl import doctor

    monkeypatch.setattr(
        doctor.pv,
        "inspect",
        lambda helper=None, mode="auto", runner=None: pv.HelperStatus(pv.INSECURE, "bad", "fix"),
    )
    report = await doctor.run_doctor(Settings())
    assert report.ok is False


def test_cli_privileged_prints_status_and_both_commands(monkeypatch):
    from dgxctl.cli import app

    monkeypatch.setattr(
        "dgxctl.privileged.inspect",
        lambda helper=None, mode="auto", runner=None: pv.HelperStatus(
            pv.NOT_INSTALLED, "not installed — owners hidden", "sudo /x/enable.sh"
        ),
    )
    monkeypatch.setattr("dgxctl.privileged.enable_script", lambda: "/x/enable.sh")
    out = CliRunner().invoke(app, ["privileged"])
    assert out.exit_code == 0, out.output
    assert "not installed" in out.output
    assert "sudo /x/enable.sh" in out.output
    assert "sudo /x/enable.sh --remove" in out.output
    assert "--print-sudoers" in out.output, "the user should be able to read the rule first"
