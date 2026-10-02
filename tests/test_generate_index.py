"""The index format and its regeneration discipline (CR-21, Q7/CR-26).

The index is generated, never hand-edited: a records change without
regeneration refuses, and a hand-edited row refuses the same way. The format
test pins the row shape the website slice will render — additive consumption,
never a reshape.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
GENERATOR = REPO / "scripts" / "generate_index.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GENERATOR), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )


def test_index_is_committed_and_current() -> None:
    assert (REPO / "index.json").is_file()
    result = _run("--check")
    assert result.returncode == 0, result.stderr


def test_generation_is_byte_reproducible() -> None:
    first = _run("--root", str(REPO))
    assert first.returncode == 0, first.stderr
    committed = (REPO / "index.json").read_bytes()
    second = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, {str(REPO / 'scripts')!r}); "
         f"from generate_index import generate; "
         f"sys.stdout.buffer.write(generate(__import__('pathlib').Path({str(REPO)!r})))"],
        capture_output=True,
        check=False,
    )
    assert second.returncode == 0, second.stderr
    assert second.stdout == committed


def test_hand_edited_index_row_refuses(tmp_path: Path) -> None:
    """CR-21's falsifier: drift between the trees and the committed index refuses."""
    import shutil

    sandbox = tmp_path / "repo"
    shutil.copytree(REPO, sandbox, ignore=shutil.ignore_patterns("venv", ".git"))
    index = json.loads((sandbox / "index.json").read_bytes())
    assert index["rows"], "the dogfooded release must seed the index"
    index["rows"][0]["summary"] = "hand-edited summary"
    (sandbox / "index.json").write_bytes(
        json.dumps(index, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check", "--root", str(sandbox)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "index_drift" in result.stderr


def test_row_carries_the_catalogue_and_styleguide_fields() -> None:
    """The format is forward-complete for the website slice's rendering."""
    index = json.loads((REPO / "index.json").read_bytes())
    row = index["rows"][0]
    for field in (
        "kind",
        "publisher",
        "manifest_sha256",
        "signature_state",
        "display_name",
        "summary",
        "licence_spdx",
        "compatibility",
        "evidence",
        "maintenance",
        "advisories",
        "capabilities",
        "transport_triples",
        "source_revision",
        "unverified_markers",
    ):
        assert field in row, field
    assert row["kind"] == "admitted-release"
    assert row["signature_state"] == "signed-valid"
    assert row["timestamp"] is None
    assert row["timestamp_recommended"] is True
    assert "conformance-evidence-self-attested" in row["unverified_markers"]
    # F1 rework: the pin is advertised, never enforced.
    assert row["gateway_ref"] == "45d5e7fdc45dc6bbf765b1c8e85af70a2d830d94"
    assert row["firmware_attestation"] is None


def test_index_schema_validates_the_committed_index() -> None:
    import jsonschema

    schema = json.loads((REPO / "records" / "index.schema.json").read_bytes())
    index = json.loads((REPO / "index.json").read_bytes())
    jsonschema.Draft202012Validator(schema).validate(index)


# ── the yank arm (issue #224 slice 2, CR-25) ─────────────────────────────────
#
# A release directory carrying status.json with lifecycle yanked or revoked
# drops out of the generated index at regeneration — "no stale rows survive a
# yank or unlist" (CR-25); the record and git history retain it (CR-32's
# floor is history, not the catalogue). status.json is the single authority
# for this read (the same origin state file stock gateways consult, Q8).
# Absent status.json or lifecycle published|deprecated -> row present
# (today's dogfood, unchanged). Zero format motion: the row shape is
# untouched; only which rows exist moves.


def _fixture_release(
    root: Path,
    plugin: str = "alpha-tool",
    *,
    status: dict[str, object] | None = None,
    version: str = "1.0.0",
) -> Path:
    """A minimal release tree for the generator (invented names only)."""
    release = (
        root / "releases" / "benchweave-registry" / "northwind-instruments" / plugin / version
    )
    release.mkdir(parents=True)
    manifest = {
        "registry_id": "benchweave-registry",
        "package_id": f"northwind-instruments/{plugin}",
        "version": version,
        "publisher_id": "northwind-instruments",
        "display_name": f"Northwind {plugin}",
        "summary": "Synthetic fixture release for the catalogue yank arm.",
        "licence": {"spdx_expression": "MIT"},
        "compatibility": {
            "otdp_versions": ["0.2.2"],
            "adapter_api_versions": ["1.1"],
            "stg_versions": ["1.5"],
        },
        "evidence": [
            {"level": "simulated", "report_path": "evidence/report.md", "result": "passed"}
        ],
        "source": {"revision": "0" * 40},
    }
    (release / "manifest.json").write_bytes(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    if status is not None:
        (release / "status.json").write_bytes(
            json.dumps(status, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        )
    return release


def _row_ids(root: Path) -> list[str]:
    result = _run("--root", str(root))
    assert result.returncode == 0, result.stderr
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    return [row["package_id"] for row in index["rows"]]


def _rows(root: Path) -> list[dict[str, Any]]:
    _row_ids(root)
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = index["rows"]
    return rows


def test_absent_status_keeps_the_row(tmp_path: Path) -> None:
    """Today's dogfood shape is unchanged: no status document, row present."""
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(root)
    assert _row_ids(root) == ["northwind-instruments/alpha-tool"]


def test_published_status_keeps_the_row(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(root, status={"lifecycle": "published"})
    assert _row_ids(root) == ["northwind-instruments/alpha-tool"]


def test_deprecated_status_keeps_the_row(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(root, status={"lifecycle": "deprecated"})
    assert _row_ids(root) == ["northwind-instruments/alpha-tool"]


def test_yanked_release_drops_the_row(tmp_path: Path) -> None:
    """B1's yank arm, generator half: a yanked release is gone from the
    index at the next refresh — discovery must not offer what admission
    already refuses (CR-25)."""
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(root, status={"lifecycle": "yanked"})
    assert _row_ids(root) == []


def test_revoked_release_drops_the_row(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(root, status={"lifecycle": "revoked"})
    assert _row_ids(root) == []


def test_one_yanked_release_does_not_drop_the_others(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(root, plugin="alpha-tool", status={"lifecycle": "yanked"})
    _fixture_release(root, plugin="beta-tool")
    assert _row_ids(root) == ["northwind-instruments/beta-tool"]


def test_advisories_from_the_status_document_surface_in_the_row(tmp_path: Path) -> None:
    """The status document is the single authority for advisories too
    (Q8's origin status/lifecycle file): advisory ids reach the row the
    catalogue renders."""
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(
        root,
        status={
            "lifecycle": "published",
            "advisories": [
                {
                    "id": "BW-ADV-001",
                    "severity": "medium",
                    "summary": "Synthetic advisory for the yank-arm fixture.",
                    "url": "https://example.invalid/advisories/BW-ADV-001",
                }
            ],
        },
    )
    assert _rows(root)[0]["advisories"] == ["BW-ADV-001"]


def test_records_edit_without_regeneration_refuses(tmp_path: Path) -> None:
    """B2 plant 1 (re-proven on this slice's fixture trees): a status change
    without index regeneration reddens --check — the CR-21 falsifier."""
    root = tmp_path / "repo"
    root.mkdir()
    release = _fixture_release(root)
    first = _run("--root", str(root))
    assert first.returncode == 0, first.stderr
    (release / "status.json").write_bytes(
        json.dumps({"lifecycle": "yanked"}).encode() + b"\n"
    )
    check = _run("--check", "--root", str(root))
    assert check.returncode == 1, check.stdout + check.stderr
    assert "index_drift" in check.stderr
