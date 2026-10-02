"""Admission replay through unmodified gateway admission (ON-DEMAND tool).

Owner ruling (issue #223 rework): the registry states and advertises; the
client enforces. This script is NOT a publish-time gate — it is the
verification tool a client or reviewer runs to confirm a release admits
through unmodified gateway admission at the recorded ``gateway-ref`` pin.

Two postures (issue #225 slice 3, selected by the R1 pre-build verification
of 2026-10-02):

1. ``--fixture <root>`` — the four-pillar replay: every release under the
   fixture origin resolves AND admits through the gateway's own
   ``Resolver`` + ``admit`` with all four pillars live (origin signature,
   sequence high-water, lifecycle, digests). The trust root is
   ``--origin-root`` (default ``<fixture>/keys/main.pub.pem``); the fixture
   is runtime-keyed by the caller (an in-test Ed25519 keypair), so no arm
   ever depends on uncommitted key material. This is the CR-13 falsifier's
   proof harness — a yanked fixture must refuse ``AdmissionRejected("yanked")``
   and an identical-bytes published control must admit.

2. the real tree (the default, no ``--fixture``) — the lane-posture replay.
   R1 proved the committed ``manifest.sig`` is the PUBLISHER's signature
   over ``submission-manifest.json`` (the owner-ruled posture: the registry
   VALIDATES + PUBLISHES + LABELS, never signs), and one Ed25519 signature
   cannot also verify as an origin-root signature over ``manifest.json`` —
   a full ``required``-policy resolve of this origin is impossible BY
   DESIGN, not by defect. This posture therefore verifies, through the
   gateway's own public machinery, every pillar the lane actually serves:
   the status document (authenticity against the committed origin root,
   the release binding, the expiry/sequence gates, the lifecycle reading)
   plus the publisher signature over the submission manifest — and states
   the posture loudly instead of failing on a signature topology the lane
   rules out. The four-pillar resolve stays provable in ``--fixture`` mode.

    uv run --project <gateway-checkout> python scripts/replay_admission.py \
        --gateway <gateway-checkout> [--fixture <origin-root>] [--origin-root <pem>]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

REPO = Path(__file__).resolve().parents[1]
REGISTRY_ID = "benchweave-registry"

#: Mirrors the gateway resolver's own status budget at the pin.
_STATUS_MAX_BYTES = 100_000


def _packages(releases_root: Path) -> list[tuple[str, str]]:
    """Every published (package_id, version) served under the registry origin."""
    origin = releases_root / REGISTRY_ID
    if not origin.is_dir():
        return []
    packages: list[tuple[str, str]] = []
    for manifest_path in sorted(origin.rglob("manifest.json")):
        parts = manifest_path.relative_to(origin).parts
        if len(parts) != 4 or parts[-1] != "manifest.json":
            continue
        packages.append((f"{parts[0]}/{parts[1]}", parts[2]))
    return packages


def _namespaces(releases_root: Path) -> tuple[str, ...]:
    """The publisher namespaces served under the origin (directory-derived)."""
    namespaces: list[str] = []
    origin = releases_root / REGISTRY_ID
    if not origin.is_dir():
        return tuple(namespaces)
    for publisher_dir in sorted(path for path in origin.iterdir() if path.is_dir()):
        namespaces.append(publisher_dir.name)
    return tuple(namespaces)


def _load_gateway(gateway_src: Path) -> SimpleNamespace:
    """Import the pinned gateway's registry machinery into this process.

    The imports resolve against the gateway checkout injected into
    ``sys.path`` below, never against this repository.
    """
    sys.path.insert(0, str(gateway_src))
    from benchweave.registry.admission import (  # type: ignore[import-not-found]
        AdmissionLimits,
        Approval,
        admit,
    )
    from benchweave.registry.authenticity import (  # type: ignore[import-not-found]
        check_status,
        load_trust_root,
        verify_document,
    )
    from benchweave.registry.resolver import (  # type: ignore[import-not-found]
        LocalDirectorySource,
        OriginConfig,
        Resolver,
    )
    from benchweave.registry.schemas import (  # type: ignore[import-not-found]
        load_status_document,
    )

    return SimpleNamespace(
        AdmissionLimits=AdmissionLimits,
        Approval=Approval,
        admit=admit,
        check_status=check_status,
        load_trust_root=load_trust_root,
        verify_document=verify_document,
        LocalDirectorySource=LocalDirectorySource,
        OriginConfig=OriginConfig,
        Resolver=Resolver,
        load_status_document=load_status_document,
    )


def _resolve_and_admit(
    gw: SimpleNamespace, origins: dict[str, Any], packages: list[tuple[str, str]]
) -> int:
    """The shared four-pillar loop: resolve + admit every package, or refuse
    typing the gateway's own rejection reason."""
    now_ns = int(time.time() * 1_000_000_000)
    admitted_total = 0
    with tempfile.TemporaryDirectory() as work_dir:
        work = Path(work_dir)
        high_water: dict[Any, int] = {}
        for package_id, version in packages:
            label = f"{package_id}@{version}"
            try:
                closure = gw.Resolver(origins).resolve(
                    REGISTRY_ID, package_id, version, now_ns=now_ns, high_water=high_water
                )
                admitted = gw.admit(
                    closure,
                    cache_root=work / "cache",
                    lock_path=work / "packages.lock.json",
                    limits=gw.AdmissionLimits(
                        max_archive_bytes=10_000_000,
                        max_files=1000,
                        max_unpacked_bytes=10_000_000,
                    ),
                    approval=gw.Approval(
                        principal_id="benchweave-registry-replay",
                        approved_at="2026-10-01T00:00:00Z",
                        policy_id="registry-replay",
                        policy_version="1.0.0",
                    ),
                    now_ns=now_ns,
                    roots={name: config.root for name, config in origins.items()},
                )
            except (ValueError, FileNotFoundError) as exc:
                reason = getattr(exc, "reason", None) or exc
                print(
                    f"replay_admission: refused: {label}: "
                    f"{type(exc).__name__}: {reason}",
                    file=sys.stderr,
                )
                return 1
            admitted_total += len(admitted.manifest_sha256s)
            print(
                f"replay_admission: admitted {label} "
                f"({len(admitted.manifest_sha256s)} manifests, "
                f"lock {admitted.lock_sha256[:12]}…)"
            )
    print(
        f"replay_admission: {len(packages)} release(s), {admitted_total} admitted "
        "manifest(s) through unmodified gateway admission"
    )
    return 0


def _replay_fixture(args: argparse.Namespace, gw: SimpleNamespace) -> int:
    fixture = args.fixture.resolve()
    if not fixture.is_dir():
        print(f"replay_admission: fixture root not found: {fixture}", file=sys.stderr)
        return 2
    pem = args.origin_root or fixture / "keys" / "main.pub.pem"
    if not pem.is_file():
        print(
            f"replay_admission: origin root not found: {pem} "
            "(pass --origin-root with the fixture root's public PEM)",
            file=sys.stderr,
        )
        return 2
    packages = _packages(fixture)
    if not packages:
        print("replay_admission: no releases under the fixture origin", file=sys.stderr)
        return 1
    origins = {
        REGISTRY_ID: gw.OriginConfig(
            registry_id=REGISTRY_ID,
            root=gw.load_trust_root(REGISTRY_ID, pem),
            source=gw.LocalDirectorySource(fixture / REGISTRY_ID),
            namespaces=_namespaces(fixture),
        )
    }
    return _resolve_and_admit(gw, origins, packages)


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


def _replay_real_tree(args: argparse.Namespace, gw: SimpleNamespace) -> int:
    """The lane-posture replay over the real tree (R1's outcome, §1.4)."""
    root = args.root.resolve()
    releases_root = root / "releases"
    packages = _packages(releases_root)
    if not packages:
        print("replay_admission: no published releases to replay", file=sys.stderr)
        return 1
    pem = args.origin_root or root / "keys" / "main.pub.pem"
    if not pem.is_file():
        print(
            "replay_admission: origin_root_absent: the origin public root is not "
            f"committed at {pem} (issue #225 F2) and no --origin-root was given — "
            "the status pillar cannot be authenticated",
            file=sys.stderr,
        )
        return 1
    trust = gw.load_trust_root(REGISTRY_ID, pem)
    source = gw.LocalDirectorySource(releases_root / REGISTRY_ID)
    publisher_keys = _publisher_keys(root)
    now_ns = int(time.time() * 1_000_000_000)
    failures = 0
    for package_id, version in packages:
        label = f"{package_id}@{version}"
        try:
            manifest_raw, manifest_digest = source.manifest_bytes(package_id, version)
        except FileNotFoundError:
            print(f"replay_admission: manifest_absent: {label}", file=sys.stderr)
            failures += 1
            continue
        # The status pillar — the gateway's own machinery, end to end:
        # served bytes, schema, origin-root signature, release binding,
        # expiry/sequence gates, lifecycle reading.
        try:
            status_raw, status_digest = source.status_bytes(package_id, version)
        except FileNotFoundError:
            print(
                f"replay_admission: status_document_absent: {label} — the served "
                "layout claims a status pair (issue #225 §1.2)",
                file=sys.stderr,
            )
            failures += 1
            continue
        try:
            status_doc = gw.load_status_document(
                status_raw, status_digest, max_bytes=_STATUS_MAX_BYTES
            )
        except Exception as exc:  # RegistryRejected/jsonschema, reported typed
            print(f"replay_admission: status_invalid: {label}: {exc}", file=sys.stderr)
            failures += 1
            continue
        try:
            status_sig = source.status_signature(package_id, version)
        except FileNotFoundError:
            print(
                f"replay_admission: status_signature_absent: {label} — the status "
                "pair is incomplete (a held maintainer signature reads here; "
                "issue #225 F3)",
                file=sys.stderr,
            )
            failures += 1
            continue
        try:
            gw.verify_document(status_doc, status_sig, trust)
        except ValueError as exc:
            print(
                f"replay_admission: status_signature_invalid: {label}: "
                f"{getattr(exc, 'reason', exc)}",
                file=sys.stderr,
            )
            failures += 1
            continue
        claimed = status_doc.content["release"]
        if (
            claimed["registry_id"],
            claimed["package_id"],
            claimed["version"],
        ) != (REGISTRY_ID, package_id, version) or claimed["manifest_sha256"] != (
            manifest_digest
        ):
            print(
                f"replay_admission: status_release_mismatch: {label}: {claimed!r}",
                file=sys.stderr,
            )
            failures += 1
            continue
        try:
            sequence = gw.check_status(
                status_doc.content, root=trust, now_ns=now_ns, high_water={}
            )
        except ValueError as exc:
            print(
                f"replay_admission: status_gate_refused: {label}: "
                f"{getattr(exc, 'reason', exc)}",
                file=sys.stderr,
            )
            failures += 1
            continue
        lifecycle = status_doc.content["lifecycle"]
        if lifecycle in ("yanked", "revoked"):
            print(f"replay_admission: refused: {label}: {lifecycle}", file=sys.stderr)
            failures += 1
            continue
        # The manifest pillar under the lane's ruled posture (R1): the
        # publisher's signature over the submission manifest — the reading
        # the committed bytes satisfy and the owner ruling names.
        release_dir = releases_root / REGISTRY_ID / package_id / version
        sig_path = release_dir / "manifest.sig"
        signed_path = release_dir / "submission-manifest.json"
        key = publisher_keys.get(package_id.split("/")[0])
        if key is None or not sig_path.is_file() or not signed_path.is_file():
            print(
                f"replay_admission: publisher_signature_unverifiable: {label}",
                file=sys.stderr,
            )
            failures += 1
            continue
        try:
            key.verify(sig_path.read_bytes(), signed_path.read_bytes())
        except Exception:
            print(
                f"replay_admission: publisher_signature_invalid: {label}",
                file=sys.stderr,
            )
            failures += 1
            continue
        print(
            f"replay_admission: lane-posture verified {label} "
            f"(status sequence {sequence}, lifecycle {lifecycle}, "
            "publisher signature valid)"
        )
    print(
        "replay_admission: posture disclosure — the lane serves publisher-signed "
        "manifests by owner ruling (the registry validates + publishes + labels, "
        "never signs); a full required-policy resolve of this origin is "
        "impossible by design (R1, issue #225). The four-pillar resolve is "
        "proven in --fixture mode."
    )
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help="Replay a fixture origin root (releases-shaped) with all four "
        "pillars live; runtime-keyed by the caller.",
    )
    parser.add_argument(
        "--origin-root",
        type=Path,
        default=None,
        help="The origin public root PEM (default: <fixture>/keys/main.pub.pem "
        "in fixture mode, else <root>/keys/main.pub.pem).",
    )
    args = parser.parse_args()
    gateway_src = (args.gateway / "src").resolve()
    if not (gateway_src / "benchweave" / "registry").is_dir():
        print(f"replay_admission: gateway sources not found under {gateway_src}", file=sys.stderr)
        return 2
    gw = _load_gateway(gateway_src)
    if args.fixture is not None:
        return _replay_fixture(args, gw)
    return _replay_real_tree(args, gw)


if __name__ == "__main__":
    raise SystemExit(main())

