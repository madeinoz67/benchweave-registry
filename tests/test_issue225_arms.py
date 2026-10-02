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
    # five at v1; sim-v6/v7 fold-added; sim-v8..v11 supplement folds
    assert len(inputs) == len(vectors) == 11


# ── gate arms: the tree-level validity checks (design §2.4) ───────────────────
#
# Every arm builds a minimal self-contained tree: the fixture publishers
# (northwind-instruments / harborline-systems, both vetted) + the vetting
# checklist + whatever records and release documents the arm names.


def _gate_tree(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "records").mkdir(parents=True)
    (root / "records" / "publishers.json").write_bytes(
        (FIXTURES / "queue-records" / "records" / "publishers.json").read_bytes()
    )
    (root / "vetting-checklist.md").write_bytes((REPO / "vetting-checklist.md").read_bytes())
    (root / "lane-rules.json").write_bytes((REPO / "lane-rules.json").read_bytes())
    return root


def _plant(root: Path, record: dict[str, Any], seq: int = 1) -> None:
    lc = record.get("lifecycle") or record.get("review", {})
    sub = "lifecycle" if record.get("record_type") == "lifecycle" else "submissions"
    target = root / "records" / sub / lc["publisher"] / lc["plugin"] / lc["version"]
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{seq}-{lc.get('op', 'review')}.json").write_bytes(
        vr.canonical_bytes(record)
    )


def _release(root: Path, publisher: str, plugin: str, version: str,
             status: dict[str, Any] | None = None,
             review_block: dict[str, Any] | None = None) -> Path:
    release = root / "releases" / "benchweave-registry" / publisher / plugin / version
    release.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "registry_id": "benchweave-registry",
        "package_id": f"{publisher}/{plugin}",
        "version": version,
        "publisher_id": publisher,
    }
    if review_block is not None:
        manifest["review"] = review_block
    (release / "manifest.json").write_bytes(vr.canonical_bytes(manifest))
    if status is not None:
        (release / "status.json").write_bytes(vr.canonical_bytes(status))
    return release


def _findings(root: Path) -> list[str]:
    return vr.validate_tree(root)

def _submission_artefacts(root: Path, publisher: str, plugin: str, version: str) -> None:
    artefacts = (
        root / "records" / "submissions" / publisher / plugin / version / "artefacts"
    )
    artefacts.mkdir(parents=True, exist_ok=True)
    (artefacts / "submission.json").write_bytes(
        vr.canonical_bytes({"submission_version": "0.1.1", "entries": []})
    )




# --- the namespace arm (CR-15/16/39, records-side) ------------------------------


def test_unvetted_publisher_record_is_refused(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    _plant(root, review_record(publisher="driftwood-labs", plugin="widget"))
    findings = _findings(root)
    assert any(f.startswith("publisher_unvetted:") for f in findings), findings


def test_reserved_namespace_exact_is_refused_at_vetting(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    _plant_publishers_entry(root, "stg-mirror", "stg")
    findings = _findings(root)
    assert any(f.startswith("namespace_reserved:") for f in findings), findings


def test_reserved_namespace_extension_is_refused_at_vetting(tmp_path: Path) -> None:
    """The lane-rules vector's reading: 'otdp-tools' extends the reserved
    'otdp' — a candidate near a RESERVED name is reserved, not lookalike."""
    root = _gate_tree(tmp_path)
    _plant_publishers_entry(root, "otdp-tools", "otdp-tools")
    findings = _findings(root)
    assert any(f.startswith("namespace_reserved:") for f in findings), findings


def test_lookalike_namespace_is_refused_at_vetting(tmp_path: Path) -> None:
    """Vetting REFUSES where package-time only flags (CR-39): a namespace
    near an existing vetted namespace never admits."""
    root = _gate_tree(tmp_path)
    _plant_publishers_entry(root, "northwind-instrumentz", "northwind-instrumentz")
    findings = _findings(root)
    assert any(f.startswith("namespace_lookalike:") for f in findings), findings


def test_duplicate_namespace_claim_is_a_collision(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    _plant_publishers_entry(root, "harborline-mirror", "harborline-systems")
    findings = _findings(root)
    assert any(f.startswith("namespace_collision:") for f in findings), findings


def test_reserved_plugin_name_record_is_refused(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    record = publish_record(publisher="northwind-instruments", plugin="sim-psu")
    record["record_version"] = "1.1.0"
    _plant(root, record)
    findings = _findings(root)
    assert any(f.startswith("namespace_reserved:") for f in findings), findings


def test_vetted_fixture_publishers_pass(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    assert _findings(root) == []


def _plant_publishers_entry(root: Path, publisher_id: str, namespace: str) -> None:
    document = json.loads((root / "records" / "publishers.json").read_bytes())
    document["publishers"].append(
        vetted_entry(publisher_id, namespace)
    )
    (root / "records" / "publishers.json").write_bytes(vr.canonical_bytes(document))


# --- the vetting-citation arm ----------------------------------------------------


def test_unknown_vetting_row_is_refused(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    entry = vetted_entry("kestrel-devices", "kestrel-devices")
    entry["vetting"]["cited_rows"] = ["V-01", "V-99"]
    _plant_publishers_entry_full(root, entry)
    findings = _findings(root)
    assert any(f.startswith("vetting_row_unknown:") for f in findings), findings


def test_missing_checklist_file_is_refused(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    (root / "vetting-checklist.md").unlink()
    findings = _findings(root)
    assert any(f.startswith("vetting_checklist_absent:") for f in findings), findings


def _plant_publishers_entry_full(root: Path, entry: dict[str, Any]) -> None:
    document = json.loads((root / "records" / "publishers.json").read_bytes())
    document["publishers"].append(entry)
    (root / "records" / "publishers.json").write_bytes(vr.canonical_bytes(document))


# --- the lifecycle pair checks (§2.3) ---------------------------------------------


def test_yank_without_governing_status_refuses(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    _release(root, "northwind-instruments", "alpha-tool", "1.0.0")
    _plant(root, lifecycle_record(
        "yank", publisher="northwind-instruments", plugin="alpha-tool", version="1.0.0",
        extra={"release_manifest_sha256": HEX64, "status_sequence": 2},
    ))
    findings = _findings(root)
    assert any(f.startswith("yank_status_absent:") for f in findings), findings


def test_yanked_status_without_a_yank_record_refuses(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    _release(root, "northwind-instruments", "alpha-tool", "1.0.0",
             status={"lifecycle": "yanked", "sequence": 2})
    findings = _findings(root)
    assert any(f.startswith("status_yank_unrecorded:") for f in findings), findings


def test_coherent_yank_passes(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    _release(root, "northwind-instruments", "alpha-tool", "1.0.0",
             status={"lifecycle": "yanked", "sequence": 2})
    _plant(root, lifecycle_record(
        "yank", publisher="northwind-instruments", plugin="alpha-tool", version="1.0.0",
        extra={"release_manifest_sha256": HEX64, "status_sequence": 2},
    ))
    assert _findings(root) == []


def test_yank_citing_a_future_status_revision_refuses(tmp_path: Path) -> None:
    """Ordering, not equality (fold row 1): the record must not claim a
    status revision NEWER than the served document."""
    root = _gate_tree(tmp_path)
    _release(root, "northwind-instruments", "alpha-tool", "1.0.0",
             status={"lifecycle": "yanked", "sequence": 4})
    _plant(root, lifecycle_record(
        "yank", publisher="northwind-instruments", plugin="alpha-tool", version="1.0.0",
        extra={"release_manifest_sha256": HEX64, "status_sequence": 5},
    ))
    findings = _findings(root)
    assert any(f.startswith("yank_status_sequence_mismatch:") for f in findings), findings


def test_yank_then_advise_tree_is_valid(tmp_path: Path) -> None:
    """Fold row 1's RED arm (critic F1): yank@seq2 + advise@seq3 - the
    CVE-documentation pattern §2.3 invites by preserving advisories through
    yank. Equality pinned this tree red forever; ordering keeps it
    representable (record cites 2 <= served 3, lifecycle yanked)."""
    root = _gate_tree(tmp_path)
    _release(root, "northwind-instruments", "alpha-tool", "1.0.0",
             status={"lifecycle": "yanked", "sequence": 3, "advisories": [
                 {"id": "BW-ADV-001", "severity": "medium",
                  "summary": "s", "url": "https://example.invalid/b"}
             ]})
    _plant(root, lifecycle_record(
        "yank", publisher="northwind-instruments", plugin="alpha-tool", version="1.0.0",
        extra={"release_manifest_sha256": HEX64, "status_sequence": 2},
    ), seq=2)
    _plant(root, lifecycle_record(
        "advisory", publisher="northwind-instruments", plugin="alpha-tool",
        version="1.0.0",
        extra={"advisory": {
            "id": "BW-ADV-001", "severity": "medium",
            "summary": "s", "url": "https://example.invalid/b",
        }},
    ), seq=3)
    assert _findings(root) == []


def test_advisory_absent_from_served_status_refuses(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    _release(root, "northwind-instruments", "alpha-tool", "1.0.0",
             status={"lifecycle": "published", "sequence": 2, "advisories": [
                 {"id": "BW-ADV-OTHER", "severity": "low",
                  "summary": "s", "url": "https://example.invalid/a"}
             ]})
    _plant(root, lifecycle_record(
        "advisory", publisher="northwind-instruments", plugin="alpha-tool",
        version="1.0.0",
        extra={"advisory": {
            "id": "BW-ADV-001", "severity": "medium",
            "summary": "s", "url": "https://example.invalid/b",
        }},
    ))
    findings = _findings(root)
    assert any(f.startswith("advisory_status_absent:") for f in findings), findings


def test_advisory_present_in_served_status_passes(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    _release(root, "northwind-instruments", "alpha-tool", "1.0.0",
             status={"lifecycle": "published", "sequence": 2, "advisories": [
                 {"id": "BW-ADV-001", "severity": "medium",
                  "summary": "s", "url": "https://example.invalid/b"}
             ]})
    _plant(root, lifecycle_record(
        "advisory", publisher="northwind-instruments", plugin="alpha-tool",
        version="1.0.0",
        extra={"advisory": {
            "id": "BW-ADV-001", "severity": "medium",
            "summary": "s", "url": "https://example.invalid/b",
        }},
    ))
    assert _findings(root) == []


# --- the withdraw arm (CR-32) ------------------------------------------------------


def test_withdraw_after_publication_refuses(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    _submission_artefacts(root, "northwind-instruments", "beta-tool", "1.0.0")
    _release(root, "northwind-instruments", "beta-tool", "1.0.0")
    publish = publish_record(
        publisher="northwind-instruments", plugin="beta-tool", version="1.0.0"
    )
    publish["record_version"] = "1.1.0"
    _plant(root, publish, seq=1)
    _plant(root, lifecycle_record(
        "withdraw", publisher="northwind-instruments", plugin="beta-tool", version="1.0.0",
    ), seq=2)
    findings = _findings(root)
    assert any(f.startswith("withdraw_after_publication:") for f in findings), findings


def test_withdraw_at_higher_numeric_seq_still_refuses(tmp_path: Path) -> None:
    """Fold row 2's RED arm (critic F2): "10-withdraw.json" sorts BEFORE
    "2-publish.json" lexicographically, so a single mid-pass evaluation of
    the CR-32 arm saw the withdraw before the publish existed."""
    root = _gate_tree(tmp_path)
    _submission_artefacts(root, "northwind-instruments", "beta-tool", "1.0.0")
    _release(root, "northwind-instruments", "beta-tool", "1.0.0")
    publish = publish_record(
        publisher="northwind-instruments", plugin="beta-tool", version="1.0.0"
    )
    publish["record_version"] = "1.1.0"
    _plant(root, publish, seq=2)
    _plant(root, lifecycle_record(
        "withdraw", publisher="northwind-instruments", plugin="beta-tool", version="1.0.0",
    ), seq=10)
    findings = _findings(root)
    assert any(f.startswith("withdraw_after_publication:") for f in findings), findings


def test_pre_acceptance_withdraw_passes(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    _submission_artefacts(root, "northwind-instruments", "beta-tool", "1.0.0")
    _plant(root, lifecycle_record(
        "withdraw", publisher="northwind-instruments", plugin="beta-tool", version="1.0.0",
    ))
    assert _findings(root) == []


# --- the transfer arm (CR-17/Q9) ----------------------------------------------------


def _transfer_record(extra_transfer: dict[str, Any] | None = None) -> dict[str, Any]:
    block = {
        "from_publisher": "northwind-instruments",
        "to_publisher": "harborline-systems",
        "consents": ["northwind-instruments", "harborline-systems"],
        "vetting_reference": "publishers.json#harborline-systems",
    }
    if extra_transfer:
        block.update(extra_transfer)
    return lifecycle_record(
        "transfer", publisher="northwind-instruments", plugin="gamma-tool",
        version="1.0.0", extra={"transfer": block},
    )


def test_transfer_to_unvetted_receiver_refuses(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    _release(root, "northwind-instruments", "gamma-tool", "1.0.0")
    _plant(root, _transfer_record({"to_publisher": "driftwood-labs"}))
    findings = _findings(root)
    assert any(f.startswith("transfer_receiver_unvetted:") for f in findings), findings


def test_transfer_with_unresolved_vetting_reference_refuses(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    _release(root, "northwind-instruments", "gamma-tool", "1.0.0")
    _plant(root, _transfer_record({"vetting_reference": "vetting/2024-09.pdf"}))
    findings = _findings(root)
    assert any(f.startswith("transfer_vetting_unresolved:") for f in findings), findings


def test_transfer_without_both_consents_refuses(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    _release(root, "northwind-instruments", "gamma-tool", "1.0.0")
    _plant(root, _transfer_record({"consents": ["northwind-instruments"]}))
    findings = _findings(root)
    assert any(f.startswith("transfer_consents_incomplete:") for f in findings), findings


def test_coherent_transfer_passes(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    _release(root, "northwind-instruments", "gamma-tool", "1.0.0")
    _plant(root, _transfer_record())
    assert _findings(root) == []


# --- the similarity rule's committed vectors (twin-test discipline) -----------------


def test_similarity_vectors_hold_under_the_committed_rule() -> None:
    """The committed lane-rules vectors, each run against the comparison set
    its expected label types (the truth table's disclosed reading). Fold row
    5 added the skeleton-equal confusable and a containment cell (seven)."""
    rules = json.loads((REPO / "lane-rules.json").read_bytes())
    vectors = rules["similarity_rule"]["vectors"]
    assert len(vectors) == 11, [v["candidate"] for v in vectors]
    table = json.loads((FIXTURES / "namespace-vetting.truth-table.json").read_bytes())
    rows = {row["input"]: row for row in table["rows"]
            if row["surface"] == "similarity-rule"}
    for vector in vectors:
        key = next(k for k in rows if k.startswith(vector["candidate"] + " "))
        row = rows[key]
        verdict = vr.namespace_verdict(
            vector["candidate"], vector["existing"],
            reserved=row["comparison_set"] == "reserved",
            rules=rules,
        )
        assert verdict == row["expected"], (vector, verdict, row["expected"])


# ── fold rows 3/4/8: fail-closed authorities, seq uniqueness, equality ────────


def test_gate_refuses_when_authorities_are_absent(tmp_path: Path) -> None:
    """Fold row 3 (critic M3/F4): records without their authorities are
    §1.2's vacuity class reborn - the gate was green with unvetted and
    reserved records planted, because nothing forced the authority files
    to exist."""
    root = _gate_tree(tmp_path)
    (root / "records" / "publishers.json").unlink()
    (root / "lane-rules.json").unlink()
    _plant(root, publish_record(publisher="driftwood-labs", plugin="widget"))
    findings = _findings(root)
    assert any(f.startswith("authority_absent:records/publishers.json") for f in findings), findings
    assert any(f.startswith("authority_absent:lane-rules.json") for f in findings), findings


def test_duplicate_record_sequences_refuse(tmp_path: Path) -> None:
    """Fold row 4 (critic M1b/F3): two records at one numeric sequence on
    one release must not merge silently. Gap-free stays optional - a
    documented choice, not an arm."""
    root = _gate_tree(tmp_path)
    _release(root, "northwind-instruments", "beta-tool", "1.0.0")
    _plant(root, lifecycle_record(
        "withdraw", publisher="northwind-instruments", plugin="beta-tool", version="1.0.0",
    ), seq=4)
    _plant(root, lifecycle_record(
        "yank", publisher="northwind-instruments", plugin="beta-tool", version="1.0.0",
        extra={"release_manifest_sha256": HEX64, "status_sequence": 5},
    ), seq=4)
    findings = _findings(root)
    assert any(f.startswith("record_seq_duplicate:") for f in findings), findings


def test_publisher_namespace_equality_is_pinned(tmp_path: Path) -> None:
    """Fold row 8 (conditional): every committed + fixture entry carries
    publisher_id == namespace (verified by hand before folding), so the
    equality is pinned. A divergent claim refuses - cross-field equality is
    not expressible in JSON Schema 2020-12, so the arm lives in the gate."""
    root = _gate_tree(tmp_path)
    _plant_publishers_entry(root, "tidewater-probes", "tide-probes")
    findings = _findings(root)
    assert any(
        f.startswith("publisher_namespace_mismatch:") for f in findings
    ), findings


def test_committed_and_fixture_publishers_carry_the_equality() -> None:
    """Row 8's CHECK arm: universally true in the committed data and the
    queue fixture before the fold landed."""
    committed = json.loads((REPO / "records" / "publishers.json").read_bytes())
    fixture = json.loads(
        (FIXTURES / "queue-records" / "records" / "publishers.json").read_bytes()
    )
    for document in (committed, fixture):
        for entry in document["publishers"]:
            assert entry["publisher_id"] == entry["namespace"], entry


# ── supplement rows (adversary lanes A/B + reviewer): RED-first ───────────────


def test_latest_review_resolves_by_numeric_sequence(tmp_path: Path) -> None:
    """A2: review-10.json sorts BEFORE review-9.json lexicographically —
    the last-write-wins resolution picked the OLDER review. The seq-10
    review must govern (the manifest block pins it, and the tree is clean
    only under the numeric reading)."""
    root = _gate_tree(tmp_path)
    # governed-by-10 chain: review-9 changes-requested, review-10 accepted,
    # publish record + manifest review block pin review-10.
    closure = vr.closure_digest_of_dependencies([])
    older = review_record(
        publisher="northwind-instruments", plugin="epsilon-probe", version="1.0.0"
    )
    older["review"]["outcome"] = "changes-requested"
    older["review"]["cited_failures"] = ["P-03"]
    older["review"]["closure_digest"] = closure
    newer = review_record(
        publisher="northwind-instruments", plugin="epsilon-probe", version="1.0.0"
    )
    newer["review"]["closure_digest"] = closure
    target = root / "records" / "submissions" / "northwind-instruments" / "epsilon-probe" / "1.0.0"
    target.mkdir(parents=True)
    (target / "review-9.json").write_bytes(vr.canonical_bytes(older))
    (target / "review-10.json").write_bytes(vr.canonical_bytes(newer))
    release = _release(
        root, "northwind-instruments", "epsilon-probe", "1.0.0",
        review_block={"record_sha256": vr.sha256_hex(vr.canonical_bytes(newer)),
                      "outcome": "accepted"},
    )
    publish = publish_record(
        publisher="northwind-instruments", plugin="epsilon-probe", version="1.0.0"
    )
    publish["record_version"] = "1.1.0"
    publish["lifecycle"]["closure_digest"] = closure
    publish["lifecycle"]["release_manifest_sha256"] = vr.sha256_hex(
        (release / "manifest.json").read_bytes()
    )
    _plant(root, publish, seq=1)
    findings = _findings(root)
    assert findings == [], findings


def test_advisory_in_status_without_a_record_refuses(tmp_path: Path) -> None:
    """B2: the advisory pairing is bidirectional — a served advisory with no
    advisory record is the silent divergence §2.3 refuses in EITHER
    direction (the yank direction already refused)."""
    root = _gate_tree(tmp_path)
    _release(root, "northwind-instruments", "alpha-tool", "1.0.0",
             status={"lifecycle": "published", "sequence": 2, "advisories": [
                 {"id": "BW-ADV-001", "severity": "medium",
                  "summary": "s", "url": "https://example.invalid/b"}
             ]})
    findings = _findings(root)
    assert any(f.startswith("status_advisory_unrecorded:") for f in findings), findings


def test_record_filed_at_a_misleading_path_refuses(tmp_path: Path) -> None:
    """B5: path<->block agreement — a record's directory names the
    submission it belongs to; a block claiming another identity refuses."""
    root = _gate_tree(tmp_path)
    record = lifecycle_record(
        "withdraw", publisher="northwind-instruments", plugin="alpha-tool", version="1.0.0",
    )
    target = root / "records" / "lifecycle" / "northwind-instruments" / "beta-tool" / "1.0.0"
    target.mkdir(parents=True)
    (target / "5-withdraw.json").write_bytes(vr.canonical_bytes(record))
    findings = _findings(root)
    assert any(f.startswith("record_path_mismatch:") for f in findings), findings


def test_reserved_plugin_near_shapes_refuse(tmp_path: Path) -> None:
    """C1: the reserved-plugin arm gets the same near-aware predicate as the
    namespace arm — '5im-psu' skeleton-folds exactly onto reserved
    'sim-psu' (the strongest impersonation shape), 'sim-psu-labs' is the
    delimiter-bounded extension. Both refused end-to-end."""
    for plugin in ("5im-psu", "sim-psu-labs"):
        root = _gate_tree(tmp_path / plugin)
        record = publish_record(publisher="northwind-instruments", plugin=plugin)
        record["record_version"] = "1.1.0"
        _plant(root, record)
        findings = _findings(root)
        assert any(
            f.startswith("namespace_reserved:") and plugin in f for f in findings
        ), (plugin, findings)


def test_reserved_prefix_boundary_is_delimiter_bounded() -> None:
    """B6: containment means the reserved token followed by a SEPARATOR (or
    exact/skeleton-equal) — dev-tools-inc claims 'dev'; devlin-instruments
    merely begins with the letters and passes the reserved set."""
    rules = json.loads((REPO / "lane-rules.json").read_bytes())
    assert vr.namespace_verdict(
        "dev-tools-inc", "dev", reserved=True, rules=rules
    ) == "reserved"
    assert vr.namespace_verdict(
        "devlin-instruments", "dev", reserved=True, rules=rules
    ) == "distinct"


def test_submission_artefacts_are_payload_not_records(tmp_path: Path) -> None:
    """C2: the named exclusion — artefacts/ subtrees under
    records/submissions/ are submission payload (the submit flow stages
    them; the index generator reads them), never validity-gated records."""
    root = _gate_tree(tmp_path)
    artefacts = (
        root / "records" / "submissions" / "northwind-instruments" / "delta-tool"
        / "1.0.0" / "artefacts"
    )
    artefacts.mkdir(parents=True)
    (artefacts / "submission.json").write_bytes(
        vr.canonical_bytes({"submission_version": "0.1.1", "entries": []})
    )
    _plant(root, lifecycle_record(
        "withdraw", publisher="northwind-instruments", plugin="delta-tool", version="1.0.0",
    ))
    findings = _findings(root)
    assert findings == [], findings


def test_artefacts_exclusion_does_not_disarm_the_authority_census(tmp_path: Path) -> None:
    """C2's pin: the exclusion is a document-class boundary, not a vacuity
    hole — real records still require their authorities with artefacts
    present."""
    root = _gate_tree(tmp_path)
    (root / "records" / "publishers.json").unlink()
    (root / "lane-rules.json").unlink()
    artefacts = (
        root / "records" / "submissions" / "northwind-instruments" / "delta-tool"
        / "1.0.0" / "artefacts"
    )
    artefacts.mkdir(parents=True)
    (artefacts / "submission.json").write_bytes(b'{"submission_version": "0.1.1"}\n')
    _plant(root, lifecycle_record(
        "withdraw", publisher="northwind-instruments", plugin="delta-tool", version="1.0.0",
    ))
    findings = _findings(root)
    assert any(f.startswith("authority_absent:") for f in findings), findings


# --- B3: the PR-state fixture matches the SDK queue normalizer's contract -----


def test_pr_state_fixture_maps_every_truth_table_submission() -> None:
    """B3: the fixture drives the SDK queue's normalizer — submission keys
    derive from the records/submissions/<p>/<x>/<v>/ file paths, manifest.sig
    detection from path basenames, states/reviews lowercase gh vocabulary."""
    import re as _re

    payload = json.loads((FIXTURES / "pr-state.json").read_bytes())
    assert isinstance(payload.get("prs"), list) and len(payload["prs"]) == 8
    pattern = _re.compile(
        r"^records/submissions/([a-z0-9][a-z0-9-]*)/([a-z0-9][a-z0-9_-]*)/"
        r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)/"
    )
    mapped: set[tuple[str, str, str]] = set()
    for entry in payload["prs"]:
        assert entry["state"] in {"open", "closed", "merged"}, entry
        for review in entry["reviews"]:
            assert isinstance(review, str) and review.islower(), entry
        assert entry["files"], "every PR must carry at least one submission path"
        for path in entry["files"]:
            match = pattern.match(path)
            assert match is not None, path
            mapped.add(
                (
                    match.group(1),
                    match.group(2),
                    f"{match.group(3)}.{match.group(4)}.{match.group(5)}",
                )
            )
    table = json.loads((FIXTURES / "queue-truth-table.json").read_bytes())
    expected = {
        (row["publisher"], row["plugin"], row["version"]) for row in table["rows"]
    }
    assert mapped == expected, (mapped ^ expected)


# ── wave-2 residuals: G1 guards, G3 shared numbering, G5 existence ────────────


def test_takedown_record_needs_no_status_sequence(tmp_path: Path) -> None:
    """G1's scope guard: the ordering semantics and the schema's
    status_sequence if/then bind op==yank ONLY — a takedown record (which
    pairs with a revoked status) carries no status_sequence and stays green.
    Pins the fold against overreach; green by design both before and after."""
    root = _gate_tree(tmp_path)
    _release(root, "northwind-instruments", "alpha-tool", "1.0.0",
             status={"lifecycle": "revoked", "sequence": 2})
    _plant(root, lifecycle_record(
        "takedown", publisher="northwind-instruments", plugin="alpha-tool",
        version="1.0.0",
    ), seq=2)
    assert _findings(root) == []


def test_re_yank_multiplicity_is_representable(tmp_path: Path) -> None:
    """G1's re-yank acceptance arm: N yank records each citing a sequence
    <= the served document are all green (ordering is <=, never one-record).
    DISCLOSED: nothing consumes re-yank multiplicity yet — the arm pins the
    representability, not a consumer."""
    root = _gate_tree(tmp_path)
    _release(root, "northwind-instruments", "alpha-tool", "1.0.0",
             status={"lifecycle": "yanked", "sequence": 4})
    _plant(root, lifecycle_record(
        "yank", publisher="northwind-instruments", plugin="alpha-tool", version="1.0.0",
        extra={"release_manifest_sha256": HEX64, "status_sequence": 2},
    ), seq=2)
    _plant(root, lifecycle_record(
        "yank", publisher="northwind-instruments", plugin="alpha-tool", version="1.0.0",
        extra={"release_manifest_sha256": HEX64, "status_sequence": 3},
    ), seq=3)
    assert _findings(root) == []


def test_yank_and_takedown_share_one_numbering_space(tmp_path: Path) -> None:
    """G3: sequences are ONE space per release directory across ops — yank
    and takedown at the same number collide (pinning the scoping; the
    uniqueness arm itself landed in the first fold)."""
    root = _gate_tree(tmp_path)
    _release(root, "northwind-instruments", "alpha-tool", "1.0.0",
             status={"lifecycle": "revoked", "sequence": 3})
    _plant(root, lifecycle_record(
        "yank", publisher="northwind-instruments", plugin="alpha-tool", version="1.0.0",
        extra={"release_manifest_sha256": HEX64, "status_sequence": 2},
    ), seq=2)
    _plant(root, lifecycle_record(
        "takedown", publisher="northwind-instruments", plugin="alpha-tool",
        version="1.0.0",
    ), seq=2)
    findings = _findings(root)
    assert any(f.startswith("record_seq_duplicate:") for f in findings), findings


# --- G5: inert-record existence -------------------------------------------------


def test_withdraw_on_a_nonexistent_submission_refuses(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    _plant(root, lifecycle_record(
        "withdraw",
        publisher="northwind-instruments",
        plugin="theta-tool",
        version="1.0.0",
    ))
    findings = _findings(root)
    assert any(f.startswith("record_subject_absent:") for f in findings), findings


def test_unlist_on_a_nonexistent_release_refuses(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    _plant(root, lifecycle_record(
        "unlist", publisher="northwind-instruments", plugin="eta-tool", version="1.0.0",
    ))
    findings = _findings(root)
    assert any(f.startswith("record_subject_absent:") for f in findings), findings


def test_transfer_on_a_nonexistent_release_refuses(tmp_path: Path) -> None:
    root = _gate_tree(tmp_path)
    _plant(root, _transfer_record())
    findings = _findings(root)
    assert any(f.startswith("record_subject_absent:") for f in findings), findings


def test_withdraw_with_staged_artefacts_is_the_pre_acceptance_shape(
    tmp_path: Path,
) -> None:
    """The C2 document-class boundary meets G5: the submit flow's staged
    artefacts ARE the submission's on-disk presence — a withdraw against
    them is the pre-acceptance shape and passes."""
    root = _gate_tree(tmp_path)
    _submission_artefacts(root, "northwind-instruments", "beta-tool", "1.0.0")
    _plant(root, lifecycle_record(
        "withdraw", publisher="northwind-instruments", plugin="beta-tool", version="1.0.0",
    ))
    assert _findings(root) == []
