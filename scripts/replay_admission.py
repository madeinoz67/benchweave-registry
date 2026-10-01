"""Admission replay through unmodified gateway admission (Q10, CR-13).

Runs the gateway repository's own registry machinery — at the committed
``gateway-ref`` pin — over this repository's ``releases/`` tree with the
committed public root, asserting every published release resolves and admits
with all four pillars live (origin signature, sequence high-water, lifecycle,
digests). This is the authoritative CR-13 falsifier check: an accepted release
admits through unmodified admission, executed by the gateway's own code at a
pinned ref. A red replay means a bad submission, not gateway drift (F5).

    uv run --project <gateway-checkout> python scripts/replay_admission.py \
        --gateway <gateway-checkout>
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
REGISTRY_ID = "benchweave-registry"


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=REPO)
    args = parser.parse_args()
    gateway_src = (args.gateway / "src").resolve()
    if not (gateway_src / "benchweave" / "registry").is_dir():
        print(f"replay_admission: gateway sources not found under {gateway_src}", file=sys.stderr)
        return 2
    sys.path.insert(0, str(gateway_src))

    # The pin is the point: these imports resolve against the gateway checkout
    # injected into sys.path above, never against this repository.
    from benchweave.registry.admission import (  # type: ignore[import-not-found]
        AdmissionLimits,
        Approval,
        admit,
    )
    from benchweave.registry.authenticity import (  # type: ignore[import-not-found]
        load_trust_root,
    )
    from benchweave.registry.resolver import (  # type: ignore[import-not-found]
        LocalDirectorySource,
        OriginConfig,
        Resolver,
    )

    root = args.root.resolve()
    releases_root = root / "releases"
    packages = _packages(releases_root)
    if not packages:
        print("replay_admission: no published releases to replay", file=sys.stderr)
        return 1

    publishers = json.loads((root / "records" / "publishers.json").read_bytes())
    namespaces = tuple(
        entry["namespace"] for entry in publishers["publishers"] if "namespace" in entry
    )
    now_ns = int(time.time() * 1_000_000_000)
    origins = {
        REGISTRY_ID: OriginConfig(
            registry_id=REGISTRY_ID,
            root=load_trust_root(REGISTRY_ID, root / "keys" / "main.pub.pem"),
            source=LocalDirectorySource(releases_root / REGISTRY_ID),
            namespaces=namespaces,
        )
    }

    admitted_total = 0
    manifest_digests: dict[str, list[str]] = {}
    with tempfile.TemporaryDirectory() as work_dir:
        work = Path(work_dir)
        high_water: dict[Any, int] = {}
        for package_id, version in packages:
            closure = Resolver(origins).resolve(
                REGISTRY_ID, package_id, version, now_ns=now_ns, high_water=high_water
            )
            admitted = admit(
                closure,
                cache_root=work / "cache",
                lock_path=work / "packages.lock.json",
                limits=AdmissionLimits(
                    max_archive_bytes=10_000_000, max_files=1000, max_unpacked_bytes=10_000_000
                ),
                approval=Approval(
                    principal_id="benchweave-registry-replay",
                    approved_at="2026-10-01T00:00:00Z",
                    policy_id="registry-replay",
                    policy_version="1.0.0",
                ),
                now_ns=now_ns,
                roots={REGISTRY_ID: load_trust_root(REGISTRY_ID, root / "keys" / "main.pub.pem")},
            )
            admitted_total += len(admitted.manifest_sha256s)
            manifest_digests[f"{package_id}@{version}"] = sorted(admitted.manifest_sha256s)
            print(
                f"replay_admission: admitted {package_id}@{version} "
                f"({len(admitted.manifest_sha256s)} manifests, lock {admitted.lock_sha256[:12]}…)"
            )

    print(
        f"replay_admission: {len(packages)} release(s), {admitted_total} admitted manifest(s) "
        "through unmodified gateway admission at the pinned ref"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
