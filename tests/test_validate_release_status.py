"""The independent release-status validity arm (issue #224 slice-2 pivot §3.2).

The pivot's lane-B-2 vacancy repair: the enum that governs a release's
lifecycle is enforced by its OWN step — this walk over every
``releases/**/status.json`` against the digest-pinned vendored copy of the
gateway's release-status schema — independent of ``generate_index.py``'s
regenerate-and-compare, so a wrongly-read authority cannot be
self-consistent by construction.

The pin test is the two-constants-one-link discipline (§3.2): the vendored
copy's digest is pinned against its origin, and repinning is a deliberate
recorded act, never a silent drift.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VALIDATOR = REPO / "scripts" / "validate_release_status.py"
PIN = REPO / "vendored" / "gateway" / "release-status.pin.json"
COPY = REPO / "vendored" / "gateway" / "release-status.schema.json"

#: The vendored bytes' origin, as recorded in the pin record.
ORIGIN = "madeinoz67/benchweave@c90f9f3:standards/registry/0.1.1/release-status.schema.json"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )


def test_the_vendored_copy_is_digest_pinned_to_its_origin() -> None:
    """The copy's bytes hash to the pin's sha256 and the pin cites the
    gateway's vendored 0.1.1 schema as source (repin = deliberate edit)."""
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    assert pin["source"] == ORIGIN, pin["source"]
    digest = hashlib.sha256(COPY.read_bytes()).hexdigest()
    assert digest == pin["sha256"], (
        f"the vendored release-status schema drifted from its pin "
        f"(on-disk {digest}, pinned {pin['sha256']}) — repin deliberately or restore"
    )


def test_the_enum_comes_from_the_schema_not_a_hand_list() -> None:
    """The authority is the schema's own enum block — four values, the exact
    set generate_index.py refuses and validates against."""
    schema = json.loads(COPY.read_text(encoding="utf-8"))
    enum = schema["properties"]["lifecycle"]["enum"]
    assert enum == ["published", "deprecated", "yanked", "revoked"], enum


def _release(status_bytes: bytes, root: Path, plugin: str = "alpha-tool") -> Path:
    release = root / "releases" / "benchweave-registry" / "northwind-instruments" / plugin / "1.0.0"
    release.mkdir(parents=True)
    (release / "status.json").write_bytes(status_bytes)
    return release


def test_valid_status_documents_pass(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _release(
        json.dumps(
            {
                "status_version": "0.1.1",
                "release": {
                    "registry_id": "benchweave-registry",
                    "package_id": "northwind-instruments/alpha-tool",
                    "version": "1.0.0",
                    "manifest_sha256": "0" * 64,
                },
                "sequence": 1,
                "updated_at": "2026-10-02T00:00:00Z",
                "expires_at": "2027-10-02T00:00:00Z",
                "lifecycle": "yanked",
                "reason": "synthetic yank for the boundary arm",
                "support_state": "maintained",
                "support_contact": "https://example.invalid/northwind",
                "reviews": [],
                "advisories": [],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        + b"\n",
        root,
    )
    result = _run("--root", str(root))
    assert result.returncode == 0, result.stdout + result.stderr


def test_out_of_enum_lifecycle_refuses_with_the_typed_prefix(tmp_path: Path) -> None:
    """Present-but-out-of-enum is exactly the class the independent step
    exists to catch — `Yanked`, `yank`, `retired` all refuse here."""
    for bad in ("Yanked", "yank", "retired"):
        root = tmp_path / f"repo-{bad}"
        root.mkdir()
        _release(json.dumps({"lifecycle": bad}).encode(), root)
        result = _run("--root", str(root))
        assert result.returncode == 1, f"{bad}: {result.stdout + result.stderr}"
        assert "status_invalid:" in result.stdout + result.stderr, bad


def test_missing_lifecycle_refuses(tmp_path: Path) -> None:
    """A status document without the lifecycle key is not schema-valid; the
    enum authority refuses it rather than letting the generator read a
    key-absent file as benign."""
    root = tmp_path / "repo"
    root.mkdir()
    _release(json.dumps({"reason": "no lifecycle key"}).encode(), root)
    result = _run("--root", str(root))
    assert result.returncode == 1
    assert "status_invalid:" in result.stdout + result.stderr


def test_malformed_status_refuses(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _release(b"not json at all", root)
    result = _run("--root", str(root))
    assert result.returncode == 1
    assert "status_invalid:" in result.stdout + result.stderr


def test_a_tree_with_no_status_documents_is_green(tmp_path: Path) -> None:
    """Today's dogfood shape: no release carries status.json yet, and the
    step is green by vacuity — disclosed, not hidden. The planted arms above
    are what make the step discriminating once the first status lands."""
    root = tmp_path / "repo"
    (root / "releases").mkdir(parents=True)
    result = _run("--root", str(root))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "no status documents" in result.stdout


def test_the_committed_tree_passes() -> None:
    result = _run()
    assert result.returncode == 0, result.stdout + result.stderr


def test_validator_script_is_executable_cli(tmp_path: Path) -> None:
    """The workflow invokes it bare; the sandbox copy proves --root routing."""
    root = tmp_path / "repo"
    root.mkdir()
    _release(json.dumps({"lifecycle": "published"}).encode(), root)
    result = _run("--root", str(root))
    assert result.returncode == 1, "an enum-only status document is not schema-valid"
    assert "status_invalid:" in result.stdout + result.stderr


def test_validator_runs_from_a_bare_checkout(tmp_path: Path) -> None:
    """The step must not depend on anything outside scripts/ + vendored/ —
    a bare copy of those two trees plus a release tree is enough."""
    root = tmp_path / "bare"
    (root / "scripts").mkdir(parents=True)
    (root / "vendored" / "gateway").mkdir(parents=True)
    shutil.copy2(VALIDATOR, root / "scripts" / VALIDATOR.name)
    shutil.copy2(COPY, root / "vendored" / "gateway" / COPY.name)
    _release(json.dumps({"lifecycle": "retired"}).encode(), root)
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / "validate_release_status.py"),
         "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "status_invalid:" in result.stdout + result.stderr
