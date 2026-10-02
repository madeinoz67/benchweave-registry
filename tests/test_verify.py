"""verify.py arms: the clone-alone verifier under the publisher-signature model."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
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
