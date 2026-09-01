"""The OpenAPI document is the frontend's source of types. It must never go stale."""

from __future__ import annotations

import json
from pathlib import Path

from dgxctl.config import Settings
from dgxctl.main import create_app

REPO = Path(__file__).parent.parent.parent
SCHEMA = REPO / "openapi.json"


def current_schema() -> dict:
    return create_app(Settings(host="127.0.0.1"), start_poller=False).openapi()


def test_committed_openapi_is_current():
    """Frontend types are generated from this file. If it drifts, the UI types lie.

    Regenerate with:  dgxctl schema --out openapi.json
    """
    assert SCHEMA.exists(), "openapi.json is missing; run `dgxctl schema --out openapi.json`"
    committed = json.loads(SCHEMA.read_text())
    assert committed == current_schema(), (
        "openapi.json is out of date with the API. "
        "Run `dgxctl schema --out openapi.json` and commit the result."
    )


def test_every_section_payload_is_in_the_schema():
    schemas = current_schema()["components"]["schemas"]
    for name in (
        "GpuSection",
        "ProcessSection",
        "ContainerSection",
        "ImageSection",
        "DiskSection",
        "NetworkSection",
        "TailscaleSection",
        "ServiceSection",
        "ModelSection",
        "PyEnvSection",
    ):
        assert name in schemas, f"{name} would be invisible to the type generator"


def test_exposure_vocabulary_is_pinned_in_the_contract():
    """The UI styles these four levels by name; adding one silently would break FE-C4."""
    enum = current_schema()["components"]["schemas"]["Exposure"]["enum"]
    assert set(enum) == {"loopback", "lan", "tailnet", "all", "unknown"}


def test_health_response_carries_no_host_fields():
    props = current_schema()["components"]["schemas"]["HealthResponse"]["properties"]
    assert set(props) == {"status", "version", "uptime_seconds"}
