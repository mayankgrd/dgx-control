"""Repo hygiene (SDD-124). These guard the things a newcomer trips over."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).parent.parent.parent
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
FENCED = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`]*`")


def prose(text: str) -> str:
    """Strip code so a documented example like `[x](y)` is not read as a real link."""
    return INLINE_CODE.sub("", FENCED.sub("", text))


def markdown_files() -> list[Path]:
    files = list(REPO.glob("*.md")) + list(REPO.glob("docs/*.md"))
    return [f for f in files if f.name != "LOCAL.md"]


# SPDX identifier -> a phrase that must appear in the licence text itself.
LICENCE_MARKERS = {
    "Apache-2.0": "Apache License",
    "MIT": "MIT License",
    "BSD-3-Clause": "BSD",
}


def test_licence_exists_and_matches_package_metadata():
    licence = REPO / "LICENSE"
    assert licence.exists(), "pyproject claims a licence; ship one"
    declared = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["license"]["text"]
    marker = LICENCE_MARKERS.get(declared)
    assert marker, f"unrecognised licence id {declared!r}; add it to LICENCE_MARKERS"
    assert marker.lower() in licence.read_text().lower(), (
        f"pyproject declares {declared} but LICENSE does not look like it"
    )


def test_apache_notice_file_is_shipped():
    """Apache 2.0 §4(d): a NOTICE file, if present, must be carried into redistributions.
    Shipping one is what makes that clause meaningful for downstream users."""
    declared = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]["license"]["text"]
    if declared != "Apache-2.0":
        return
    notice = REPO / "NOTICE"
    assert notice.exists(), "Apache-2.0 projects should ship a NOTICE file"
    text = notice.read_text()
    assert "Apache License" in text and "Copyright" in text


def test_the_licence_text_is_complete():
    """A truncated licence is worse than none: check the clauses that motivated the choice."""
    text = (REPO / "LICENSE").read_text()
    for clause in (
        "Grant of Patent License",
        "Redistribution",
        "Disclaimer of Warranty",
        "Limitation of Liability",
    ):
        assert clause in text, f"LICENSE is missing the {clause!r} section"


def test_no_broken_relative_links_in_markdown():
    """The docs move must not silently break references."""
    broken: list[str] = []
    for md in markdown_files():
        for target in MD_LINK.findall(prose(md.read_text())):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            path = target.split("#", 1)[0].split("?", 1)[0]
            if not path:
                continue
            resolved = (md.parent / path).resolve()
            if not resolved.exists():
                broken.append(f"{md.relative_to(REPO)} → {target}")
    assert not broken, "broken relative links:\n  " + "\n  ".join(broken)


def test_root_is_not_cluttered_with_process_docs():
    """A stranger's first look at the repo should read as a product, not a design folder."""
    root_md = {f.name for f in REPO.glob("*.md")} - {"LOCAL.md"}
    assert root_md == {"README.md", "CLAUDE.md"}, f"unexpected files at root: {root_md}"
    for expected in ("spec.md", "architecture.md", "SDD.md", "AUDIT.md", "prior_art.md"):
        assert (REPO / "docs" / expected).exists(), f"docs/{expected} is missing"


def test_readme_leads_with_installation():
    """Anyone should be able to install without reading the architecture first."""
    text = (REPO / "README.md").read_text()
    install_at = text.find("## Install")
    assert install_at != -1, "README has no install section"
    assert install_at < len(text) // 2, "install instructions are buried too deep"
    assert "install.sh" in text


def test_example_config_is_valid_toml_and_parses_as_settings():
    from dgxctl.config import Settings

    raw = (REPO / "config.example.toml").read_text()
    data = tomllib.loads(raw)
    data.pop("node", None)
    data["nodes"] = []
    data["services"] = data.pop("service", [])
    Settings(**data)  # must not raise


def test_gitignore_covers_secrets_and_state():
    text = (REPO / ".gitignore").read_text()
    for pattern in (".env", "token", "*.db", "LOCAL.md"):
        assert pattern in text, f"{pattern} is not ignored"
