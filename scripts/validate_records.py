"""Records-validity gate for the BenchWeave registry lane (CR-9/CR-10/CR-56/CR-60/CR-38/CR-35).

Every record under ``records/`` must be canonical JSON (sorted keys, compact
separators, one trailing newline), schema-valid against
``records/records.schema.json``, and semantically consistent:

- a changes-requested review citing no failure is refused (CR-10);
- a review naming no platform findings at the pinned revision is refused (CR-60);
- a record without a kind tag is refused (CR-56);
- a publish record without a closure diff, or whose sign-off names a different
  closure digest than the one published, is refused (CR-38);
- no dev-prefixed registry id appears anywhere in the records or the published
  releases (CR-35's index half);
- the review block inside a published release's manifest pins the review
  record's own canonical digest, and the record's closure digest matches the
  manifest's dependency closure (the review-to-sign swap defense, CR-11/CR-14).

Structural validity does not establish trust; these checks are the machine
half, and identified human review remains the accountable one.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import jsonschema

REPO = Path(__file__).resolve().parents[1]
RECORDS = REPO / "records"

_SCHEMA_CACHE: dict[str, jsonschema.Draft202012Validator] = {}


def canonical_bytes(obj: object) -> bytes:
    """The lane's canonical serialization: sorted keys, compact, LF, newline."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _validator(name: str) -> jsonschema.Draft202012Validator:
    if name not in _SCHEMA_CACHE:
        schema = json.loads((RECORDS / name).read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        _SCHEMA_CACHE[name] = jsonschema.Draft202012Validator(schema)
    return _SCHEMA_CACHE[name]


def record_paths(records_dir: Path) -> list[Path]:
    """Every committed record file, sorted (submissions and lifecycle)."""
    return sorted(
        path
        for sub in ("submissions", "lifecycle")
        for path in (records_dir / sub).rglob("*.json")
        if path.is_file()
    )


def closure_digest_of_dependencies(dependencies: list[dict[str, Any]]) -> str:
    """CR-38's closure digest: sha256 over the canonical sorted dependency pins.

    One definition, used by the submission tooling, the review record, the
    publish record and this checker, so the sign-off can never cover a
    different closure than the one published.
    """
    pins = sorted(
        (dep["registry_id"], dep["package_id"], dep["version"], dep["manifest_sha256"])
        for dep in dependencies
    )
    return sha256_hex(canonical_bytes(pins))


def validate_record(raw: bytes, path: Path) -> tuple[list[str], dict[str, Any] | None]:
    """Validate one record's bytes; returns (findings, parsed-or-None)."""
    findings: list[str] = []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return [f"record_schema_invalid:{path.name}: not JSON: {exc}"], None
    if not isinstance(parsed, dict):
        return [f"record_schema_invalid:{path.name}: record is not an object"], None
    if canonical_bytes(parsed) != raw:
        findings.append(f"record_not_canonical:{path.name}")
    errors = sorted(_validator("records.schema.json").iter_errors(parsed), key=str)
    for err in errors:
        findings.append(
            f"record_schema_invalid:{path.name}: {err.json_path}: {err.message}"
        )
    return findings, parsed


def _review_records(parsed_by_path: dict[Path, dict[str, Any]]) -> dict[tuple[str, str, str], Path]:
    """Map (publisher, plugin, version) -> the accepted review record's path."""
    reviews: dict[tuple[str, str, str], Path] = {}
    for path, parsed in parsed_by_path.items():
        if parsed.get("record_type") != "review":
            continue
        review = parsed.get("review", {})
        key = (review.get("publisher"), review.get("plugin"), review.get("version"))
        reviews[key] = path
    return reviews


def _release_manifests(releases_dir: Path) -> dict[tuple[str, str, str], Path]:
    """Map (publisher, plugin, version) -> manifest path under releases/."""
    manifests: dict[tuple[str, str, str], Path] = {}
    if not releases_dir.is_dir():
        return manifests
    for path in sorted(releases_dir.rglob("manifest.json")):
        parts = path.relative_to(releases_dir).parts
        # <registry-id>/<publisher>/<plugin>/<version>/manifest.json
        if len(parts) != 5 or parts[-1] != "manifest.json":
            continue
        manifests[(parts[1], parts[2], parts[3])] = path
    return manifests


def validate_tree(root: Path) -> list[str]:
    """All findings for the committed records tree; empty means valid."""
    findings: list[str] = []
    records_dir = root / "records"
    releases_dir = root / "releases"

    publishers_raw = records_dir / "publishers.json"
    if publishers_raw.is_file():
        raw = publishers_raw.read_bytes()
        parsed = json.loads(raw)
        if canonical_bytes(parsed) != raw:
            findings.append("record_not_canonical:publishers.json")
        for err in sorted(
            _validator("publishers.schema.json").iter_errors(parsed), key=str
        ):
            findings.append(
                f"record_schema_invalid:publishers.json: {err.json_path}: {err.message}"
            )

    parsed_by_path: dict[Path, dict[str, Any]] = {}
    for path in record_paths(records_dir):
        record_findings, parsed = validate_record(path.read_bytes(), path)
        findings.extend(record_findings)
        if parsed is not None:
            parsed_by_path[path] = parsed

    reviews = _review_records(parsed_by_path)
    manifests = _release_manifests(releases_dir)

    # CR-35's releases half: no dev-prefixed origin or dependency lineage in
    # the published tree (the docstring's records-AND-releases claim, made
    # true here): a dev-unsigned origin under releases/ refuses.
    import re as _re

    _segment = _re.compile(r"^[a-z0-9][a-z0-9._-]*$")
    for manifest_path in sorted(manifests.values()):
        manifest = json.loads(manifest_path.read_bytes())
        rel = manifest_path.relative_to(releases_dir).as_posix()
        # Fold L2 (read side): a traversal-shaped identity never resolves.
        parts = manifest_path.relative_to(releases_dir).parts
        for part in parts[:-1]:
            if _segment.fullmatch(part) is None:
                findings.append(f"release_path_unsafe:{rel}")
        # Fold M3 (identity agreement): the manifest must claim the path it
        # lives at - a ghost at 0.9.0 claiming 0.1.0 refuses here too.
        path_package = f"{parts[1]}/{parts[2]}"
        if manifest.get("package_id") != path_package or manifest.get("version") != parts[3]:
            findings.append(
                f"release_identity_mismatch:{rel}: claims "
                f"{manifest.get('package_id')}@{manifest.get('version')}"
            )
        if str(manifest.get("registry_id", "")).startswith("dev-"):
            findings.append(f"dev_lineage_in_release:{rel}")
        for dep in manifest.get("dependencies", []):
            if str(dep.get("registry_id", "")).startswith("dev-"):
                findings.append(f"dev_lineage_in_release:{rel}")
        # Fold H2: the consumed manifest is reconciled against the signed
        # bytes and the recorded digest - a post-recording tamper refuses.
        submission_path = manifest_path.parent / "submission-manifest.json"
        if submission_path.is_file():
            signed = json.loads(submission_path.read_bytes())
            reconciled = {k: v for k, v in manifest.items() if k != "review"}
            reconciled["manifest_version"] = signed.get("manifest_version", "0.1.1")
            if reconciled != signed:
                findings.append(f"manifest_reconciliation_failed:{rel}")

    for path, parsed in parsed_by_path.items():
        # CR-35's index half: no dev-prefixed registry id in any record.
        if "dev-" in json.dumps(parsed):
            findings.append(f"dev_lineage_in_records:{path.name}")
        if parsed.get("record_type") != "lifecycle":
            continue
        lifecycle = parsed.get("lifecycle", {})
        if lifecycle.get("op") != "publish":
            continue
        if "closure" not in lifecycle:
            # Belt and braces: the schema's if/then already refuses this
            # (A4's closure_diff_absent mutant names exactly this component).
            findings.append(f"closure_diff_absent:{path.name}")
            continue
        key = (lifecycle.get("publisher"), lifecycle.get("plugin"), lifecycle.get("version"))
        release_path: Path | None = manifests.get(key)
        if release_path is None:
            findings.append(
                f"publish_record_without_release:{path.name}: no manifest under releases/"
            )
            continue
        manifest = json.loads(release_path.read_bytes())
        # Fold H2: the publish record's release_manifest_sha256 must pin the
        # manifest bytes actually on disk.
        recorded_digest = lifecycle.get("release_manifest_sha256")
        if recorded_digest and recorded_digest != sha256_hex(release_path.read_bytes()):
            findings.append(
                f"release_digest_mismatch:{path.name}: record pins "
                f"{recorded_digest[:12]}…, on disk is "
                f"{sha256_hex(release_path.read_bytes())[:12]}…"
            )
        # CR-38: the sign-off names the closure digest actually published.
        expected = closure_digest_of_dependencies(manifest.get("dependencies", []))
        if lifecycle.get("closure_digest") != expected:
            findings.append(
                f"closure_digest_mismatch:{path.name}: sign-off names "
                f"{lifecycle.get('closure_digest')}, published closure is {expected}"
            )
        review_path = reviews.get(key)
        if review_path is None:
            findings.append(
                f"publish_record_without_review:{path.name}: no review record for {key}"
            )
            continue
        review = parsed_by_path[review_path]["review"]
        if review.get("closure_digest") != expected:
            findings.append(
                f"closure_digest_mismatch:{review_path.name}: review sign-off names "
                f"{review.get('closure_digest')}, published closure is {expected}"
            )
        # CR-11/CR-14: the signed manifest's review block pins the review
        # record's own canonical digest, and the record pins the release.
        review_raw = review_path.read_bytes()
        block = manifest.get("review", {})
        if block.get("record_sha256") != sha256_hex(review_raw):
            findings.append(
                f"review_record_digest_mismatch:{release_path.name}: review block pins "
                f"{block.get('record_sha256')}, record digest is {sha256_hex(review_raw)}"
            )
        if block.get("outcome") != review.get("outcome"):
            findings.append(
                f"review_outcome_mismatch:{release_path.name}: manifest review block says "
                f"{block.get('outcome')}, record says {review.get('outcome')}"
            )
    return findings


def main(argv: list[str] | str | None = None) -> int:
    root = REPO
    if isinstance(argv, str):
        root = Path(argv).resolve()
    elif argv:
        root = Path(argv[0]).resolve()
    findings = validate_tree(root)
    for finding in findings:
        print(f"validate_records: {finding}", file=sys.stderr)
    if findings:
        return 1
    print(f"validate_records: {len(record_paths(root / 'records'))} records valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
