"""A5/A4 record-validity arms (CR-10, CR-60, CR-56, CR-38, CR-35, CR-11/14).

Each arm feeds a mutant record through the validity checker and asserts the
refusal with its stable prefix; the control arms prove valid records pass.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import validate_records as vr

HEX64 = "a" * 64
HEX40 = "b" * 40


def review_record(outcome: str = "accepted") -> dict[str, Any]:
    record: dict[str, object] = {
        "record_type": "review",
        "record_version": "1.0.0",
        "kind": "admitted-release",
        "created_at": "2026-10-01T00:00:00Z",
        "actor": "madeinoz67",
        "review": {
            "publisher": "madeinoz67",
            "plugin": "dps150",
            "version": "0.1.0",
            "checklist_id": "review-checklist",
            "checklist_version": "1",
            "reviewer_id": "madeinoz67",
            "outcome": outcome,
            "submission_manifest_sha256": HEX64,
            "source_revision": HEX40,
            "closure_digest": "c" * 64,
            "capability_declaration": {
                "network_egress": False,
                "subprocess_or_native_library": False,
                "filesystem_writes_beyond_evidence_retention": False,
            },
            "platform_findings": [
                {"source": "code-scanning", "state": "consulted-no-findings"}
            ],
            "execution_model_disclosure": (
                "in-process execution with full gateway authority; no Python sandbox"
            ),
            "components": [
                "adapter-source",
                "build-provenance",
                "capability-declaration",
                "closure-diff",
                "conformance-evidence",
                "dependency-lock",
                "descriptor",
                "licence",
                "payload-inventory",
                "release-manifest",
            ],
        },
    }
    if outcome == "changes-requested":
        review = record["review"]
        assert isinstance(review, dict)
        review["cited_failures"] = ["P-03"]
    return record


def publish_record() -> dict[str, Any]:
    return {
        "record_type": "lifecycle",
        "record_version": "1.0.0",
        "kind": "admitted-release",
        "created_at": "2026-10-01T00:00:00Z",
        "actor": "madeinoz67",
        "lifecycle": {
            "op": "publish",
            "publisher": "madeinoz67",
            "plugin": "dps150",
            "version": "0.1.0",
            "reason": "initial dogfooded release",
            "release_manifest_sha256": "d" * 64,
            "closure": {"prior": None, "added": [], "changed": [], "removed": []},
            "closure_digest": "c" * 64,
            "signature_state": "signed-valid",
        },
    }


def findings_for(record: dict[str, Any]) -> list[str]:
    findings, _parsed = vr.validate_record(vr.canonical_bytes(record), Path("x.json"))
    return findings


def tree_with(root: Path, records: dict[str, dict[str, Any]]) -> Path:
    (root / "records").mkdir(parents=True, exist_ok=True)
    (root / "records" / "publishers.json").write_bytes(
        (Path(__file__).resolve().parents[1] / "records" / "publishers.json").read_bytes()
    )
    for name, record in records.items():
        target = root / "records" / "submissions" / "madeinoz67" / "dps150" / "0.1.0"
        target.mkdir(parents=True, exist_ok=True)
        (target / name).write_bytes(vr.canonical_bytes(record))
    return root


# --- A5: the two CI-refused fixtures ------------------------------------------


def test_changes_requested_without_cited_failure_is_refused() -> None:
    """CR-10 / A5 arm 1: a changes-requested record citing no failed row."""
    record = review_record(outcome="changes-requested")
    review = record["review"]
    assert isinstance(review, dict)
    del review["cited_failures"]
    findings = findings_for(record)
    assert any("record_schema_invalid" in f and "cited_failures" in f for f in findings), findings


def test_review_without_platform_findings_is_refused() -> None:
    """CR-60 / A5 arm 2: a review naming no platform findings at the pinned revision."""
    record = review_record()
    review = record["review"]
    assert isinstance(review, dict)
    review["platform_findings"] = []
    findings = findings_for(record)
    assert any("platform_findings" in f for f in findings), findings


def test_valid_accepted_review_passes() -> None:
    assert findings_for(review_record()) == []


def test_changes_requested_with_cited_failure_passes() -> None:
    assert findings_for(review_record(outcome="changes-requested")) == []


# --- A4's sixth gate and the CR-38/35/11 chain ---------------------------------


def test_publish_record_without_closure_diff_is_refused() -> None:
    """A4 arm 6: a publish record without the closure diff (`closure_diff_absent`)."""
    record = publish_record()
    lifecycle = record["lifecycle"]
    assert isinstance(lifecycle, dict)
    del lifecycle["closure"]
    findings = findings_for(record)
    assert any("record_schema_invalid" in f and "closure" in f for f in findings), findings


def test_record_without_kind_is_refused() -> None:
    """CR-56: kind is machine-checked at write time."""
    record = review_record()
    del record["kind"]
    findings = findings_for(record)
    assert any("record_schema_invalid" in f and "kind" in f for f in findings), findings


def test_non_canonical_bytes_are_refused() -> None:
    raw = json.dumps(review_record(), indent=2).encode()
    findings, _ = vr.validate_record(raw, Path("x.json"))
    assert "record_not_canonical:x.json" in findings


def _mini_release(
    root: Path, dependencies: list[dict[str, Any]], review_block: dict[str, Any] | None
) -> Path:
    release_dir = root / "releases" / "benchweave-registry" / "madeinoz67" / "dps150" / "0.1.0"
    release_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, object] = {"dependencies": dependencies}
    if review_block is not None:
        manifest["review"] = review_block
    path = release_dir / "manifest.json"
    path.write_bytes(vr.canonical_bytes(manifest))
    return path


def _consistent_release(root: Path, dependencies: list[dict[str, Any]]) -> tuple[Path, Path]:
    """A review record + publish record + release manifest whose chain agrees."""
    record = review_record()
    review = record["review"]
    assert isinstance(review, dict)
    digest = vr.closure_digest_of_dependencies(
        [dep for dep in dependencies if isinstance(dep, dict)]
    )
    review["closure_digest"] = digest
    tree_with(root, {"review-1.json": record})
    publish = publish_record()
    lifecycle = publish["lifecycle"]
    assert isinstance(lifecycle, dict)
    lifecycle["closure_digest"] = digest
    publish_path = root / "records" / "lifecycle" / "madeinoz67" / "dps150" / "0.1.0"
    publish_path.mkdir(parents=True, exist_ok=True)
    (publish_path / "1-publish.json").write_bytes(vr.canonical_bytes(publish))
    review_raw = (
        root / "records" / "submissions" / "madeinoz67" / "dps150" / "0.1.0" / "review-1.json"
    ).read_bytes()
    manifest_path = _mini_release(
        root,
        dependencies,
        {"record_sha256": vr.sha256_hex(review_raw), "outcome": "accepted"},
    )
    return manifest_path, publish_path


_DEPS: list[dict[str, Any]] = [
    {
        "registry_id": "benchweave-registry",
        "package_id": "madeinoz67/dps150-descriptor",
        "version": "0.1.0",
        "manifest_sha256": "e" * 64,
    }
]


def test_consistent_chain_passses(tmp_path: Path) -> None:
    _manifest, _publish = _consistent_release(tmp_path, copy.deepcopy(_DEPS))
    assert vr.validate_tree(tmp_path) == []


def test_closure_digest_mismatch_is_refused(tmp_path: Path) -> None:
    """CR-38: a sign-off naming a different closure digest than the one published."""
    _manifest, publish_path = _consistent_release(tmp_path, copy.deepcopy(_DEPS))
    publish = json.loads((publish_path / "1-publish.json").read_bytes())
    publish["lifecycle"]["closure_digest"] = "f" * 64
    (publish_path / "1-publish.json").write_bytes(vr.canonical_bytes(publish))
    findings = vr.validate_tree(tmp_path)
    assert any(f.startswith("closure_digest_mismatch:") for f in findings), findings


def test_review_record_digest_mismatch_is_refused(tmp_path: Path) -> None:
    """CR-11/CR-14: the signed manifest's review block must pin the review record."""
    manifest_path, _publish = _consistent_release(tmp_path, copy.deepcopy(_DEPS))
    manifest = json.loads(manifest_path.read_bytes())
    manifest["review"]["record_sha256"] = "0" * 64
    manifest_path.write_bytes(vr.canonical_bytes(manifest))
    findings = vr.validate_tree(tmp_path)
    assert any(f.startswith("review_record_digest_mismatch:") for f in findings), findings


def test_dev_prefixed_registry_id_in_record_is_refused(tmp_path: Path) -> None:
    """CR-35's records half: dev-unsigned lineage never reaches a committed record."""
    record = review_record()
    record["review"]["notes"] = "depends on dev-local/mutant"
    tree_with(tmp_path, {"review-1.json": record})
    findings = vr.validate_tree(tmp_path)
    assert any(f.startswith("dev_lineage_in_records:") for f in findings), findings


def test_main_returns_zero_on_valid_tree(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _manifest, _publish = _consistent_release(tmp_path, copy.deepcopy(_DEPS))
    assert vr.main(str(tmp_path)) == 0
    assert "2 records valid" in capsys.readouterr().out

# --- M1 (CR-35 fold): the published tree refuses dev-lineage ---------------------


def test_dev_lineage_release_tree_is_refused(tmp_path: Path) -> None:
    """CR-35's releases half: a dev-prefixed origin under releases/ refuses
    (the validity gate's docstring claims records AND releases)."""
    dev_release = tmp_path / "releases" / "dev-local" / "dev" / "widget" / "0.1.0"
    dev_release.mkdir(parents=True)
    (dev_release / "manifest.json").write_bytes(
        vr.canonical_bytes(
            {"registry_id": "dev-local", "package_id": "dev/widget", "version": "0.1.0"}
        )
    )
    findings = vr.validate_tree(tmp_path)
    assert any(f.startswith("dev_lineage_in_release:") for f in findings), findings


def test_dev_lineage_dependency_in_release_is_refused(tmp_path: Path) -> None:
    signed_origin = tmp_path / "releases" / "benchweave-registry" / "acme" / "tool" / "1.0.0"
    signed_origin.mkdir(parents=True)
    (signed_origin / "manifest.json").write_bytes(
        vr.canonical_bytes(
            {
                "registry_id": "benchweave-registry",
                "package_id": "acme/tool",
                "version": "1.0.0",
                "dependencies": [
                    {
                        "registry_id": "dev-local",
                        "package_id": "dev/widget",
                        "version": "1.0.0",
                        "manifest_sha256": "e" * 64,
                    }
                ],
            }
        )
    )
    findings = vr.validate_tree(tmp_path)
    assert any(f.startswith("dev_lineage_in_release:") for f in findings), findings

# --- F1 rework (issue #223): recorded and advertised, never enforced ----------


def test_publish_record_advertises_gateway_ref() -> None:
    record = publish_record()
    record["lifecycle"]["gateway_ref"] = "45d5e7fdc45dc6bbf765b1c8e85af70a2d830d94"
    record["lifecycle"]["signature_state"] = "signed-valid"
    assert findings_for(record) == []


def test_unpinned_publish_record_still_validates() -> None:
    """No publish-time enforcement: a release targeting no pin records fine."""
    record = publish_record()
    assert "gateway_ref" not in record["lifecycle"]
    record["lifecycle"]["signature_state"] = "unsigned"
    assert findings_for(record) == []


def test_publish_record_records_firmware_attestation() -> None:
    record = publish_record()
    record["lifecycle"]["firmware_attestation"] = {
        "vendor": "Exampleworks",
        "manifest": "firmware/vendor.manifest",
        "bytes": "vendor-distributed",
        "files": ["firmware/blob.bin"],
    }
    assert findings_for(record) == []

