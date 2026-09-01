"""The launch guards. Each one prevents a mistake that is expensive to diagnose."""

from __future__ import annotations

from pathlib import Path

import pytest

from dgxctl.catalog import (
    KNOWN_GOOD_VLLM_IMAGE,
    CatalogError,
    Entry,
    build_process_spec,
    build_run_spec,
    check_memory_budget,
    load_catalog,
)

CATALOG = Path(__file__).parent.parent.parent / "catalog" / "default.toml"


def entries():
    return {e.id: e for e in load_catalog(CATALOG)}


def test_default_catalog_loads_and_validates():
    e = entries()
    assert "vllm-server" in e and "jupyterlab" in e
    assert e["vllm-server"].image == KNOWN_GOOD_VLLM_IMAGE
    assert e["vllm-server"].kind == "container"
    assert e["jupyterlab"].kind == "process"


def test_bind_defaults_to_loopback_for_every_shipped_entry():
    for entry in entries().values():
        assert entry.bind == "127.0.0.1", f"{entry.id} does not default to loopback"


def test_published_port_always_carries_an_explicit_bind_address():
    """A bare `-p PORT:PORT` publishes on 0.0.0.0. It must be impossible to emit one."""
    built = build_run_spec(entries()["vllm-server"], {"model": "Qwen/Qwen3-8B"})
    ports = built["spec"]["ports"]
    assert ports == {"8010/tcp": ("127.0.0.1", 8010)}
    for value in ports.values():
        assert isinstance(value, tuple) and value[0] == "127.0.0.1"


def test_deep_gemm_disabled_on_every_vllm_entry():
    """sm_121 requires VLLM_USE_DEEP_GEMM=0."""
    assert entries()["vllm-server"].env["VLLM_USE_DEEP_GEMM"] == "0"


def test_unpinned_vllm_image_produces_the_driver_warning():
    entry = Entry(id="x", name="x", image="nvcr.io/nvidia/vllm:26.07-py3", args=["vllm", "serve"])
    from dgxctl.catalog import _apply_guards

    _apply_guards(entry)
    joined = " ".join(entry.warnings)
    assert "UnicodeDecodeError" in joined, "the misleading-error hint must be surfaced"
    assert KNOWN_GOOD_VLLM_IMAGE in joined


def test_wildcard_bind_entry_is_warned_about():
    entry = Entry(id="x", name="x", image="nginx", bind="0.0.0.0")
    from dgxctl.catalog import _apply_guards

    _apply_guards(entry)
    assert any("ALL interfaces" in w for w in entry.warnings)


def test_budget_guard_refuses_over_ceiling_and_names_the_cost():
    entry = entries()["vllm-server"]  # requests 0.50
    ok, why = check_memory_budget(entry, [0.50])
    assert not ok
    assert "0.50" in why and "0.70" in why
    assert "unified memory" in why.lower()


def test_budget_guard_allows_a_fitting_launch():
    ok, _ = check_memory_budget(entries()["vllm-server"], [0.10])
    assert ok


def test_budget_guard_ignores_entries_without_a_reservation():
    ok, _ = check_memory_budget(entries()["jupyterlab"], [0.70])
    assert ok, "an entry that reserves no GPU memory is not subject to the ceiling"


def test_unknown_parameters_are_rejected_not_ignored():
    with pytest.raises(CatalogError, match="unknown parameter"):
        build_run_spec(entries()["vllm-server"], {"model": "a", "extra_args": "--rm -v /:/host"})


def test_missing_required_parameter_is_rejected():
    with pytest.raises(CatalogError, match="missing required parameter"):
        build_run_spec(entries()["vllm-server"], {})


def test_parameters_substitute_as_argv_never_as_shell():
    """Spec S8: a param carrying shell metacharacters stays one inert argv element."""
    built = build_run_spec(entries()["vllm-server"], {"model": "evil; rm -rf /"})
    cmd = built["spec"]["command"]
    assert "evil; rm -rf /" in cmd
    assert isinstance(cmd, list)
    assert not any(isinstance(part, str) and part.startswith("sh ") for part in cmd)


# --- process entries (SDD-100..102) ----------------------------------------


def test_process_entry_command_is_argv_never_a_shell_string():
    entry = entries()["jupyterlab"]
    assert isinstance(entry.command, list)
    assert all(isinstance(part, str) for part in entry.command)
    assert not any(part.startswith("sh -c") or " && " in part for part in entry.command)


def test_process_entry_binds_loopback_by_default():
    entry = entries()["jupyterlab"]
    assert entry.bind == "127.0.0.1"
    # And the app itself is told to bind loopback, not 0.0.0.0: a host process has no
    # docker publish layer to constrain it afterwards.
    assert any("--ServerApp.ip=127.0.0.1" == part for part in entry.command)


def test_process_spec_substitutes_only_declared_params(tmp_path):
    venv = tmp_path / "venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "jupyter-lab").write_text("#!/bin/sh\n")
    built = build_process_spec(
        entries()["jupyterlab"],
        {"venv": str(tmp_path / "venv"), "root_dir": str(tmp_path), "port": "12345"},
    )
    assert built["argv"][0] == str(venv / "jupyter-lab")
    assert "12345" in built["argv"]
    assert built["port"] == 12345
    assert "{venv}" not in " ".join(built["argv"])


def test_process_spec_rejects_undeclared_params(tmp_path):
    with pytest.raises(CatalogError, match="unknown parameter"):
        build_process_spec(entries()["jupyterlab"], {"extra": "--allow-root"})


def test_missing_venv_refuses_with_an_actionable_message():
    with pytest.raises(CatalogError, match="does not exist"):
        build_process_spec(entries()["jupyterlab"], {"venv": "/nonexistent/venv"})


def test_build_run_spec_refuses_a_process_entry():
    with pytest.raises(CatalogError, match="not a container entry"):
        build_run_spec(entries()["jupyterlab"], {})


def test_build_process_spec_refuses_a_container_entry():
    with pytest.raises(CatalogError, match="not a process entry"):
        build_process_spec(entries()["vllm-server"], {"model": "x"})


def test_catalog_rejects_a_process_entry_with_no_command(tmp_path):
    bad = tmp_path / "c.toml"
    bad.write_text('[[entry]]\nid = "x"\nname = "X"\nkind = "process"\n')
    with pytest.raises(CatalogError, match="no command"):
        load_catalog(bad)


def test_catalog_rejects_a_container_entry_with_no_image(tmp_path):
    bad = tmp_path / "c.toml"
    bad.write_text('[[entry]]\nid = "x"\nname = "X"\n')
    with pytest.raises(CatalogError, match="no image"):
        load_catalog(bad)


def test_catalog_rejects_an_unknown_kind(tmp_path):
    bad = tmp_path / "c.toml"
    bad.write_text('[[entry]]\nid = "x"\nname = "X"\nkind = "vm"\nimage = "y"\n')
    with pytest.raises(CatalogError, match="unknown kind"):
        load_catalog(bad)


def test_launch_labels_record_the_reservation_for_the_budget_guard():
    built = build_run_spec(entries()["vllm-server"], {"model": "Qwen/Qwen3-8B"})
    labels = built["spec"]["labels"]
    assert labels["dgxctl.entry"] == "vllm-server"
    assert labels["dgxctl.gpu_memory_utilization"] == "0.5"


def test_resolved_executable_fills_in_defaults():
    """Live regression: find_running searched for the literal template "{venv}/bin/..."
    and therefore never adopted a running JupyterLab."""
    entry = entries()["jupyterlab"]
    assert "{venv}" in entry.executable, "the raw command is a template"
    resolved = entry.resolved_executable()
    assert "{" not in resolved
    assert resolved.endswith("/jupyterlab/.venv/bin/jupyter-lab")
    assert resolved.startswith("/"), "must be absolute so a process-table match can succeed"


def test_resolved_executable_honours_supplied_values():
    entry = entries()["jupyterlab"]
    assert entry.resolved_executable({"venv": "/opt/env"}) == "/opt/env/bin/jupyter-lab"
