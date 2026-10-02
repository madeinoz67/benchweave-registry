"""Verify a clone of this repository end to end (A3: recovery in two commands).

    git clone https://github.com/madeinoz67/benchweave-registry.git
    uv run python scripts/verify.py

The registry VALIDATES + PUBLISHES + LABELS, never signs (owner ruling
2026-10-02). Checks, from the clone alone (no gateway repository, no PR
thread, no service):

1. every record under ``records/`` is canonical, schema-valid and semantically
   consistent (the records-validity gate, ``validate_records``);
2. every published release's payload archive digest matches its manifest's
   ``payload`` block and every member's digest matches the inventory;
3. every release's SIGNATURE STATE matches its label: a ``signed-valid``
   release carries a publisher signature that verifies against the
   publisher's recorded public key (an invalid signature is a finding — the
   recording path rejects those, so finding one here means tampering after
   the fact); an ``unsigned`` release carries no signature file;
4. the accountability chain for each release is printable on demand (CR-54).

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


def _publisher_keys(root: Path) -> dict[str, Ed25519PublicKey]:
    keys: dict[str, Ed25519PublicKey] = {}
    path = root / "records" / "publishers.json"
    if not path.is_file():
        return keys
    for entry in json.loads(path.read_bytes())["publishers"]:
        pem = entry.get("ed25519_public_key_pem")
        if pem:
            loaded = serialization.load_pem_public_key(pem.encode())
            if isinstance(loaded, Ed25519PublicKey):
                keys[entry["publisher_id"]] = loaded
    return keys


def _lifecycle_events(root: Path) -> dict[tuple[str, str, str], list[dict[str, str]]]:
    """C6 (issue #225 slice 3): each release's lifecycle event timeline,
    from the already-validated records — ops, actors, timestamps."""
    events: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for path in vr.record_paths(root / "records"):
        parsed = json.loads(path.read_bytes())
        if parsed.get("record_type") != "lifecycle":
            continue
        lifecycle = parsed.get("lifecycle", {})
        key = (lifecycle.get("publisher"), lifecycle.get("plugin"), lifecycle.get("version"))
        events.setdefault(key, []).append(
            {
                "op": str(lifecycle.get("op")),
                "actor": str(parsed.get("actor")),
                "at": str(parsed.get("created_at")),
            }
        )
    return events


def verify_releases(root: Path) -> tuple[list[str], list[dict[str, Any]]]:
    findings: list[str] = []
    chains: list[dict[str, Any]] = []
    releases_dir = root / "releases"
    if not releases_dir.is_dir():
        return findings, chains
    keys = _publisher_keys(root)
    reviews = _load_reviews(root)
    publishes = _publish_records(root)
    lifecycle_events = _lifecycle_events(root)
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
        publish = publishes.get((publisher, plugin, version), {})
        state = publish.get("signature_state")

        # Payload digests: archive then per-member inventory.
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

        # The signature state matches the label. The publisher signed the
        # SUBMISSION manifest (pre-review); those bytes ride the tree as
        # submission-manifest.json, and the review record pins their digest.
        sig_path = release_dir / "manifest.sig"
        signed_raw_path = release_dir / "submission-manifest.json"
        if state == "signed-valid":
            key = keys.get(manifest.get("publisher_id", publisher))
            if key is None:
                findings.append(f"signature_publisher_key_absent:{label}")
            elif not sig_path.is_file() or not signed_raw_path.is_file():
                findings.append(f"signature_absent:{label}")
            else:
                try:
                    key.verify(sig_path.read_bytes(), signed_raw_path.read_bytes())
                except InvalidSignature:
                    findings.append(f"signature_invalid:{label}")
        elif state == "unsigned":
            if sig_path.is_file():
                findings.append(f"signature_unexpected:{label}")
        else:
            findings.append(f"signature_state_unrecorded:{label}")

        # The review chain: the recorded manifest's review block pins the
        # committed review record, which pins the submission digest.
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
                "signature_state": state,
                "closure_digest": record.get("review", {}).get("closure_digest"),
                "capability_declaration": record.get("review", {}).get(
                    "capability_declaration"
                ),
                "lifecycle_events": lifecycle_events.get((publisher, plugin, version), []),
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


def _publish_records(root: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    publishes: dict[tuple[str, str, str], dict[str, Any]] = {}
    for path in vr.record_paths(root / "records"):
        parsed = json.loads(path.read_bytes())
        if parsed.get("record_type") != "lifecycle":
            continue
        lifecycle = parsed.get("lifecycle", {})
        if lifecycle.get("op") != "publish":
            continue
        key = (lifecycle.get("publisher"), lifecycle.get("plugin"), lifecycle.get("version"))
        publishes[key] = lifecycle
    return publishes


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
    print(
        f"verify: records valid, {len(chains)} release(s) digest-verified, "
        "signature states checked against the recorded publisher keys"
    )
    for chain in chains:
        print(
            f"verify: {chain['release']} published_by={chain['publisher']} "
            f"reviewed_by={chain['reviewer']} outcome={chain['outcome']} "
            f"signature={chain['signature_state']} "
            f"closure={chain['closure_digest'][:12]}… "
            f"capabilities={json.dumps(chain['capability_declaration'], sort_keys=True)} "
            f"lifecycle={','.join(event['op'] for event in chain['lifecycle_events']) or '-'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
