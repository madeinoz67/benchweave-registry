"""Generate the catalogue index from records/ + releases/ (CR-21, Q7/CR-26).

The ONE generated JSON index serving catalogue, search and verification. Runs
offline over the committed trees; the output is canonical JSON and
byte-reproducible for identical inputs. ``--check`` regenerates in memory and
refuses a committed index that differs — a records change without regeneration
fails CI (the CR-21 falsifier), and a hand-edited index row is caught the same
way. The format lives in ``records/index.schema.json``; the website slice
RENDERS this index and never reshapes it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema
from validate_records import canonical_bytes, record_paths, sha256_hex

REPO = Path(__file__).resolve().parents[1]

#: Every row carries these markers unless a future slice's mechanism retires
#: one; they exist so no catalogue surface ever renders self-attested content
#: as verified (CR-37/NFR-S1).
_UNVERIFIED_MARKERS = [
    "conformance-evidence-self-attested",
    "review-is-process-not-proof",
]

_SCHEMA_CACHE: jsonschema.Draft202012Validator | None = None


def _index_schema() -> jsonschema.Draft202012Validator:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        schema = json.loads((REPO / "records" / "index.schema.json").read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        _SCHEMA_CACHE = jsonschema.Draft202012Validator(schema)
    return _SCHEMA_CACHE


def _publish_records(root: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    publishes: dict[tuple[str, str, str], dict[str, Any]] = {}
    for path in record_paths(root / "records"):
        parsed = json.loads(path.read_bytes())
        if parsed.get("record_type") != "lifecycle":
            continue
        lifecycle = parsed.get("lifecycle", {})
        if lifecycle.get("op") != "publish":
            continue
        key = (lifecycle.get("publisher"), lifecycle.get("plugin"), lifecycle.get("version"))
        publishes[key] = lifecycle
    return publishes


def _reviews(root: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    reviews: dict[tuple[str, str, str], dict[str, Any]] = {}
    for path in record_paths(root / "records"):
        parsed = json.loads(path.read_bytes())
        if parsed.get("record_type") != "review":
            continue
        review = parsed.get("review", {})
        reviews[(review.get("publisher"), review.get("plugin"), review.get("version"))] = parsed
    return reviews


def _maintenance(status: dict[str, Any]) -> str:
    state = status.get("support_state")
    if state in ("maintained", "maintenance_only", "unmaintained"):
        return str(state)
    return "unknown"


def generate(root: Path) -> bytes:
    """The canonical index bytes for the committed trees; pure and offline."""
    reviews = _reviews(root)
    publishes = _publish_records(root)
    rows: list[dict[str, Any]] = []
    releases = root / "releases"
    if releases.is_dir():
        for manifest_path in sorted(releases.rglob("manifest.json")):
            parts = manifest_path.relative_to(releases).parts
            if len(parts) != 5 or parts[-1] != "manifest.json":
                continue
            _registry_id, publisher, plugin, version, _name = parts
            manifest = json.loads(manifest_path.read_bytes())
            release_dir = manifest_path.parent
            signed = (release_dir / "manifest.sig").is_file() and (
                release_dir / "status.sig"
            ).is_file()
            status: dict[str, Any] = {}
            if (release_dir / "status.json").is_file():
                status = json.loads((release_dir / "status.json").read_bytes())
            review_record = reviews.get((publisher, plugin, version), {})
            review = review_record.get("review", {})
            publish = publishes.get((publisher, plugin, version), {})
            submission_path = (
                root / "records" / "submissions" / publisher / plugin / version
                / "artefacts" / "submission.json"
            )
            submission = (
                json.loads(submission_path.read_bytes()) if submission_path.is_file() else {}
            )
            rows.append(
                {
                    "registry_id": manifest.get("registry_id", parts[0]),
                    "package_id": manifest["package_id"],
                    "version": manifest["version"],
                    "kind": review_record.get("kind", "admitted-release"),
                    "publisher": manifest.get("publisher_id", publisher),
                    "manifest_sha256": sha256_hex(manifest_path.read_bytes()),
                    "signed": signed,
                    "display_name": manifest.get("display_name", plugin),
                    "summary": manifest.get("summary", ""),
                    "licence_spdx": manifest.get("licence", {}).get("spdx_expression", "unknown"),
                    "compatibility": {
                        key: manifest.get("compatibility", {}).get(key, [])
                        for key in ("otdp_versions", "adapter_api_versions", "stg_versions")
                    },
                    "evidence": [
                        {
                            "level": entry.get("level"),
                            "report_path": entry.get("report_path"),
                            "result": entry.get("result"),
                        }
                        for entry in manifest.get("evidence", [])
                    ],
                    "maintenance": _maintenance(status),
                    "advisories": sorted(
                        advisory.get("id", "")
                        for advisory in status.get("advisories", [])
                        if advisory.get("id")
                    ),
                    "capabilities": review.get(
                        "capability_declaration",
                        submission.get(
                            "capability_declaration",
                            {
                                "network_egress": False,
                                "subprocess_or_native_library": False,
                                "filesystem_writes_beyond_evidence_retention": False,
                            },
                        ),
                    ),
                    "transport_triples": submission.get("transport_triples", []),
                    "source_revision": manifest.get("source", {}).get("revision", "0" * 40),
                    "gateway_ref": publish.get("gateway_ref"),
                    "firmware_attestation": publish.get("firmware_attestation"),
                    "unverified_markers": list(_UNVERIFIED_MARKERS),
                }
            )
    index = {
        "index_version": 1,
        "generated_from": {"records_tree": "records/", "releases_tree": "releases/"},
        "rows": sorted(rows, key=lambda row: (row["package_id"], row["version"])),
    }
    errors = sorted(_index_schema().iter_errors(index), key=str)
    if errors:
        for error in errors:
            print(f"generate_index: index_schema_invalid: {error.json_path}: {error.message}",
                  file=sys.stderr)
        raise SystemExit(1)
    return canonical_bytes(index)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument("--check", action="store_true", help="Refuse drift; write nothing")
    args = parser.parse_args()
    root = args.root.resolve()
    fresh = generate(root)
    if args.check:
        committed = root / "index.json"
        if not committed.is_file():
            print("generate_index: index_absent (records changed without regeneration, CR-21)",
                  file=sys.stderr)
            return 1
        if committed.read_bytes() != fresh:
            print(
                "generate_index: index_drift: the committed index differs from a fresh "
                "generation (records changed without regeneration, or a hand edit — CR-21)",
                file=sys.stderr,
            )
            return 1
        print(f"generate_index: index current ({len(json.loads(fresh)['rows'])} rows)")
        return 0
    (root / "index.json").write_bytes(fresh)
    print(f"generate_index: wrote index.json ({len(json.loads(fresh)['rows'])} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
