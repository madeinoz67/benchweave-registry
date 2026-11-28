"""Issue #227 slice-5 arms: community-shared listings (CR-56, CR-57, Q20).

author: Stephen Eaton

RED-first: each arm was written and RUN against the pre-change bytes before
the mechanism it pins landed (per-commit, in-history). The tree every arm
mutates is built by ``tests/issue227_tree.py``: gate-valid as built, so a
control arm is green only because the tree is right and a mutant reddens for
the planted reason.

Acceptance map (design record section 4, slice 5):

- E1 kind: the record shape and the kind-tag coherence at write time;
- E4 takedown: the recorded takedown of a shared listing (this file's gate
  half; the generator half lives in ``tests/test_generate_index.py``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import validate_records as vr
from issue227_tree import (
    ADMITTED,
    FIXTURE,
    REVISION,
    SHARED,
    UNLISTED,
    Key,
    ThreeKindTree,
    lifecycle_record,
    package_id,
    plant_bare_release,
    review_record,
    share_record,
    takedown_record,
    three_kind_tree,
    with_lifecycle,
    with_shared,
    with_top,
    write_record,
    write_review,
)

REPO = Path(__file__).resolve().parents[1]

#: CR-57's carried set, as the ``lifecycle.shared`` members.
CARRIED_SET = (
    "display_name",
    "summary",
    "source",
    "licence_spdx",
    "compatibility",
    "capabilities",
)

#: The shared listing's declared source repository (invented).
SOURCE_URL = "https://github.com/harborline-example/anchor-meter"


def _tree(tmp_path: Path, **kwargs: Any) -> ThreeKindTree:
    return three_kind_tree(tmp_path / "repo", **kwargs)


def _rewrite(path: Path, record: dict[str, Any]) -> None:
    path.write_bytes(vr.canonical_bytes(record))


def _record_findings(record: dict[str, Any]) -> list[str]:
    findings, _parsed = vr.validate_record(vr.canonical_bytes(record), Path("x.json"))
    return findings


def _shared_kind_plant(tree: ThreeKindTree, plant: str) -> Path:
    """Carry ``community-shared`` on a record class that is not a listing;
    returns the planted record's path."""
    if plant == "review":
        return write_review(tree.root, review_record(UNLISTED, kind="community-shared"))
    if plant == "publish":
        path = tree.publish_path()
        _rewrite(path, with_top(tree.read_record(path), kind="community-shared"))
        return path
    return write_record(tree.root, lifecycle_record(plant, ADMITTED, kind="community-shared"))


# ── the builder's own integrity (a broken fixture tree proves nothing) ───────


def test_the_tree_is_gate_valid_and_complete_without_the_listing(tmp_path: Path) -> None:
    """PIN (green at base): the two releases alone are gate-valid, so every
    refusal below is the listing's doing. The admitted release is signed; the
    fixture release is not."""
    tree = _tree(tmp_path)
    tree.share_record_path().unlink()
    assert vr.validate_tree(tree.root) == []
    admitted = tree.release_dir(ADMITTED)
    assert sorted(p.name for p in admitted.iterdir()) == [
        "manifest.json",
        "manifest.sig",
        "payload.zip",
        "submission-manifest.json",
    ]
    assert not (tree.release_dir(FIXTURE) / "manifest.sig").exists()
    assert tree.publish_path().is_file() and tree.publish_path(FIXTURE).is_file()


# ── the control: a valid shared listing passes the gate ───────────────────────


def test_a_valid_share_record_passes_the_gate(tmp_path: Path) -> None:
    """CR-57: a vetted publisher shares a standalone plugin as ONE lifecycle
    record and the records-validity gate accepts the tree."""
    tree = _tree(tmp_path)
    assert vr.validate_tree(tree.root) == []


def test_the_share_record_is_the_cr57_shape(tmp_path: Path) -> None:
    """The record carries publisher identity, a pinned immutable source ref,
    licence, declared compatibility and the capability declaration — every
    value author-declared, under ``lifecycle.shared``."""
    tree = _tree(tmp_path)
    record = tree.read_record(tree.share_record_path())
    assert record["kind"] == "community-shared"
    assert record["record_type"] == "lifecycle"
    assert record["actor"] == SHARED[0]
    assert record["lifecycle"]["op"] == "share"
    assert (record["lifecycle"]["publisher"], record["lifecycle"]["plugin"]) == SHARED[:2]
    shared = record["lifecycle"]["shared"]
    assert set(shared) == set(CARRIED_SET)
    assert shared["source"] == {"url": SOURCE_URL, "revision": REVISION}
    assert vr.validate_tree(tree.root) == []


# ── schema: the share op and its carried set (CR-57) ─────────────────────────


@pytest.mark.parametrize("member", CARRIED_SET)
def test_share_without_a_carried_member_is_refused(member: str) -> None:
    """Each carried member is REQUIRED on a share record; the refusal names it."""
    record = with_shared(share_record(), **{member: None})
    assert member not in record["lifecycle"]["shared"]
    findings = _record_findings(record)
    assert any("record_schema_invalid" in f and member in f for f in findings), findings


def test_a_share_record_without_the_shared_block_is_refused() -> None:
    record = with_lifecycle(share_record(), shared=None)
    assert "shared" not in record["lifecycle"]
    findings = _record_findings(record)
    assert any("record_schema_invalid" in f and "shared" in f for f in findings), findings


def test_the_shared_block_takes_no_undeclared_member() -> None:
    """Author-declared content is a closed set: a hand-added member refuses,
    so nothing rides a listing the catalogue does not render honestly."""
    record = with_shared(share_record(), evidence=[{"level": "hardware", "result": "passed"}])
    findings = _record_findings(record)
    assert any("record_schema_invalid" in f and "evidence" in f for f in findings), findings


def test_a_share_record_without_a_kind_is_refused() -> None:
    """CR-56 at write time. PIN: the base already enforces this through the
    schema's required list (tests/test_validate_records.py proves it on a
    review record); this arm extends the pin to the share op."""
    findings = _record_findings(with_top(share_record(), kind=None))
    assert any("record_schema_invalid" in f and "kind" in f for f in findings), findings


SOURCE_URL = "https://github.com/harborline-example/anchor-meter"


@pytest.mark.parametrize("revision", ["main", "master", "HEAD", "v1", "abc123", "1.2.0"])
def test_share_pins_an_immutable_source_revision(revision: str) -> None:
    """CR-36 at the listing: a moving name is not a pinned source ref."""
    record = with_shared(share_record(), source={"url": SOURCE_URL, "revision": revision})
    findings = _record_findings(record)
    assert any(
        "record_schema_invalid" in f and "source" in f and "revision" in f for f in findings
    ), findings


@pytest.mark.parametrize("revision", ["a" * 40, "b" * 64])
def test_share_accepts_a_commit_digest_as_the_source_revision(revision: str) -> None:
    """Control arm: both immutable forms lane-rules.json names pass."""
    record = with_shared(share_record(), source={"url": SOURCE_URL, "revision": revision})
    assert _record_findings(record) == []


def test_the_listing_source_revision_rule_is_the_review_rule() -> None:
    """One rule for the lane: the share record's source-revision pattern is
    byte-equal to the review record's (never a second hand list)."""
    schema = json.loads((REPO / "records" / "records.schema.json").read_bytes())
    properties = schema["properties"]
    review_pattern = properties["review"]["properties"]["source_revision"]["pattern"]
    shared_source = properties["lifecycle"]["properties"]["shared"]["properties"]["source"]
    assert shared_source["properties"]["revision"]["pattern"] == review_pattern


@pytest.mark.parametrize(
    "url",
    ["http://example.invalid/anchor-meter", "ftp://x/y", "javascript:alert(1)"],
)
def test_share_source_url_must_be_https(url: str) -> None:
    """The pinned-source link the page renders comes from this value: a
    non-https scheme never reaches a record (the advisory url rule's twin)."""
    record = with_shared(share_record(), source={"url": url, "revision": REVISION})
    findings = _record_findings(record)
    assert any("record_schema_invalid" in f and "source" in f and "url" in f for f in findings), (
        findings
    )


@pytest.mark.parametrize("family", ["otdp_versions", "stg_versions"])
def test_share_declares_at_least_one_version_per_required_family(family: str) -> None:
    """``declared compatibility`` means declared: the two families the release
    manifest requires are required here too (the index renders them verbatim)."""
    record = share_record()
    record["lifecycle"]["shared"]["compatibility"][family] = []
    findings = _record_findings(record)
    assert any("record_schema_invalid" in f and family in f for f in findings), findings


def test_share_takes_a_closed_capability_declaration() -> None:
    """CR-45's three-way enumeration binds a listing the way it binds a
    package: all three members, no other."""
    incomplete = with_shared(
        share_record(),
        capabilities={"network_egress": True, "subprocess_or_native_library": False},
    )
    findings = _record_findings(incomplete)
    assert any(
        "record_schema_invalid" in f and "filesystem_writes_beyond_evidence_retention" in f
        for f in findings
    ), findings
    extra = share_record()
    extra["lifecycle"]["shared"]["capabilities"]["device_io"] = True
    findings = _record_findings(extra)
    assert any("record_schema_invalid" in f and "device_io" in f for f in findings), findings


# ── kind coherence at write time (CR-56, CR-57) ──────────────────────────────


def test_the_share_op_takes_only_the_community_shared_kind(tmp_path: Path) -> None:
    """A share record is a shared listing by definition; any other kind tag
    on it is a lie the catalogue would render."""
    tree = _tree(tmp_path)
    _rewrite(tree.share_record_path(), with_top(share_record(), kind="admitted-release"))
    findings = vr.validate_tree(tree.root)
    assert any(f.startswith("record_kind_mismatch:1-share.json") for f in findings), findings


@pytest.mark.parametrize("plant", ["review", "publish", "unlist"])
def test_the_shared_kind_is_legal_only_on_share_and_takedown(tmp_path: Path, plant: str) -> None:
    """Sharing is not an admission path: a review, publish or unlist record
    can never carry ``community-shared``. DISCRIMINATING AT BASE: the base
    gate accepted every one of these plants."""
    tree = _tree(tmp_path)
    planted = _shared_kind_plant(tree, plant).name
    findings = vr.validate_tree(tree.root)
    assert any(f.startswith(f"record_kind_mismatch:{planted}") for f in findings), findings


# ── who may share, and under what name ───────────────────────────────────────


def test_an_unvetted_publisher_cannot_share(tmp_path: Path) -> None:
    """Q20: any VETTED publisher may share. PIN: the base's records-side
    vetting arm already reaches every lifecycle record; this arm pins it on
    the share op."""
    tree = _tree(tmp_path)
    rogue: Key = ("copperleaf-labs", "copperleaf-daq", "1.0.0")
    write_record(tree.root, share_record(rogue))
    findings = vr.validate_tree(tree.root)
    assert any(f.startswith("publisher_unvetted:") and "copperleaf-labs" in f for f in findings), (
        findings
    )


def test_a_reserved_plugin_name_cannot_be_shared(tmp_path: Path) -> None:
    """CR-16's records half reaches the share op. PIN (existing arm)."""
    tree = _tree(tmp_path)
    reserved: Key = (SHARED[0], "sim-psu", "1.0.0")
    write_record(tree.root, share_record(reserved))
    findings = vr.validate_tree(tree.root)
    assert any(f.startswith("namespace_reserved:") and "sim-psu" in f for f in findings), findings


# ── a listing owns its identity (one subject, one kind) ──────────────────────


def test_a_shared_listing_never_shares_an_identity_with_a_release(tmp_path: Path) -> None:
    """A release and a shared listing at one (publisher, plugin, version)
    would be two catalogue rows under one identity."""
    tree = _tree(tmp_path)
    plant_bare_release(tree.root, SHARED)
    findings = vr.validate_tree(tree.root)
    assert any(f.startswith("shared_listing_conflict:1-share.json") for f in findings), findings


def test_a_shared_listing_never_shares_an_identity_with_a_reviewed_submission(
    tmp_path: Path,
) -> None:
    """A reviewed submission at the listing's key is another kind of entry
    under the same identity."""
    tree = _tree(tmp_path)
    write_review(tree.root, review_record(SHARED))
    findings = vr.validate_tree(tree.root)
    assert any(f.startswith("shared_listing_conflict:1-share.json") for f in findings), findings


def test_one_share_record_per_listing(tmp_path: Path) -> None:
    """A listing is amended by history, never by a second share record at the
    same key: the catalogue reads exactly one record per shared row."""
    tree = _tree(tmp_path)
    extra = write_record(tree.root, with_shared(share_record(), display_name="Anchor meter, again"))
    assert extra.name == "2-share.json"
    findings = vr.validate_tree(tree.root)
    assert any(f.startswith("shared_listing_duplicate:2-share.json") for f in findings), findings


# ── the recorded takedown (Q20, CR-28) ───────────────────────────────────────


def test_takedown_unlists_a_shared_listing_and_is_recorded(tmp_path: Path) -> None:
    """E4, gate half: the takedown is a lifecycle record carrying actor,
    reason and timestamp, and the tree stays coherent with it."""
    tree = _tree(tmp_path)
    path = write_record(tree.root, takedown_record())
    assert path.name == "2-takedown.json"
    record = tree.read_record(path)
    assert record["actor"] == "madeinoz67"
    assert record["created_at"] == "2026-11-27T00:00:00Z"
    assert record["kind"] == "community-shared"
    assert record["lifecycle"]["reason"].startswith("takedown requested")
    assert vr.validate_tree(tree.root) == []


@pytest.mark.parametrize("record_version", ["1.1.0", "1.2.0"])
def test_a_takedown_with_no_listing_to_unlist_refuses(tmp_path: Path, record_version: str) -> None:
    """The inert-record rule reaches the shared takedown: there must be a
    listing to take down. The 1.1.0 arm is DISCRIMINATING AT BASE — the base
    gate accepted it (nothing checked a takedown's subject)."""
    tree = _tree(tmp_path)
    write_record(tree.root, with_top(takedown_record(UNLISTED), record_version=record_version))
    findings = vr.validate_tree(tree.root)
    assert any(
        f.startswith("record_subject_absent:1-takedown.json")
        and package_id(UNLISTED) in f
        and "shared listing" in f
        for f in findings
    ), findings


def test_a_takedown_in_another_kind_at_a_listing_key_refuses(tmp_path: Path) -> None:
    """A release-class takedown record parked on a shared listing's key is a
    foreign record there: a listing's history holds only shared-kind share
    and takedown records."""
    tree = _tree(tmp_path)
    write_record(tree.root, lifecycle_record("takedown", SHARED, kind="admitted-release"))
    findings = vr.validate_tree(tree.root)
    assert any(f.startswith("shared_listing_conflict:1-share.json") for f in findings), findings


def test_a_taken_down_listing_is_not_shared_again(tmp_path: Path) -> None:
    """A takedown is terminal for its key. The listing comes back only as a
    new version, so a third record cannot re-list what was taken down."""
    tree = _tree(tmp_path)
    write_record(tree.root, takedown_record())
    path = write_record(tree.root, share_record())
    assert path.name == "3-share.json"
    findings = vr.validate_tree(tree.root)
    assert any(f.startswith("shared_listing_duplicate:3-share.json") for f in findings), findings


def test_an_admitted_takedown_keeps_its_status_governed_reading(tmp_path: Path) -> None:
    """Scope guard (PIN): a release-class takedown — the slice-3 shape, kind
    ``admitted-release`` over a revoked status document — is untouched by the
    shared-listing rules; it stays the status-governed record it was."""
    tree = _tree(tmp_path)
    release = tree.release_dir(ADMITTED)
    manifest_digest = vr.sha256_hex((release / "manifest.json").read_bytes())
    status = {
        "advisories": [],
        "lifecycle": "revoked",
        "reason": "fixture revocation for the scope guard",
        "release": {
            "manifest_sha256": manifest_digest,
            "package_id": package_id(ADMITTED),
            "registry_id": "benchweave-registry",
            "version": ADMITTED[2],
        },
        "sequence": 2,
        "status_version": "0.1.1",
    }
    (release / "status.json").write_bytes(vr.canonical_bytes(status))
    record = lifecycle_record("takedown", ADMITTED)
    record["record_version"] = "1.0.0"
    record["lifecycle"]["reason"] = "release-class takedown over the revoked status"
    write_record(tree.root, record)
    assert vr.validate_tree(tree.root) == []


def test_the_shared_listing_leaves_the_release_records_untouched(tmp_path: Path) -> None:
    """CR-13's kin: a listing beside two releases changes nothing about them —
    the gate reads the same tree it read without the listing."""
    tree = _tree(tmp_path)
    with_listing = vr.validate_tree(tree.root)
    tree.share_record_path().unlink()
    assert vr.validate_tree(tree.root) == with_listing == []


def test_the_fixture_set_carries_all_three_kinds(tmp_path: Path) -> None:
    """E1's denominator: the arms' tree holds one entry of each kind."""
    tree = _tree(tmp_path)
    kinds = {
        tree.read_record(tree.publish_path())["kind"],
        tree.read_record(tree.publish_path(FIXTURE))["kind"],
        tree.read_record(tree.share_record_path())["kind"],
    }
    assert kinds == {"admitted-release", "in-tree-fixture", "community-shared"}
    assert vr.validate_tree(tree.root) == []
