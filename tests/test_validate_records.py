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

REPO = Path(__file__).resolve().parents[1]

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
    # Issue #225 slice 3: the vetting-citation arm resolves cited rows in the
    # tree's own checklist, and the namespace arms read the tree's lane rules.
    (root / "vetting-checklist.md").write_bytes(
        (Path(__file__).resolve().parents[1] / "vetting-checklist.md").read_bytes()
    )
    (root / "lane-rules.json").write_bytes(
        (Path(__file__).resolve().parents[1] / "lane-rules.json").read_bytes()
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
    manifest: dict[str, object] = {
        "package_id": "madeinoz67/dps150",
        "version": "0.1.0",
        "dependencies": dependencies,
    }
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
    review_raw = (
        root / "records" / "submissions" / "madeinoz67" / "dps150" / "0.1.0" / "review-1.json"
    ).read_bytes()
    manifest_path = _mini_release(
        root,
        dependencies,
        {"record_sha256": vr.sha256_hex(review_raw), "outcome": "accepted"},
    )
    publish_path = root / "records" / "lifecycle" / "madeinoz67" / "dps150" / "0.1.0"
    publish_path.mkdir(parents=True, exist_ok=True)
    publish["lifecycle"]["release_manifest_sha256"] = vr.sha256_hex(
        manifest_path.read_bytes()
    )
    (publish_path / "1-publish.json").write_bytes(vr.canonical_bytes(publish))
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
    assert vr.main(["--root", str(tmp_path)]) == 0
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


def test_timestamp_recommended_advisory_is_recorded() -> None:
    """The optional-but-recommended advisory rides the publish record."""
    record = publish_record()
    record["lifecycle"]["signature_state"] = "signed-valid"
    record["lifecycle"]["timestamp_recommended"] = True
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

# --- fold H2/M3/L2: reconciliation, path identity, traversal (2026-10-02) -------


def _sandbox_repo(tmp_path: Path) -> Path:
    import shutil

    sandbox = tmp_path / "repo"
    shutil.copytree(
        Path(__file__).resolve().parents[1],
        sandbox,
        ignore=shutil.ignore_patterns("venv", ".git", "__pycache__", ".wt"),
    )
    return sandbox


RELEASE = "releases/benchweave-registry/madeinoz67/dps150/0.1.0"


def test_post_recording_manifest_tamper_refuses(tmp_path: Path) -> None:
    """H2: permissions/transports changed in manifest.json after recording."""
    sandbox = _sandbox_repo(tmp_path)
    mpath = sandbox / RELEASE / "manifest.json"
    manifest = json.loads(mpath.read_bytes())
    manifest["permissions"] = ["network_egress"]
    manifest["device_targets"][0]["transports"] = ["tcp"]
    mpath.write_bytes(vr.canonical_bytes(manifest))
    findings = vr.validate_tree(sandbox)
    assert any(f.startswith("manifest_reconciliation_failed:") for f in findings), findings


def test_release_digest_pin_mismatch_refuses(tmp_path: Path) -> None:
    """H2: the publish record's release_manifest_sha256 pins the on-disk bytes."""
    sandbox = _sandbox_repo(tmp_path)
    mpath = sandbox / RELEASE / "manifest.json"
    manifest = json.loads(mpath.read_bytes())
    manifest["summary"] = "tampered summary"
    mpath.write_bytes(vr.canonical_bytes(manifest))
    findings = vr.validate_tree(sandbox)
    assert any(f.startswith("release_digest_mismatch:") for f in findings), findings


def test_tampered_manifest_refuses_index_generation(tmp_path: Path) -> None:
    """H2: the index never serves tampered bytes under a signed-valid label."""
    import subprocess
    import sys as _sys

    sandbox = _sandbox_repo(tmp_path)
    mpath = sandbox / RELEASE / "manifest.json"
    manifest = json.loads(mpath.read_bytes())
    manifest["permissions"] = ["network_egress"]
    mpath.write_bytes(vr.canonical_bytes(manifest))
    result = subprocess.run(
        [_sys.executable, str(sandbox / "scripts" / "generate_index.py"),
         "--root", str(sandbox)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "manifest_reconciliation_failed" in result.stderr


def test_ghost_release_claiming_another_version_refuses(tmp_path: Path) -> None:
    """M3: identity comes from the path; a ghost at 0.9.0 claiming 0.1.0
    refuses (validate AND index)."""
    import subprocess
    import sys as _sys

    sandbox = _sandbox_repo(tmp_path)
    ghost = sandbox / "releases/benchweave-registry/madeinoz67/dps150/0.9.0"
    ghost.mkdir(parents=True)
    real = json.loads((sandbox / RELEASE / "manifest.json").read_bytes())
    real.pop("review", None)
    for name in ("submission-manifest.json", "payload.zip", "manifest.sig"):
        source = sandbox / RELEASE / name
        if source.is_file():
            (ghost / name).write_bytes(source.read_bytes())
    (ghost / "manifest.json").write_bytes(vr.canonical_bytes(real))
    findings = vr.validate_tree(sandbox)
    assert any(f.startswith("release_identity_mismatch:") for f in findings), findings
    result = subprocess.run(
        [_sys.executable, str(sandbox / "scripts" / "generate_index.py"),
         "--root", str(sandbox)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "index_identity_mismatch" in result.stderr


def test_duplicate_release_rows_refuse(tmp_path: Path) -> None:
    """M3: the same identity at two paths cannot both serve rows."""
    import subprocess
    import sys as _sys

    sandbox = _sandbox_repo(tmp_path)
    twin = sandbox / "releases/benchweave-registry/madeinoz67/dps150/0.1.0-copy"
    twin.mkdir(parents=True)
    for name in ("manifest.json", "submission-manifest.json", "payload.zip"):
        source = sandbox / RELEASE / name
        if source.is_file():
            (twin / name).write_bytes(source.read_bytes())
    # A twin whose manifest agrees with its own path is impossible without
    # changing the version; the copy carries 0.1.0 at a 0.1.0-copy path ->
    # identity mismatch fires first. For the pure duplicate arm, copy the
    # whole 0.1.0 dir under a second registry id instead.
    twin2 = sandbox / "releases/mirror-registry/madeinoz67/dps150/0.1.0"
    twin2.mkdir(parents=True)
    for name in ("manifest.json", "submission-manifest.json", "payload.zip"):
        source = sandbox / RELEASE / name
        if source.is_file():
            (twin2 / name).write_bytes(source.read_bytes())
    result = subprocess.run(
        [_sys.executable, str(sandbox / "scripts" / "generate_index.py"),
         "--root", str(sandbox)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 1
    assert "index_duplicate_row" in result.stderr


def test_traversal_shaped_release_dir_refuses(tmp_path: Path) -> None:
    """L2 read side: a traversal-shaped directory under releases/ refuses."""
    sandbox = _sandbox_repo(tmp_path)
    # rglob never yields a path with .. in parts (it resolves), so the honest
    # arm is a directory whose NAME fails the segment shape.
    evil = sandbox / "releases/benchweave-registry/BAD..SEG/x/1.0.0"
    evil.mkdir(parents=True)
    (evil / "manifest.json").write_bytes(b"{}")
    findings = vr.validate_tree(sandbox)
    assert any(f.startswith("release_path_unsafe:") for f in findings), findings

# --- fold F6 (2026-10-02, lane A F4): publisher identity uniqueness ------------


def test_duplicate_publisher_ids_refuse(tmp_path: Path) -> None:
    """F6: publishers.json keyed two entries under one publisher_id — every
    consumer (the page generator's join, verify's key map) silently keeps
    the LAST entry; the validity gate refuses the duplicate, naming the
    id. The control is the real single-publisher tree, which every
    tree_with-based arm already proves green."""
    publishers_path = tmp_path / "records" / "publishers.json"
    publishers_path.parent.mkdir(parents=True)
    base = json.loads((REPO / "records" / "publishers.json").read_bytes())
    duplicate = copy.deepcopy(base)
    duplicate["publishers"].append(copy.deepcopy(base["publishers"][0]))
    publishers_path.write_bytes(vr.canonical_bytes(duplicate))
    findings = vr.validate_tree(tmp_path)
    assert any(f.startswith("publisher_id_duplicate:") for f in findings), findings


def test_distinct_publisher_ids_still_pass(tmp_path: Path) -> None:
    """F6 control: two DISTINCT publisher entries stay green."""
    publishers_path = tmp_path / "records" / "publishers.json"
    publishers_path.parent.mkdir(parents=True)
    base = json.loads((REPO / "records" / "publishers.json").read_bytes())
    second = copy.deepcopy(base["publishers"][0])
    second["publisher_id"] = "quarrystone-labs"
    second["namespace"] = "quarrystone-labs"
    document = {"publishers_version": 1, "publishers": [base["publishers"][0], second]}
    publishers_path.write_bytes(vr.canonical_bytes(document))
    findings = vr.validate_tree(tmp_path)
    assert not any(f.startswith("publisher_id_duplicate:") for f in findings), findings


# --- fold R2/R5 (2026-10-02 round-2 refute) ------------------------------------


def _yank_record() -> dict[str, Any]:
    # Schema 1.1.0 (issue #225 slice 3): a yank record carries the release
    # digest it governs and the status sequence it corresponds to - the
    # pre-slice-3 shape is deliberately unrepresentable now.
    return {
        "record_type": "lifecycle",
        "record_version": "1.1.0",
        "kind": "admitted-release",
        "created_at": "2026-10-02T00:00:00Z",
        "actor": "madeinoz67",
        "lifecycle": {
            "op": "yank",
            "publisher": "madeinoz67",
            "plugin": "dps150",
            "version": "0.1.0",
            "reason": "synthetic yank for the coherence arm",
            "release_manifest_sha256": "d" * 64,
            "status_sequence": 2,
        },
    }


def _yank_tree_with(root: Path, status: dict[str, Any] | None) -> Path:
    """A release tree plus a canonical yank record; ``status`` plants the
    release's status.json when given (the plants carry the lifecycle and the
    sequence — the slice-3 pairing reads both)."""
    manifest_path = _mini_release(root, [], None)
    yank_dir = root / "records" / "lifecycle" / "madeinoz67" / "dps150" / "0.1.0"
    yank_dir.mkdir(parents=True, exist_ok=True)
    (yank_dir / "2-yank.json").write_bytes(vr.canonical_bytes(_yank_record()))
    # Fold rows 3+8: a tree with records must carry its authorities.
    repo = Path(__file__).resolve().parents[1]
    (root / "records" / "publishers.json").write_bytes(
        (repo / "records" / "publishers.json").read_bytes()
    )
    for name in ("lane-rules.json", "vetting-checklist.md"):
        (root / name).write_bytes((repo / name).read_bytes())
    if status is not None:
        planted = dict(status)
        planted.setdefault("sequence", 2)
        (manifest_path.parent / "status.json").write_bytes(vr.canonical_bytes(planted))
    return root


def test_yank_record_without_a_status_document_is_refused(tmp_path: Path) -> None:
    """R2 (lane A F2): records.schema.json admits op:yank, but nothing
    consumed the record — a canonical yank with no governing status.json was
    silently inert with every gate green. The coherence rule refuses loudly;
    status.json stays the single catalogue authority (Q8) and the generator
    still honours only status documents, never yank records."""
    _yank_tree_with(tmp_path, None)
    findings = vr.validate_tree(tmp_path)
    assert any(f.startswith("yank_status_absent:") for f in findings), findings


def test_yank_record_with_a_published_status_document_is_refused(tmp_path: Path) -> None:
    """R2's second arm: a status document whose lifecycle is not
    yanked-or-revoked does not govern the yank."""
    _yank_tree_with(tmp_path, {"lifecycle": "published"})
    findings = vr.validate_tree(tmp_path)
    assert any(f.startswith("yank_status_absent:") for f in findings), findings


def test_yank_record_with_a_yanked_status_document_passes(tmp_path: Path) -> None:
    """R2 control: the coherent shape — the yank record and the status
    document that makes it true — stays green."""
    _yank_tree_with(tmp_path, {"lifecycle": "yanked"})
    assert vr.validate_tree(tmp_path) == []


def test_cli_root_flag_routes_to_the_given_tree(tmp_path: Path) -> None:
    """R5 (lane A F4): ``--root`` actually routes. The pre-fold CLI ignored
    the flag entirely and validated its own tree — exit 0 reporting the
    REPO's record count, a silent lie this arm pins shut."""
    import subprocess
    import sys as _sys

    empty = tmp_path / "empty"
    empty.mkdir()
    result = subprocess.run(
        [_sys.executable, str(REPO / "scripts" / "validate_records.py"),
         "--root", str(empty)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "0 records valid" in result.stdout, (
        f"--root did not route (the validator reported its own tree): {result.stdout!r}"
    )


def test_cli_refuses_unknown_arguments(tmp_path: Path) -> None:
    """R5's second arm: unknown arguments refuse (argparse exit 2) instead
    of being silently ignored."""
    import subprocess
    import sys as _sys

    result = subprocess.run(
        [_sys.executable, str(REPO / "scripts" / "validate_records.py"),
         "--frobnicate", "1"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2, (
        f"unknown arguments must refuse with argparse's exit 2, got "
        f"{result.returncode}: {result.stdout + result.stderr}"
    )

