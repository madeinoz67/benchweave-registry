"""Issue #225 slice-3 arms: schema motion, namespace/vetting, lifecycle pairs.

RED-first: each arm was written and proven failing before the mechanism it
pins landed (per-commit, in-history). The fixture contract lives in
``tests/fixtures/issue225/`` (committed first); these arms execute it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import validate_records as vr

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "issue225"

HEX64 = "a" * 64
HEX40 = "b" * 40

CAPS = {
    "network_egress": False,
    "subprocess_or_native_library": False,
    "filesystem_writes_beyond_evidence_retention": False,
}
COMPONENTS = [
    "adapter-source", "build-provenance", "capability-declaration", "closure-diff",
    "conformance-evidence", "dependency-lock", "descriptor", "licence",
    "payload-inventory", "release-manifest",
]


def review_record(
    publisher: str = "madeinoz67", plugin: str = "dps150", version: str = "0.1.0"
) -> dict[str, Any]:
    return {
        "record_type": "review",
        "record_version": "1.0.0",
        "kind": "admitted-release",
        "created_at": "2026-10-02T00:00:00Z",
        "actor": "madeinoz67",
        "review": {
            "publisher": publisher,
            "plugin": plugin,
            "version": version,
            "checklist_id": "review-checklist",
            "checklist_version": "1",
            "reviewer_id": "madeinoz67",
            "outcome": "accepted",
            "submission_manifest_sha256": HEX64,
            "source_revision": HEX40,
            "closure_digest": "c" * 64,
            "capability_declaration": CAPS,
            "platform_findings": [
                {"source": "code-scanning", "state": "consulted-no-findings"}
            ],
            "execution_model_disclosure": (
                "in-process execution with full gateway authority; no Python sandbox"
            ),
            "components": COMPONENTS,
        },
    }


def publish_record(
    publisher: str = "madeinoz67",
    plugin: str = "dps150",
    version: str = "0.1.0",
) -> dict[str, Any]:
    return {
        "record_type": "lifecycle",
        "record_version": "1.0.0",
        "kind": "admitted-release",
        "created_at": "2026-10-02T00:00:00Z",
        "actor": "madeinoz67",
        "lifecycle": {
            "op": "publish",
            "publisher": publisher,
            "plugin": plugin,
            "version": version,
            "reason": "fixture publish record",
            "release_manifest_sha256": "d" * 64,
            "closure": {"prior": None, "added": [], "changed": [], "removed": []},
            "closure_digest": "c" * 64,
            "signature_state": "signed-valid",
        },
    }


def lifecycle_record(
    op: str,
    publisher: str = "madeinoz67",
    plugin: str = "dps150",
    version: str = "0.1.0",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    block: dict[str, Any] = {
        "op": op,
        "publisher": publisher,
        "plugin": plugin,
        "version": version,
        "reason": f"fixture {op} record",
    }
    if extra:
        block.update(extra)
    return {
        "record_type": "lifecycle",
        "record_version": "1.1.0",
        "kind": "admitted-release",
        "created_at": "2026-10-02T00:00:00Z",
        "actor": "madeinoz67",
        "lifecycle": block,
    }


def findings_for(record: dict[str, Any]) -> list[str]:
    findings, _parsed = vr.validate_record(vr.canonical_bytes(record), Path("x.json"))
    return findings


def plant_publishers(root: Path, entry: dict[str, Any], version: int = 2) -> None:
    (root / "records").mkdir(parents=True, exist_ok=True)
    (root / "records" / "publishers.json").write_bytes(
        vr.canonical_bytes({"publishers_version": version, "publishers": [entry]})
    )


def vetted_entry(publisher_id: str = "madeinoz67", namespace: str = "madeinoz67") -> dict[str, Any]:
    return {
        "publisher_id": publisher_id,
        "namespace": namespace,
        "github": "madeinoz67",
        "vetted_at": "2026-10-02T00:00:00Z",
        "publisher_repo_protections": [
            {"protection": "push-protection", "state": "declared-not-verified"}
        ],
        "vetting": {
            "checklist_id": "vetting-checklist",
            "checklist_version": "1",
            "cited_rows": ["V-01", "V-02", "V-03", "V-04", "V-05", "V-06"],
            "vetted_by": "madeinoz67",
        },
    }


# ── records schema 1.1.0 (design §2.5) ────────────────────────────────────────


def test_record_version_enum_admits_1_1_0() -> None:
    """F4's default: the enum arm — a 1.1.0 record is schema-valid and every
    existing 1.0.0 record stays valid (no restamp, old-valid forever)."""
    assert findings_for(lifecycle_record("withdraw")) == []
    assert findings_for(review_record()) == []


def test_withdraw_op_is_in_the_lifecycle_enum() -> None:
    record = lifecycle_record("withdraw")
    assert findings_for(record) == []


def test_yank_record_requires_digest_and_status_sequence() -> None:
    """Schema 1.1.0's per-op if/then: a yank record names the release digest
    it governs AND the status sequence it corresponds to."""
    record = lifecycle_record("yank")
    findings = findings_for(record)
    assert any(
        "record_schema_invalid" in f and "status_sequence" in f for f in findings
    ), findings
    assert any(
        "record_schema_invalid" in f and "release_manifest_sha256" in f
        for f in findings
    ), findings


def test_yank_record_with_required_fields_passes() -> None:
    record = lifecycle_record(
        "yank", extra={"release_manifest_sha256": HEX64, "status_sequence": 2}
    )
    assert findings_for(record) == []


def test_advisory_record_requires_the_advisory_block() -> None:
    record = lifecycle_record("advisory")
    findings = findings_for(record)
    assert any("record_schema_invalid" in f and "advisory" in f for f in findings), findings


def test_advisory_record_with_the_block_passes() -> None:
    record = lifecycle_record(
        "advisory",
        extra={
            "advisory": {
                "id": "BW-ADV-001",
                "severity": "medium",
                "summary": "Synthetic advisory fixture.",
                "url": "https://example.invalid/advisories/BW-ADV-001",
            }
        },
    )
    assert findings_for(record) == []


def test_advisory_severity_enum_matches_the_status_schema() -> None:
    """One authority: the records schema's advisory severity enum is the
    vendored release-status schema's advisories severity enum, pinned equal
    (the lifecycle-enum derivation discipline applied to the new block)."""
    records_schema = json.loads((REPO / "records" / "records.schema.json").read_bytes())
    status_schema = json.loads(
        (REPO / "vendored" / "gateway" / "release-status.schema.json").read_bytes()
    )
    assert records_schema["properties"]["lifecycle"]["properties"]["advisory"][
        "properties"
    ]["severity"]["enum"] == status_schema["properties"]["advisories"]["items"][
        "properties"
    ]["severity"]["enum"]


# ── publishers schema v2 (design §2.4/§2.5) ──────────────────────────────────


def test_publishers_entry_without_vetting_block_is_refused() -> None:
    entry = vetted_entry()
    del entry["vetting"]
    findings, _ = _publishers_findings(entry)
    assert any(
        "record_schema_invalid" in f and "vetting" in f for f in findings
    ), findings


def test_publishers_v2_entry_with_vetting_block_passes() -> None:
    findings, _ = _publishers_findings(vetted_entry())
    assert findings == [], findings


def test_committed_publishers_json_is_v2_valid() -> None:
    """The restamp: the repo's own publishers.json validates under v2."""
    raw = (REPO / "records" / "publishers.json").read_bytes()
    parsed = json.loads(raw)
    assert vr.canonical_bytes(parsed) == raw, "publishers.json must stay canonical"
    errors = sorted(
        vr._validator("publishers.schema.json").iter_errors(parsed), key=str
    )
    assert errors == [], [e.message for e in errors]


def _publishers_findings(entry: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    document = {"publishers_version": 2, "publishers": [entry]}
    errors = sorted(
        vr._validator("publishers.schema.json").iter_errors(document), key=str
    )
    findings = [
        f"record_schema_invalid:publishers.json: {err.json_path}: {err.message}"
        for err in errors
    ]
    return findings, document


# ── the committed truth tables are well-formed contracts ─────────────────────


def test_queue_truth_table_covers_all_seven_stages_in_full_mode() -> None:
    table = json.loads((FIXTURES / "queue-truth-table.json").read_bytes())
    stages = {row["full_mode"] for row in table["rows"]}
    assert stages == set(table["stage_order"]), stages
    assert len(table["rows"]) == 8, "2 publishers x 4 submissions"


def test_namespace_vetting_table_names_the_design_prefixes() -> None:
    table = json.loads((FIXTURES / "namespace-vetting.truth-table.json").read_bytes())
    prefixes = {row.get("expected_finding") for row in table["rows"]}
    for expected in (
        "publisher_unvetted:",
        "namespace_collision:",
        "namespace_reserved:",
        "namespace_lookalike:",
        "yank_status_absent:",
        "status_yank_unrecorded:",
        "advisory_status_absent:",
        "withdraw_after_publication:",
        "transfer_receiver_unvetted:",
        "transfer_vetting_unresolved:",
        "vetting_row_unknown:",
    ):
        assert expected in prefixes, f"truth table lost the {expected} contract row"


def test_similarity_vectors_are_pinned_by_the_truth_table() -> None:
    """The twin-test discipline: the lane-rules vectors appear in the truth
    table with their comparison sets, so both repos pin the same five."""
    rules = json.loads((REPO / "lane-rules.json").read_bytes())
    vectors = rules["similarity_rule"]["vectors"]
    table = json.loads((FIXTURES / "namespace-vetting.truth-table.json").read_bytes())
    inputs = {row["input"] for row in table["rows"] if row["surface"] == "similarity-rule"}
    assert len(inputs) == len(vectors) == 5
