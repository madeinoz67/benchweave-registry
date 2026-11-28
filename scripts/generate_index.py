"""Generate the catalogue index from records/ + releases/ (CR-21, Q7/CR-26).

The ONE generated JSON index serving catalogue, search and verification. Runs
offline over the committed trees; the output is canonical JSON and
byte-reproducible for identical inputs. ``--check`` regenerates in memory and
refuses a committed index that differs — a records change without regeneration
fails CI (the CR-21 falsifier), and a hand-edited index row is caught the same
way. The format lives in ``records/index.schema.json``; the website slice
RENDERS this index and never reshapes it.

Issue #227 slice 5 (CR-56/CR-57, Q20): the index also carries
``community-shared`` rows, generated from share records under
``records/lifecycle/`` — a listing carries no release, so everything on its
row is author-declared and it is built here from the record alone. A shared
takedown record drops the row. And a row's kind is generated from a record,
never defaulted: a release whose records carry no kind tag refuses
(``index_kind_untagged:``) instead of landing in the catalogue as an admitted
release.
"""

from __future__ import annotations

import argparse
import json
import re
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

#: CR-57 (issue #227 slice 5): the one unverified marker a community-shared
#: row carries. The slice-1 markers describe reviewed releases (self-attested
#: conformance evidence, review as process); a listing has neither a review
#: nor evidence, so it carries only its own. The index schema REQUIRES it on
#: every community-shared row — absence is unrepresentable in the format.
SHARED_MARKER = "community-shared-not-reviewed"

#: CR-56: the kind a shared listing wears. A release is never
#: ``community-shared`` — sharing is not an admission path.
SHARED_KIND = "community-shared"

#: The repository of record's own origin id. A release reads its registry id
#: from its path under ``releases/``; a listing has no path segment, so its
#: row and record page sit under this one.
REGISTRY_ID = "benchweave-registry"

#: The release-status schema this repository vendors (digest-pinned against
#: the gateway's standards/registry/0.1.1 origin — see
#: vendored/gateway/release-status.pin.json). The lifecycle enum lives HERE,
#: never in a hand list: this generator and scripts/validate_release_status.py
#: are the two consumers of the one authority (issue #224 slice-2 pivot §3.2).
_RELEASE_STATUS_SCHEMA = REPO / "vendored" / "gateway" / "release-status.schema.json"


def _lifecycle_enum() -> tuple[str, ...]:
    try:
        schema = json.loads(_RELEASE_STATUS_SCHEMA.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(
            f"generate_index: status_schema_unreadable: {_RELEASE_STATUS_SCHEMA}: {exc}"
        ) from exc
    enum = schema["properties"]["lifecycle"]["enum"]
    return tuple(str(value) for value in enum)


#: The settled lifecycle values (published | deprecated | yanked | revoked).
LIFECYCLE_ENUM: tuple[str, ...] = _lifecycle_enum()

_SCHEMA_CACHE: jsonschema.Draft202012Validator | None = None


def _index_schema() -> jsonschema.Draft202012Validator:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        schema = json.loads((REPO / "records" / "index.schema.json").read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        _SCHEMA_CACHE = jsonschema.Draft202012Validator(schema)
    return _SCHEMA_CACHE


def _publish_records(root: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Each release's publish record — the WHOLE record, not its lifecycle
    block: the kind tag rides the record's top level (issue #227 slice 5)."""
    publishes: dict[tuple[str, str, str], dict[str, Any]] = {}
    for path in record_paths(root / "records"):
        parsed = json.loads(path.read_bytes())
        if parsed.get("record_type") != "lifecycle":
            continue
        lifecycle = parsed.get("lifecycle", {})
        if lifecycle.get("op") != "publish":
            continue
        key = (lifecycle.get("publisher"), lifecycle.get("plugin"), lifecycle.get("version"))
        publishes[key] = parsed
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


def _unlisted(root: Path) -> set[tuple[str, str, str]]:
    """Keys carrying a lifecycle UNLIST record (issue #225 slice 3, CR-32/E4).

    Unlist is the one record-driven row drop: the catalogue stops offering
    the release while its status document — and therefore its admissibility —
    is untouched. Yank/revoked remain status-driven only (Q8): the generator
    honours status documents, and a yank RECORD without a governing status
    document is the validity gate's incoherence (``yank_status_absent:``),
    never a silent drop here.
    """
    unlisted: set[tuple[str, str, str]] = set()
    for path in record_paths(root / "records"):
        parsed = json.loads(path.read_bytes())
        if parsed.get("record_type") != "lifecycle":
            continue
        lifecycle = parsed.get("lifecycle", {})
        if lifecycle.get("op") != "unlist":
            continue
        unlisted.add(
            (lifecycle.get("publisher"), lifecycle.get("plugin"), lifecycle.get("version"))
        )
    return unlisted


def _maintenance(publish: dict[str, Any]) -> str:
    state = publish.get("support_state")
    if state in ("maintained", "maintenance_only", "unmaintained"):
        return str(state)
    return "unknown"


def _record_order(path: Path) -> tuple[str, int, str]:
    """Numeric-aware record order: ``10-share`` sorts after ``2-share``."""
    match = re.search(r"(\d+)", path.stem)
    return (str(path.parent), int(match.group(1)) if match else 0, path.name)


def _shares(root: Path) -> dict[tuple[str, str, str], list[tuple[Path, dict[str, Any]]]]:
    """Every share record at each key, in record order (issue #227 slice 5).

    More than one at a key is the validity gate's refusal
    (``shared_listing_duplicate:``); the generator lists them so it can refuse
    to pick, never silently serve the first.
    """
    shares: dict[tuple[str, str, str], list[tuple[Path, dict[str, Any]]]] = {}
    for path in record_paths(root / "records"):
        parsed = json.loads(path.read_bytes())
        if parsed.get("record_type") != "lifecycle":
            continue
        lifecycle = parsed.get("lifecycle", {})
        if lifecycle.get("op") != "share":
            continue
        key = (lifecycle.get("publisher"), lifecycle.get("plugin"), lifecycle.get("version"))
        shares.setdefault(key, []).append((path, lifecycle))
    for records in shares.values():
        records.sort(key=lambda item: _record_order(item[0]))
    return shares


def _taken_down(root: Path) -> set[tuple[str, str, str]]:
    """Keys carrying a lifecycle takedown record (issue #227 slice 5, Q20).

    A shared listing has no status document, so its takedown is the one
    record-driven drop beside unlist. The set is kind-blind on purpose: a
    takedown record parked on a listing's key drops the row whichever kind it
    wears. The wrong-kind record is the validity gate's refusal
    (``shared_listing_conflict:``), and the generator failing closed is the
    row disappearing, never a taken-down listing still being offered. Release
    rows never consult this set — their drop stays status-driven (Q8).
    """
    taken_down: set[tuple[str, str, str]] = set()
    for path in record_paths(root / "records"):
        parsed = json.loads(path.read_bytes())
        if parsed.get("record_type") != "lifecycle":
            continue
        lifecycle = parsed.get("lifecycle", {})
        if lifecycle.get("op") != "takedown":
            continue
        taken_down.add(
            (lifecycle.get("publisher"), lifecycle.get("plugin"), lifecycle.get("version"))
        )
    return taken_down


def _shared_row(key: tuple[str, str, str], path: Path, lifecycle: dict[str, Any]) -> dict[str, Any]:
    """One community-shared row, built from the share record alone.

    Everything author-declared is carried verbatim (display name, summary,
    licence, compatibility, capabilities, the pinned source). Everything the
    registry would otherwise read from a release, a status document or a
    submission is empty: a listing has none, and the index schema refuses a
    shared row that claims any of it. The row's digest is the canonical share
    record's — the only bytes the registry holds for a listing.
    """
    publisher, plugin, version = key
    shared = lifecycle.get("shared", {})
    source = shared.get("source", {})
    compatibility = shared.get("compatibility", {})
    capabilities = shared.get("capabilities", {})
    return {
        "registry_id": REGISTRY_ID,
        "package_id": f"{publisher}/{plugin}",
        "version": version,
        "kind": SHARED_KIND,
        "publisher": publisher,
        "manifest_sha256": sha256_hex(path.read_bytes()),
        "signature_state": "unsigned",
        "timestamp": None,
        "timestamp_recommended": False,
        "display_name": shared.get("display_name", plugin),
        "summary": shared.get("summary", ""),
        "licence_spdx": shared.get("licence_spdx", "unknown"),
        "compatibility": {
            name: list(compatibility.get(name) or [])
            for name in ("otdp_versions", "adapter_api_versions", "stg_versions")
        },
        "evidence": [],
        "maintenance": "unknown",
        "advisories": [],
        "capabilities": {
            name: bool(capabilities.get(name))
            for name in (
                "network_egress",
                "subprocess_or_native_library",
                "filesystem_writes_beyond_evidence_retention",
            )
        },
        "transport_triples": [],
        "source_revision": source.get("revision", "0" * 40),
        "source_url": source.get("url", ""),
        "gateway_ref": None,
        "firmware_attestation": None,
        "unverified_markers": [SHARED_MARKER],
    }


def _release_kind(
    row_id: str, review_record: dict[str, Any], publish: dict[str, Any]
) -> tuple[str | None, str | None]:
    """``(kind, problem)`` — exactly one is set.

    CR-56: the kind is generated from a record. The pre-slice generator
    defaulted a release with no kind-carrying record to ``admitted-release``,
    so a release directory with no records reached the catalogue as an
    admitted release. One release wears one kind, and never the shared kind.
    """
    kinds = sorted(
        {
            str(record["kind"])
            for record in (review_record, publish)
            if record.get("kind") is not None
        }
    )
    if not kinds:
        return None, (
            f"index_kind_untagged:{row_id}: no record carries a kind tag — a "
            "row's kind is generated from a record, never defaulted (CR-56)"
        )
    if len(kinds) > 1:
        return None, f"index_kind_conflict:{row_id}: the release's records carry kinds {kinds}"
    if kinds[0] == SHARED_KIND:
        return None, (
            f"index_kind_shared_release:{row_id}: a release cannot be kind "
            f"{SHARED_KIND} — sharing is not an admission path (CR-57)"
        )
    return kinds[0], None


def generate(root: Path) -> bytes:
    """The canonical index bytes for the committed trees; pure and offline."""
    reviews = _reviews(root)
    publishes = _publish_records(root)
    unlisted = _unlisted(root)
    shares = _shares(root)
    taken_down = _taken_down(root)
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    seen_rows: set[tuple[str, str, str]] = set()
    releases = root / "releases"
    if releases.is_dir():
        for manifest_path in sorted(releases.rglob("manifest.json")):
            parts = manifest_path.relative_to(releases).parts
            if len(parts) != 5 or parts[-1] != "manifest.json":
                continue
            _registry_id, publisher, plugin, version, _name = parts
            manifest_bytes = manifest_path.read_bytes()
            manifest = json.loads(manifest_bytes)
            # Fold M3: identity comes from the PATH and the manifest must
            # agree; duplicate identities refuse.
            row_key = (publisher, plugin, version)
            if row_key in seen_rows:
                problems.append(f"index_duplicate_row:{'/'.join(row_key)}")
                continue
            seen_rows.add(row_key)
            if manifest.get("package_id") != f"{publisher}/{plugin}" or manifest.get(
                "version"
            ) != version:
                problems.append(
                    f"index_identity_mismatch:{publisher}/{plugin}/{version}: claims "
                    f"{manifest.get('package_id')}@{manifest.get('version')}"
                )
                continue
            # Fold H2: the index never serves tampered bytes under a
            # signed-valid label - reconcile against the signed submission.
            _signed_path = manifest_path.parent / "submission-manifest.json"
            if _signed_path.is_file():
                _signed = json.loads(_signed_path.read_bytes())
                _reconciled = {k: v for k, v in manifest.items() if k != "review"}
                _reconciled["manifest_version"] = _signed.get("manifest_version", "0.1.1")
                if _reconciled != _signed:
                    problems.append(
                        f"manifest_reconciliation_failed:{publisher}/{plugin}/{version}"
                    )
                    continue
            release_dir = manifest_path.parent
            # The status document is the single authority for lifecycle and
            # advisories (Q8: origin status/lifecycle files remain the
            # mechanism — the same served state file stock gateways consult).
            # Yank arm, hardened (issue #224 slice-2 pivot §3.2, CR-25):
            #   - lifecycle yanked or revoked DROPS the row — discovery must
            #     not offer what admission already refuses; the record and
            #     git history retain it;
            #   - a PRESENT lifecycle outside the enum REFUSES the run
            #     (fail-closed: the pre-pivot generator silently kept the
            #     row — the exact HIGH all four refute lanes flagged), so
            #     `Yanked`, `yank`, `retired`, null, a list value, or a
            #     missing lifecycle key all refuse, naming the row;
            #   - a status document that is not parseable JSON, not an
            #     object, or NOT A REGULAR FILE refuses with
            #     `index_status_unparseable:` (typed; never a bare
            #     traceback) — a directory-shaped status.json never reads
            #     as absent (fold R4, round-2 refute);
            #   - a PRESENT status document is BOUND to its directory: the
            #     schema-required release block must equal the directory's
            #     identity plus the manifest digest on disk — mismatch
            #     refuses with `index_status_mismatch:` (fold R1);
            #   - an ABSENT status.json keeps the row (the dogfood's shape,
            #     unchanged). Zero format motion: only which rows exist.
            status_path = release_dir / "status.json"
            row_id = f"{publisher}/{plugin}/{version}"
            if status_path.exists() and not status_path.is_file():
                problems.append(
                    f"index_status_unparseable:{row_id}: "
                    "status path is present but not a regular file"
                )
                continue
            status: dict[str, Any] = {}
            if status_path.is_file():
                try:
                    parsed_status: Any = json.loads(status_path.read_bytes())
                except ValueError as exc:
                    problems.append(f"index_status_unparseable:{row_id}: {exc}")
                    continue
                if not isinstance(parsed_status, dict):
                    problems.append(
                        f"index_status_unparseable:{row_id}: "
                        "status document is not a JSON object"
                    )
                    continue
                status = parsed_status
                expected_release: dict[str, str] = {
                    "registry_id": str(parts[0]),
                    "package_id": f"{publisher}/{plugin}",
                    "version": str(version),
                    "manifest_sha256": sha256_hex(manifest_bytes),
                }
                claimed_release: object = status.get("release")
                if claimed_release != expected_release:
                    problems.append(
                        f"index_status_mismatch:{row_id}: "
                        f"names {claimed_release!r}, governs {expected_release}"
                    )
                    continue
                lifecycle: Any = status.get("lifecycle")
                if lifecycle not in LIFECYCLE_ENUM:
                    problems.append(f"index_status_invalid:{lifecycle!r} ({row_id})")
                    continue
                if lifecycle in ("yanked", "revoked"):
                    continue
            # CR-32/E4 (issue #225 slice 3): the record-driven, catalogue-only
            # drop. The status checks above have already run for this row —
            # an unlisted release with an INVALID status document still
            # refuses the run (fail-closed), and an unlisted release with a
            # valid status document stays resolvable and admissible; only
            # the catalogue row is gone.
            if row_key in unlisted:
                continue
            review_record = reviews.get((publisher, plugin, version), {})
            review = review_record.get("review", {})
            publish = publishes.get((publisher, plugin, version), {})
            publish_block: dict[str, Any] = publish.get("lifecycle", {})
            kind, kind_problem = _release_kind(row_id, review_record, publish)
            if kind_problem is not None:
                problems.append(kind_problem)
                continue
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
                    "kind": kind,
                    "publisher": manifest.get("publisher_id", publisher),
                    "manifest_sha256": sha256_hex(manifest_bytes),
                    "signature_state": publish_block.get(
                        "signature_state",
                        "signed-valid" if (release_dir / "manifest.sig").is_file() else "unsigned",
                    ),
                    "timestamp": publish_block.get("timestamp"),
                    "timestamp_recommended": bool(
                        publish_block.get("timestamp_recommended", False)
                    ),
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
                    "maintenance": _maintenance(publish_block),
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
                    "gateway_ref": publish_block.get("gateway_ref"),
                    "firmware_attestation": publish_block.get("firmware_attestation"),
                    "unverified_markers": list(_UNVERIFIED_MARKERS),
                }
            )

    # Issue #227 slice 5 (CR-57, Q20): one row per shared listing, from the
    # share record alone. A listing never shares an identity with a release
    # (the second entry at a key refuses, as it does between two releases),
    # the generator never picks between two share records, and a takedown
    # record drops the row — the record and git history retain it (CR-32).
    for key in sorted(shares):
        publisher, plugin, version = key
        row_id = f"{publisher}/{plugin}/{version}"
        if key in seen_rows:
            problems.append(f"index_duplicate_row:{row_id}")
            continue
        seen_rows.add(key)
        records = shares[key]
        if len(records) > 1:
            problems.append(
                f"index_listing_ambiguous:{row_id}: {len(records)} share records — "
                "one key holds one listing, and the generator never picks"
            )
            continue
        if key in taken_down:
            continue
        path, lifecycle = records[0]
        rows.append(_shared_row(key, path, lifecycle))

    if problems:
        for problem in problems:
            print(f"generate_index: {problem}", file=sys.stderr)
        raise SystemExit(1)
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
