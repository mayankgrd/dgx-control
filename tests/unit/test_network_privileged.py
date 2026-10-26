"""Socket owners through the privileged helper (SDD-172).

The same bytes go through the same parser either way; what changes is only whose sockets `ss`
is allowed to name.
"""

from __future__ import annotations

from pathlib import Path

from dgxctl.collectors.network import NetworkCollector

FIXTURES = Path(__file__).parent.parent / "fixtures"
# What an unprivileged `ss` sees: sshd's socket with no owner.
UNPRIV = 'tcp LISTEN 0 4096 0.0.0.0:22 0.0.0.0:*\ntcp LISTEN 0 4096 127.0.0.1:8770 0.0.0.0:* users:(("dgxctl",pid=99,fd=3))\n'
# What root sees for the same sockets.
PRIV = 'tcp LISTEN 0 4096 0.0.0.0:22 0.0.0.0:* users:(("sshd",pid=1201,fd=3))\ntcp LISTEN 0 4096 127.0.0.1:8770 0.0.0.0:* users:(("dgxctl",pid=99,fd=3))\n'


class FakeStatus:
    def __init__(self, state, fix=None):
        self.state, self.detail, self.fix = state, f"{state} detail", fix

    @property
    def usable(self):
        return self.state == "enabled"


class FakeRunner:
    def __init__(self, state="enabled", output=PRIV):
        self._status = FakeStatus(state, "sudo enable.sh")
        self._output = output
        self.calls = []

    def status(self):
        return self._status

    def run(self, sub):
        self.calls.append(sub)
        return self._output if self._status.usable else None


def collector(monkeypatch, runner):
    monkeypatch.setattr("dgxctl.collectors.network.run_cmd", lambda argv, t=10.0: UNPRIV)
    return NetworkCollector(privileged=runner)


async def test_network_uses_the_helper_when_available(monkeypatch):
    out = await collector(monkeypatch, FakeRunner()).collect()
    ssh = next(x for x in out["listeners"] if x["port"] == 22)
    assert ssh["process"] == "sshd" and ssh["pid"] == 1201
    assert out["owners_source"] == "privileged"
    assert out["hidden_owners"] == 0


async def test_network_falls_back_when_the_helper_fails(monkeypatch):
    out = await collector(monkeypatch, FakeRunner(output=None)).collect()
    ssh = next(x for x in out["listeners"] if x["port"] == 22)
    assert ssh["process"] is None
    assert out["owners_source"] == "unprivileged"


async def test_network_without_a_helper_reports_hidden_owners_and_how_to_fix(monkeypatch):
    out = await collector(monkeypatch, FakeRunner(state="not_installed")).collect()
    assert out["owners_source"] == "unprivileged"
    assert out["hidden_owners"] == 1
    assert out["privileged"] == "not_installed"
    assert "enable.sh" in out["privileged_fix"]


async def test_no_runner_at_all_is_the_old_behaviour(monkeypatch):
    monkeypatch.setattr("dgxctl.collectors.network.run_cmd", lambda argv, t=10.0: UNPRIV)
    out = await NetworkCollector().collect()
    assert out["owners_source"] == "unprivileged"
    assert out["privileged"] == "disabled"


async def test_privileged_output_goes_through_the_same_parser(monkeypatch):
    """No new parsing surface: the real captured fixture parses identically either way."""
    real = (FIXTURES / "ss_tulnpH.txt").read_text()
    monkeypatch.setattr("dgxctl.collectors.network.run_cmd", lambda argv, t=10.0: real)
    a = await NetworkCollector().collect()
    b = await NetworkCollector(privileged=FakeRunner(output=real)).collect()

    def strip(d):
        return [(x["bind_ip"], x["port"], x["process"]) for x in d["listeners"]]

    assert strip(a) == strip(b)


async def test_hidden_owner_count_ignores_sockets_attributed_to_a_container(monkeypatch):
    monkeypatch.setattr("dgxctl.collectors.network.run_cmd", lambda argv, t=10.0: UNPRIV)
    c = NetworkCollector(
        port_owner=lambda p: "tb" if p == 22 else None, privileged=FakeRunner(state="not_installed")
    )
    out = await c.collect()
    assert out["hidden_owners"] == 0, "a container-attributed socket is not hidden"


def test_app_passes_the_privileged_runner_to_the_network_collector():
    """Wiring, not logic. Three features in this project were complete and inert because the
    caller never passed the new argument."""
    from dgxctl.config import Settings
    from dgxctl.main import create_app
    from dgxctl.privileged import PrivilegedRunner

    app = create_app(Settings(privileged="off"), start_poller=False)
    net = next(c for c in app.state.poller.collectors if c.name == "network")
    assert isinstance(net._privileged, PrivilegedRunner)
    assert net._privileged.mode == "off", "the config value must reach the runner"
