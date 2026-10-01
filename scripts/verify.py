"""Verify a clone of this repository end to end (A3: recovery in two commands).

    git clone https://github.com/madeinoz67/benchweave-registry.git
    uv run python scripts/verify.py

Checks, from the clone alone (no gateway repository, no PR thread, no service):

1. every record under ``records/`` is canonical, schema-valid and semantically
   consistent (the records-validity gate, ``validate_records``);
2. every published release's manifest and status signatures verify against the
   committed public trust root ``keys/main.pub.pem`` (Ed25519);
3. every payload archive's digest matches its manifest's ``payload`` block and
   every member's digest matches the inventory (digests authoritative);
4. the accountability chain for each release is printable on demand (CR-54):
   publisher, reviewer, outcome, closure digest, capability declaration.

Exit 0 with the chain printed; any failure exits 1 with a prefixed finding.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

import validate_records as vr
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

REPO = Path(__file__).resolve().parents[1]


def _load_public_root(path: Path) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(path.read_bytes())
    assert isinstance(key, Ed25519PublicKey)  # noqa: S101 — narrowing only
    return key


def verify_releases(root: Path) -> tuple[list[str], list[dict[str, Any]]]:
    findings: list[str] = []
    chains: list[dict[str, Any]] = []
    releases_dir = root / "releases"
    if not releases_dir.is_dir():
        return findings, chains
    root_key = _load_public_root(root / "keys" / "main.pub.pem")
    reviews = _load_reviews(root)
    for manifest_path in sorted(releases_dir.rglob("manifest.json")):
        parts = manifest_path.relative_to(releases_dir).parts
        if len(parts) != 5:
            findings.append(f"release_layout_unexpected:{manifest_path}")
            continue
        _registry_id, publisher, plugin, version, _name = parts
        release_dir = manifest_path.parent
        manifest_raw = manifest_path.read_bytes()
        manifest = json.loads(manifest_raw)
        label = f"{publisher}/{plugin}/{version}"

        # Pillar 1 — the origin signature over the exact manifest bytes.
        try:
            root_key.verify((release_dir / "manifest.sig").read_bytes(), manifest_raw)
        except InvalidSignature:
            findings.append(f"manifest_signature_invalid:{label}")

        # Pillar 2 — the status document is signed and pins the manifest.
        status_raw = (release_dir / "status.json").read_bytes()
        status = json.loads(status_raw)
        try:
            root_key.verify((release_dir / "status.sig").read_bytes(), status_raw)
        except InvalidSignature:
            findings.append(f"status_signature_invalid:{label}")
        if status.get("release", {}).get("manifest_sha256") != vr.sha256_hex(manifest_raw):
            findings.append(f"status_manifest_pin_mismatch:{label}")

        # Pillar 3 — payload digests: archive then per-member inventory.
        payload_raw = (release_dir / "payload.zip").read_bytes()
        payload = manifest.get("payload", {})
        if payload.get("sha256") != vr.sha256_hex(payload_raw):
            findings.append(f"payload_digest_mismatch:{label}")
        with zipfile.ZipFile(io.BytesIO(payload_raw)) as archive:
            members = {name: archive.read(name) for name in archive.namelist()}
        inventoried = {entry["path"]: entry for entry in payload.get("files", [])}
        if set(members) != set(inventoried):
            findings.append(f"payload_inventory_mismatch:{label}")
        for name, data in sorted(members.items()):
            entry = inventoried.get(name, {})
            if entry.get("sha256") != hashlib.sha256(data).hexdigest():
                findings.append(f"payload_member_digest_mismatch:{label}:{name}")

        # Pillar 4 — the review chain: the signed manifest's review block pins
        # the committed review record, which pins the submission digest.
        review_record = reviews.get((publisher, plugin, version))
        block = manifest.get("review", {})
        if review_record is None:
            findings.append(f"review_record_missing:{label}")
            continue
        record_raw, record = review_record
        if block.get("record_sha256") != vr.sha256_hex(record_raw):
            findings.append(f"review_record_digest_mismatch:{label}")
        chains.append(
            {
                "release": label,
                "manifest_sha256": vr.sha256_hex(manifest_raw),
                "publisher": publisher,
                "reviewer": record.get("review", {}).get("reviewer_id"),
                "outcome": block.get("outcome"),
                "closure_digest": record.get("review", {}).get("closure_digest"),
                "capability_declaration": record.get("review", {}).get(
                    "capability_declaration"
                ),
            }
        )
    return findings, chains


def _load_reviews(root: Path) -> dict[tuple[str, str, str], tuple[bytes, dict[str, Any]]]:
    reviews: dict[tuple[str, str, str], tuple[bytes, dict[str, Any]]] = {}
    for path in vr.record_paths(root / "records"):
        parsed = json.loads(path.read_bytes())
        if parsed.get("record_type") != "review":
            continue
        review = parsed.get("review", {})
        key = (review.get("publisher"), review.get("plugin"), review.get("version"))
        reviews[key] = (path.read_bytes(), parsed)
    return reviews


def main(argv: list[str] | str | None = None) -> int:
    root = REPO
    if isinstance(argv, str):
        root = Path(argv).resolve()
    elif argv:
        root = Path(argv[0]).resolve()
    findings = vr.validate_tree(root)
    release_findings, chains = verify_releases(root)
    findings.extend(release_findings)
    for finding in findings:
        print(f"verify: {finding}", file=sys.stderr)
    if findings:
        return 1
    # No gateway checkout, no service, no PR thread: the clone alone verified.
    print(f"verify: records valid, {len(chains)} release(s) signature- and digest-verified")
    for chain in chains:
        print(
            f"verify: {chain['release']} published_by={chain['publisher']} "
            f"reviewed_by={chain['reviewer']} outcome={chain['outcome']} "
            f"closure={chain['closure_digest'][:12]}… "
            f"capabilities={json.dumps(chain['capability_declaration'], sort_keys=True)}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
