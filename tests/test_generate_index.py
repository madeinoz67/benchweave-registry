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
        "signed",
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
    assert row["signed"] is True
    assert "conformance-evidence-self-attested" in row["unverified_markers"]
    # F1 rework: the pin is advertised, never enforced.
    assert row["gateway_ref"] == "45d5e7fdc45dc6bbf765b1c8e85af70a2d830d94"
    assert row["firmware_attestation"] is None


def test_index_schema_validates_the_committed_index() -> None:
    import jsonschema

    schema = json.loads((REPO / "records" / "index.schema.json").read_bytes())
    index = json.loads((REPO / "index.json").read_bytes())
    jsonschema.Draft202012Validator(schema).validate(index)
