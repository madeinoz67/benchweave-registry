"""C3(a): the admission replay's fixture mode (issue #225 slice 3).

A runtime-keyed fixture origin — Ed25519 keypair generated in-test, release
tree built from the committed dogfooded bytes — replayed through the PINNED
GATEWAY'S OWN ``Resolver`` + ``admit`` via ``replay_admission.py --fixture``.
The yank discriminator: identical bytes, one field different (the status
document's lifecycle), opposite outcomes. No arm depends on uncommitted key
material (the §1.2 lesson).

The gateway-checkout arm is skip-guarded (owner ruling, issue #223 rework):
the replay is an ON-DEMAND tool, not a publish-time CI gate, so CI never
needs a gateway checkout. The guard names the family-checkout path and the
``BENCHWEAVE_GATEWAY_CHECKOUT`` override.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

REPO = Path(__file__).resolve().parents[1]
REPLAY = REPO / "scripts" / "replay_admission.py"
REGISTRY_ID = "benchweave-registry"
RELEASE = REPO / "releases" / REGISTRY_ID / "madeinoz67" / "dps150" / "0.1.0"

#: The family checkout convention: the gateway repo lives beside this repo's
#: checkout root (a linked worktree resolves through its parents). CI has no
#: sibling and skips; ``BENCHWEAVE_GATEWAY_CHECKOUT`` overrides everywhere.
def _default_gateway_checkout() -> Path | None:
    for parent in REPO.parents:
        candidate = parent / "BenchWeave"
        if (candidate / "src" / "benchweave" / "registry").is_dir():
            return candidate
    return None


GATEWAY_CHECKOUT = Path(
    os.environ.get(
        "BENCHWEAVE_GATEWAY_CHECKOUT",
        str(_default_gateway_checkout() or REPO.parent / "BenchWeave"),
    )
)

requires_gateway = pytest.mark.skipif(
    not (GATEWAY_CHECKOUT / "src" / "benchweave" / "registry").is_dir(),
    reason=f"gateway checkout not available at {GATEWAY_CHECKOUT} "
    "(the replay is on-demand by ruling; set BENCHWEAVE_GATEWAY_CHECKOUT to override)",
)


def _canonical(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _build_fixture_origin(root: Path, lifecycle: str) -> tuple[Path, Path]:
    """A runtime-keyed fixture origin: the committed dogfooded release bytes,
    re-signed by a fresh Ed25519 fixture root, with a status document at the
    given lifecycle. Returns (origin_root, public_root_pem)."""
    key = Ed25519PrivateKey.generate()
    pub_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    keys_dir = root / "keys"
    keys_dir.mkdir(parents=True)
    (keys_dir / "main.pub.pem").write_bytes(pub_pem)

    release = root / REGISTRY_ID / "madeinoz67" / "dps150" / "0.1.0"
    release.mkdir(parents=True)
    manifest_bytes = (RELEASE / "manifest.json").read_bytes()
    (release / "manifest.json").write_bytes(manifest_bytes)
    (release / "payload.zip").write_bytes((RELEASE / "payload.zip").read_bytes())
    (release / "manifest.sig").write_bytes(key.sign(manifest_bytes))

    status = {
        "status_version": "0.1.1",
        "release": {
            "registry_id": REGISTRY_ID,
            "package_id": "madeinoz67/dps150",
            "version": "0.1.0",
            "manifest_sha256": __import__("hashlib").sha256(manifest_bytes).hexdigest(),
        },
        "sequence": 1,
        "updated_at": "2026-10-02T00:00:00Z",
        "expires_at": "2030-01-01T00:00:00Z",
        "lifecycle": lifecycle,
        "reason": f"fixture status document (lifecycle {lifecycle})",
        "support_state": "maintained",
        "support_contact": "https://github.com/madeinoz67",
        "reviews": [],
        "advisories": [],
    }
    status_bytes = _canonical(status)
    (release / "status.json").write_bytes(status_bytes)
    (release / "status.sig").write_bytes(key.sign(status_bytes))
    return root, keys_dir / "main.pub.pem"


def _replay_fixture(origin: Path, pem: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(REPLAY),
            "--gateway",
            str(GATEWAY_CHECKOUT),
            "--fixture",
            str(origin),
            "--origin-root",
            str(pem),
        ],
        capture_output=True,
        text=True,
        check=False,
    )


@requires_gateway
def test_yanked_fixture_is_refused_by_gateway_admission(tmp_path: Path) -> None:
    origin, pem = _build_fixture_origin(tmp_path / "origin", "yanked")
    result = _replay_fixture(origin, pem)
    assert result.returncode != 0, (
        f"a yanked release admitted through unmodified gateway admission:\n"
        f"{result.stdout + result.stderr}"
    )
    assert "yanked" in result.stdout + result.stderr


@requires_gateway
def test_published_control_admits(tmp_path: Path) -> None:
    """The discriminator's other half: IDENTICAL bytes, lifecycle published
    — admits. Only the lifecycle field differs between this arm and the
    yanked arm; nothing else can be carrying the refusal."""
    origin, pem = _build_fixture_origin(tmp_path / "origin", "published")
    result = _replay_fixture(origin, pem)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "admitted" in result.stdout


@requires_gateway
def test_tampered_fixture_signature_is_refused(tmp_path: Path) -> None:
    """The fixture mode's authenticity pillar is live: a status document
    re-signed by a DIFFERENT key than the root the tool is told to trust
    refuses (bad_signature), never admits."""
    origin, pem = _build_fixture_origin(tmp_path / "origin", "published")
    rogue = Ed25519PrivateKey.generate()
    status_path = origin / REGISTRY_ID / "madeinoz67" / "dps150" / "0.1.0" / "status.sig"
    status_path.write_bytes(rogue.sign(status_path.parent.joinpath("status.json").read_bytes()))
    result = _replay_fixture(origin, pem)
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "bad_signature" in combined, combined


def test_missing_fixture_directory_is_a_typed_refusal(tmp_path: Path) -> None:
    """No gateway checkout needed: the CLI validates its fixture argument."""
    result = subprocess.run(
        [sys.executable, str(REPLAY), "--gateway", str(tmp_path),
         "--fixture", str(tmp_path / "absent")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "Traceback" not in combined, combined
    assert "fixture" in combined.lower()


def test_payload_helper_is_a_real_archive() -> None:
    """Fixture sanity (no gateway needed): the committed payload the fixture
    copies is a well-formed zip — the arms' inputs are honest."""
    with zipfile.ZipFile(RELEASE / "payload.zip") as archive:
        assert archive.namelist()
