"""verify.py arms: the clone-alone verifier under the publisher-signature model."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

REPO = Path(__file__).resolve().parents[1]
import verify as V  # noqa: E402


def _sandbox(tmp_path: Path) -> Path:
    sandbox = tmp_path / "repo"
    shutil.copytree(
        Path(__file__).resolve().parents[1],
        sandbox,
        ignore=shutil.ignore_patterns("venv", ".git", "__pycache__"),
    )
    return sandbox


def test_clean_clone_verifies(tmp_path: Path) -> None:
    findings, chains = V.verify_releases(_sandbox(tmp_path))
    assert findings == [], findings
    assert chains and chains[0]["signature_state"] == "signed-valid"


def test_tampered_signed_bytes_are_caught(tmp_path: Path) -> None:
    """A byte flipped in the publisher-signed bytes after recording."""
    sandbox = _sandbox(tmp_path)
    signed = (
        sandbox / "releases/benchweave-registry/madeinoz67/dps150/0.1.0"
        / "submission-manifest.json"
    )
    raw = signed.read_bytes()
    signed.write_bytes(raw[:-2] + b"x\n" if raw.endswith(b"\n") else raw + b"x")
    findings, _chains = V.verify_releases(sandbox)
    assert any(f.startswith("signature_invalid:") for f in findings), findings


def test_unsigned_label_with_a_signature_file_is_caught(tmp_path: Path) -> None:
    sandbox = _sandbox(tmp_path)
    record = (
        sandbox / "records/lifecycle/madeinoz67/dps150/0.1.0/1-publish.json"
    )
    import json

    parsed = json.loads(record.read_bytes())
    parsed["lifecycle"]["signature_state"] = "unsigned"
    record.write_bytes(
        json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    findings, _chains = V.verify_releases(sandbox)
    assert any(f.startswith("signature_unexpected:") for f in findings), findings


# ── C6 (issue #225 slice 3): the chain carries the lifecycle timeline ─────────


def test_chain_carries_the_lifecycle_event_timeline(tmp_path: Path) -> None:
    """§2.6: beside publisher/reviewer/outcome/signature/closure/capabilities,
    the chain now prints the release's lifecycle event timeline, sourced from
    the already-validated records — one field, nothing new to trust."""
    sandbox = _sandbox(tmp_path)
    findings, chains = V.verify_releases(sandbox)
    assert findings == [], findings
    assert chains[0]["lifecycle_events"] == [
        {"op": "publish", "actor": "madeinoz67", "at": "2026-10-01T00:00:00Z"}
    ], chains[0]


def test_chain_output_prints_the_timeline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sandbox = _sandbox(tmp_path)
    assert V.main([str(sandbox)]) == 0
    out = capsys.readouterr().out
    assert "lifecycle=publish" in out, out


def test_cli_argv_routes_to_the_given_tree(tmp_path: Path) -> None:
    """B1 (lane B F3): the CLI entry dropped argv entirely — a bare
    `python scripts/verify.py <path>` always validated the script's own
    repo and exited 0. Against a TAMPERED tree the CLI must exit 1 (the
    #146 class: a green read of the wrong tree)."""
    import subprocess
    import sys as _sys

    sandbox = _sandbox(tmp_path)
    signed = (
        sandbox / "releases/benchweave-registry/madeinoz67/dps150/0.1.0"
        / "submission-manifest.json"
    )
    raw = signed.read_bytes()
    signed.write_bytes(raw[:-2] + b"x\n" if raw.endswith(b"\n") else raw + b"x")
    result = subprocess.run(
        [_sys.executable, str(REPO / "scripts" / "verify.py"), str(sandbox)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, (
        f"the CLI green-read the WRONG tree (argv dropped):\n{result.stdout}"
    )
