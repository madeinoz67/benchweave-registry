"""The index format and its regeneration discipline (CR-21, Q7/CR-26).

The index is generated, never hand-edited: a records change without
regeneration refuses, and a hand-edited row refuses the same way. The format
test pins the row shape the website slice will render — additive consumption,
never a reshape.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
GENERATOR = REPO / "scripts" / "generate_index.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GENERATOR), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )


def test_index_is_committed_and_current() -> None:
    assert (REPO / "index.json").is_file()
    result = _run("--check")
    assert result.returncode == 0, result.stderr


def test_generation_is_byte_reproducible() -> None:
    first = _run("--root", str(REPO))
    assert first.returncode == 0, first.stderr
    committed = (REPO / "index.json").read_bytes()
    second = subprocess.run(
        [sys.executable, "-c",
         f"import sys; sys.path.insert(0, {str(REPO / 'scripts')!r}); "
         f"from generate_index import generate; "
         f"sys.stdout.buffer.write(generate(__import__('pathlib').Path({str(REPO)!r})))"],
        capture_output=True,
        check=False,
    )
    assert second.returncode == 0, second.stderr
    assert second.stdout == committed


def test_hand_edited_index_row_refuses(tmp_path: Path) -> None:
    """CR-21's falsifier: drift between the trees and the committed index refuses."""
    import shutil

    sandbox = tmp_path / "repo"
    shutil.copytree(REPO, sandbox, ignore=shutil.ignore_patterns("venv", ".git"))
    index = json.loads((sandbox / "index.json").read_bytes())
    assert index["rows"], "the dogfooded release must seed the index"
    index["rows"][0]["summary"] = "hand-edited summary"
    (sandbox / "index.json").write_bytes(
        json.dumps(index, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check", "--root", str(sandbox)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "index_drift" in result.stderr


def test_row_carries_the_catalogue_and_styleguide_fields() -> None:
    """The format is forward-complete for the website slice's rendering."""
    index = json.loads((REPO / "index.json").read_bytes())
    row = index["rows"][0]
    for field in (
        "kind",
        "publisher",
        "manifest_sha256",
        "signature_state",
        "display_name",
        "summary",
        "licence_spdx",
        "compatibility",
        "evidence",
        "maintenance",
        "advisories",
        "capabilities",
        "transport_triples",
        "source_revision",
        "unverified_markers",
    ):
        assert field in row, field
    assert row["kind"] == "admitted-release"
    assert row["signature_state"] == "signed-valid"
    assert row["timestamp"] is None
    assert row["timestamp_recommended"] is True
    assert "conformance-evidence-self-attested" in row["unverified_markers"]
    # F1 rework: the pin is advertised, never enforced.
    assert row["gateway_ref"] == "45d5e7fdc45dc6bbf765b1c8e85af70a2d830d94"
    assert row["firmware_attestation"] is None


def test_index_schema_validates_the_committed_index() -> None:
    import jsonschema

    schema = json.loads((REPO / "records" / "index.schema.json").read_bytes())
    index = json.loads((REPO / "index.json").read_bytes())
    jsonschema.Draft202012Validator(schema).validate(index)


# ── the yank arm (issue #224 slice 2, CR-25) ─────────────────────────────────
#
# A release directory carrying status.json with lifecycle yanked or revoked
# drops out of the generated index at regeneration — "no stale rows survive a
# yank or unlist" (CR-25); the record and git history retain it (CR-32's
# floor is history, not the catalogue). status.json is the single authority
# for this read (the same origin state file stock gateways consult, Q8).
# Absent status.json or lifecycle published|deprecated -> row present
# (today's dogfood, unchanged). Zero format motion: the row shape is
# untouched; only which rows exist moves.


def _fixture_release(
    root: Path,
    plugin: str = "alpha-tool",
    *,
    status: dict[str, object] | None = None,
    version: str = "1.0.0",
) -> Path:
    """A minimal release tree for the generator (invented names only)."""
    release = (
        root / "releases" / "benchweave-registry" / "northwind-instruments" / plugin / version
    )
    release.mkdir(parents=True)
    manifest = {
        "registry_id": "benchweave-registry",
        "package_id": f"northwind-instruments/{plugin}",
        "version": version,
        "publisher_id": "northwind-instruments",
        "display_name": f"Northwind {plugin}",
        "summary": "Synthetic fixture release for the catalogue yank arm.",
        "licence": {"spdx_expression": "MIT"},
        "compatibility": {
            "otdp_versions": ["0.2.2"],
            "adapter_api_versions": ["1.1"],
            "stg_versions": ["1.5"],
        },
        "evidence": [
            {"level": "simulated", "report_path": "evidence/report.md", "result": "passed"}
        ],
        "source": {"revision": "0" * 40},
    }
    (release / "manifest.json").write_bytes(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    if status is not None:
        # Fold R1: every planted status document carries the BOUND release
        # block (the directory's identity + the manifest digest on disk), so
        # the plants are documents the vendored schema admits and the arms
        # exercise what they name — lifecycle polarity, drift, advisories —
        # never an accidental binding refusal.
        bound = dict(status)
        bound["release"] = _bound_release_block(release, plugin, version)
        (release / "status.json").write_bytes(_canon(bound))
    return release


def _bound_release_block(release: Path, plugin: str, version: str) -> dict[str, str]:
    """The release block R1 binds every status document to: the directory's
    own identity plus the manifest digest actually on disk."""
    manifest_digest = hashlib.sha256((release / "manifest.json").read_bytes()).hexdigest()
    return {
        "registry_id": "benchweave-registry",
        "package_id": f"northwind-instruments/{plugin}",
        "version": version,
        "manifest_sha256": manifest_digest,
    }


def _canon(obj: object) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _row_ids(root: Path) -> list[str]:
    result = _run("--root", str(root))
    assert result.returncode == 0, result.stderr
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    return [row["package_id"] for row in index["rows"]]


def _rows(root: Path) -> list[dict[str, Any]]:
    _row_ids(root)
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = index["rows"]
    return rows


def test_absent_status_keeps_the_row(tmp_path: Path) -> None:
    """Today's dogfood shape is unchanged: no status document, row present."""
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(root)
    assert _row_ids(root) == ["northwind-instruments/alpha-tool"]


def test_published_status_keeps_the_row(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(root, status={"lifecycle": "published"})
    assert _row_ids(root) == ["northwind-instruments/alpha-tool"]


def test_deprecated_status_keeps_the_row(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(root, status={"lifecycle": "deprecated"})
    assert _row_ids(root) == ["northwind-instruments/alpha-tool"]


def test_yanked_release_drops_the_row(tmp_path: Path) -> None:
    """B1's yank arm, generator half: a yanked release is gone from the
    index at the next refresh — discovery must not offer what admission
    already refuses (CR-25)."""
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(root, status={"lifecycle": "yanked"})
    assert _row_ids(root) == []


def test_revoked_release_drops_the_row(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(root, status={"lifecycle": "revoked"})
    assert _row_ids(root) == []


def test_one_yanked_release_does_not_drop_the_others(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(root, plugin="alpha-tool", status={"lifecycle": "yanked"})
    _fixture_release(root, plugin="beta-tool")
    assert _row_ids(root) == ["northwind-instruments/beta-tool"]


def test_advisories_from_the_status_document_surface_in_the_row(tmp_path: Path) -> None:
    """The status document is the single authority for advisories too
    (Q8's origin status/lifecycle file): advisory ids reach the row the
    catalogue renders."""
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(
        root,
        status={
            "lifecycle": "published",
            "advisories": [
                {
                    "id": "BW-ADV-001",
                    "severity": "medium",
                    "summary": "Synthetic advisory for the yank-arm fixture.",
                    "url": "https://example.invalid/advisories/BW-ADV-001",
                }
            ],
        },
    )
    assert _rows(root)[0]["advisories"] == ["BW-ADV-001"]


def test_records_edit_without_regeneration_refuses(tmp_path: Path) -> None:
    """B2 plant 1 (re-proven on this slice's fixture trees): a status change
    without index regeneration reddens --check — the CR-21 falsifier."""
    root = tmp_path / "repo"
    root.mkdir()
    release = _fixture_release(root)
    first = _run("--root", str(root))
    assert first.returncode == 0, first.stderr
    yanked: dict[str, object] = {"lifecycle": "yanked"}
    yanked["release"] = _bound_release_block(release, "alpha-tool", "1.0.0")
    (release / "status.json").write_bytes(_canon(yanked))
    check = _run("--check", "--root", str(root))
    assert check.returncode == 1, check.stdout + check.stderr
    assert "index_drift" in check.stderr


def test_a_submitted_not_accepted_submission_produces_no_index_row(tmp_path: Path) -> None:
    """B3's generator arm (CR-22): a submission that has not been accepted
    and published is structurally absent from the catalogue — the index is
    generated from releases/ only, and a submission becomes a release at
    publish. The control arm (the same package WITH a release) proves the
    test is not vacuous: the generator can and does produce rows."""
    root = tmp_path / "repo"
    submission = (
        root / "records" / "submissions" / "northwind-instruments" / "gamma-tool" / "1.0.0"
    )
    submission.mkdir(parents=True)
    (submission / "review-1.json").write_text(
        json.dumps({"record_type": "review"}), encoding="utf-8"
    )
    assert _row_ids(root) == [], "a submission without a release must not index"

    # control: the same package, now published (a release directory exists)
    _fixture_release(root, plugin="gamma-tool")
    assert _row_ids(root) == ["northwind-instruments/gamma-tool"]


# ── the yank arm, hardened (issue #224 slice-2 pivot, §3.2) ───────────────────
#
# The 11-value boundary matrix the refute lanes executed as repros, as a
# standing arm: out-of-enum lifecycle REFUSES (fail-closed polarity — the
# pre-pivot generator kept the row, the exact HIGH the lanes flagged);
# malformed or non-object status refuses with a TYPED prefix (no bare
# tracebacks); enum values keep their settled polarity (yanked/revoked drop
# the row; published/deprecated/absent keep it). The enum itself is the
# vendored schema's, never a hand list. Two arms beyond the named eleven
# are disclosed in place.


def _status_bytes(case: str, release: Path) -> bytes | None:
    """The status.json bytes for a matrix row (None = no file). Every
    parseable row carries the BOUND release block (fold R1) so the matrix
    exercises the lifecycle polarity, not the binding refusal — the binding
    has its own arms below."""
    if case == "absent":
        return None
    if case == "malformed":
        return b"not json at all"
    if case == "non-object":
        return b'["yanked"]'
    # Beyond the named eleven: a present status document whose lifecycle key
    # is missing. Fail-closed here too — a present-but-unreadable lifecycle
    # is not an absent one (the validity step owns the schema shape; the
    # generator refuses rather than guessing benign).
    doc: dict[str, object]
    if case == "key-absent":
        doc = {"reason": "lifecycle key absent"}
    elif case == "null":
        doc = {"lifecycle": None}
    elif case == "array":
        doc = {"lifecycle": ["yanked"]}
    else:
        doc = {"lifecycle": case}
    doc["release"] = _bound_release_block(release, "alpha-tool", "1.0.0")
    return _canon(doc)


@pytest.mark.parametrize(
    ("case", "polarity"),
    [
        # the settled rows (existing behaviour, now pinned by the matrix)
        ("yanked", "drop"),
        ("revoked", "drop"),
        ("published", "keep"),
        ("deprecated", "keep"),
        ("absent", "keep"),
        # present-but-out-of-enum REFUSES (the polarity flip)
        ("Yanked", "refuse-invalid"),
        ("yank", "refuse-invalid"),
        ("retired", "refuse-invalid"),
        ("null", "refuse-invalid"),
        ("array", "refuse-invalid"),
        ("key-absent", "refuse-invalid"),
        # unparseable authority refuses with a typed prefix
        ("malformed", "refuse-unparseable"),
        ("non-object", "refuse-unparseable"),
    ],
)
def test_status_boundary_matrix(case: str, polarity: str, tmp_path: Path) -> None:
    """The fail-closed polarity per row, exactly as the design record §3.2
    names it: `index_status_invalid: <value>` for a present lifecycle
    outside the enum; `index_status_unparseable:` for a status document
    that is not parseable JSON or not an object; the row kept for an
    absent document (today's dogfood, unchanged); the row dropped for
    yanked/revoked (CR-25)."""
    root = tmp_path / "repo"
    root.mkdir()
    release = _fixture_release(root)
    status_bytes = _status_bytes(case, release)
    if status_bytes is not None:
        (release / "status.json").write_bytes(status_bytes)
    result = _run("--root", str(root))
    if polarity == "keep":
        assert result.returncode == 0, result.stdout + result.stderr
        assert _row_ids(root) == ["northwind-instruments/alpha-tool"], case
        return
    if polarity == "drop":
        assert result.returncode == 0, f"{case}: {result.stdout + result.stderr}"
        assert _row_ids(root) == [], case
        return
    assert result.returncode == 1, f"{case}: expected a refusal, generator succeeded"
    stderr = result.stderr
    prefix = "index_status_invalid:" if polarity == "refuse-invalid" else (
        "index_status_unparseable:"
    )
    assert prefix in stderr, f"{case}: refusal lacks {prefix!r}; stderr:\n{stderr}"
    assert "Traceback" not in stderr, f"{case}: bare traceback instead of a typed refusal"


def test_the_enum_is_derived_from_the_vendored_schema() -> None:
    """The generator's lifecycle enum is the vendored release-status
    schema's own enum — one authority, two consumers (the validity step is
    the other). A hand-listed tuple here would be a second constant the
    design record explicitly refuses."""
    sys.path.insert(0, str(REPO / "scripts"))
    try:
        import generate_index
    finally:
        sys.path.remove(str(REPO / "scripts"))
    schema = json.loads(
        (REPO / "vendored" / "gateway" / "release-status.schema.json").read_bytes()
    )
    assert list(generate_index.LIFECYCLE_ENUM) == schema["properties"]["lifecycle"]["enum"]


def test_out_of_enum_status_does_not_take_the_whole_run_down(tmp_path: Path) -> None:
    """A bad status document on ONE release refuses that run loudly, and a
    sibling release with valid state is not silently half-indexed: the
    refusal is terminal (exit 1), never a partial index."""
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(root, plugin="beta-tool")
    bad = _fixture_release(root, plugin="alpha-tool")
    retired: dict[str, object] = {"lifecycle": "retired"}
    retired["release"] = _bound_release_block(bad, "alpha-tool", "1.0.0")
    (bad / "status.json").write_bytes(_canon(retired))
    result = _run("--root", str(root))
    assert result.returncode == 1
    assert "index_status_invalid:'retired'" in result.stderr
    assert "northwind-instruments/alpha-tool" in result.stderr, "the refusal must name the row"
    assert not (root / "index.json").exists(), "a refused run must write no index"


# ── fold R1/R4 (2026-10-02 round-2 refute): bind every status document ────────
#
# R1 (lane A F1, MED): the vendored schema REQUIRES release{registry_id,
# package_id, version, manifest_sha256} on every status document, but nothing
# consumed it — a status.json naming a DIFFERENT release (or pinning another
# release's manifest digest) governed this directory's row with every gate
# green. The binding below makes the generator refuse with the typed prefix
# `index_status_mismatch:`. status.json stays the single catalogue authority
# (Q8); the binding is what ties a document to the release it governs.
#
# R4 (lane A F3, LOW): a present-but-not-regular-file status.json is a typed
# refusal (`index_status_unparseable:`), never a silently-absent one.


def test_status_document_naming_a_different_release_refuses(tmp_path: Path) -> None:
    """R1: the release block is binding, not decoration."""
    root = tmp_path / "repo"
    root.mkdir()
    release = _fixture_release(root)
    status: dict[str, object] = {"lifecycle": "published"}
    status["release"] = _bound_release_block(release, "alpha-tool", "1.0.0")
    assert isinstance(status["release"], dict)
    status["release"]["package_id"] = "northwind-instruments/other-tool"
    (release / "status.json").write_bytes(_canon(status))
    result = _run("--root", str(root))
    assert result.returncode == 1, (
        f"a status document naming another release kept every gate green:\n"
        f"{result.stdout + result.stderr}"
    )
    assert "index_status_mismatch:" in result.stderr, result.stderr
    assert "other-tool" in result.stderr, "the refusal must name the claimed release"


def test_status_document_pinning_a_foreign_manifest_digest_refuses(tmp_path: Path) -> None:
    """R1's second arm: the names agree but the pinned manifest digest is not
    this release's — the document governs bytes that are not on disk."""
    root = tmp_path / "repo"
    root.mkdir()
    release = _fixture_release(root)
    status: dict[str, object] = {"lifecycle": "published"}
    status["release"] = _bound_release_block(release, "alpha-tool", "1.0.0")
    assert isinstance(status["release"], dict)
    status["release"]["manifest_sha256"] = "0" * 64
    (release / "status.json").write_bytes(_canon(status))
    result = _run("--root", str(root))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "index_status_mismatch:" in result.stderr, result.stderr


def test_bound_status_document_governs_its_row(tmp_path: Path) -> None:
    """R1 control arm: a correctly-bound published document keeps the row —
    the binding refuses mismatch, it does not refuse status documents."""
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(root, status={"lifecycle": "published"})
    assert _row_ids(root) == ["northwind-instruments/alpha-tool"]


def test_directory_shaped_status_refuses_instead_of_reading_as_absent(
    tmp_path: Path,
) -> None:
    """R4: `status.json` present as a DIRECTORY is a typed refusal — the
    pre-fold generator's `is_file()` read it as absent and kept the row."""
    root = tmp_path / "repo"
    root.mkdir()
    release = _fixture_release(root)
    (release / "status.json").mkdir()
    result = _run("--root", str(root))
    assert result.returncode == 1, (
        f"a directory-shaped status.json read as absent:\n{result.stdout + result.stderr}"
    )
    assert "index_status_unparseable:" in result.stderr, result.stderr
    assert "Traceback" not in result.stderr, "a bare traceback instead of a typed refusal"


# ── the unlist arm (issue #225 slice 3, CR-32/E4) ─────────────────────────────
#
# Unlist is RECORD-DRIVEN and catalogue-only: an unlist record drops the row
# at regeneration while the status document is NEVER touched — the release
# stays resolvable and admissible (discovery stops offering it; admission
# still accepts it). The polarity trap the design's risk §7.5 names: a cell
# that drops the row by flipping status fails. The generator continues to
# honour status documents ONLY for yank/revoked (Q8) — a yank record alone
# keeps the row (the validity gate's pair check refuses that incoherence,
# not the generator).


def _unlist_record(
    root: Path, plugin: str = "alpha-tool", version: str = "1.0.0"
) -> Path:
    record_dir = (
        root / "records" / "lifecycle" / "northwind-instruments" / plugin / version
    )
    record_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "record_type": "lifecycle",
        "record_version": "1.1.0",
        "kind": "in-tree-fixture",
        "created_at": "2026-10-02T00:00:00Z",
        "actor": "madeinoz67",
        "lifecycle": {
            "op": "unlist",
            "publisher": "northwind-instruments",
            "plugin": plugin,
            "version": version,
            "reason": "catalogue-only removal fixture",
        },
    }
    path = record_dir / "1-unlist.json"
    path.write_bytes(_canon(record))
    return path


def test_unlist_record_with_published_status_drops_the_row(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    release = _fixture_release(root, status={"lifecycle": "published"})
    status_bytes = (release / "status.json").read_bytes()
    _unlist_record(root)
    assert _row_ids(root) == []
    # CR-32/E4: the status document is untouched — the release stays
    # admissible; only the catalogue row is gone.
    assert (release / "status.json").read_bytes() == status_bytes


def test_unlist_record_with_no_status_drops_the_row(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(root)
    _unlist_record(root)
    assert _row_ids(root) == []


def test_unlist_record_with_deprecated_status_drops_the_row(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(root, status={"lifecycle": "deprecated"})
    _unlist_record(root)
    assert _row_ids(root) == []


def test_unlist_record_with_yanked_status_drops_the_row(tmp_path: Path) -> None:
    """Both mechanisms agree on this cell: record-driven drop + status drop."""
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(root, status={"lifecycle": "yanked"})
    _unlist_record(root)
    assert _row_ids(root) == []


def test_yank_record_alone_keeps_the_row(tmp_path: Path) -> None:
    """Q8 pin: the generator honours status documents only — a yank RECORD
    without a governing status.json does not drop the row here (the validity
    gate's yank_status_absent refuses that incoherence in records CI)."""
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(root)
    record_dir = (
        root / "records" / "lifecycle" / "northwind-instruments" / "alpha-tool" / "1.0.0"
    )
    record_dir.mkdir(parents=True)
    record_dir.joinpath("1-yank.json").write_bytes(
        _canon(
            {
                "record_type": "lifecycle",
                "record_version": "1.1.0",
                "kind": "in-tree-fixture",
                "created_at": "2026-10-02T00:00:00Z",
                "actor": "madeinoz67",
                "lifecycle": {
                    "op": "yank",
                    "publisher": "northwind-instruments",
                    "plugin": "alpha-tool",
                    "version": "1.0.0",
                    "reason": "ungoverned yank fixture (Q8 pin)",
                    "release_manifest_sha256": "d" * 64,
                    "status_sequence": 2,
                },
            }
        )
    )
    assert _row_ids(root) == ["northwind-instruments/alpha-tool"]


def test_unlist_record_without_regeneration_refuses(tmp_path: Path) -> None:
    """CR-21 over the unlist path: the record lands, the index regenerates,
    and a --check against the stale committed index refuses."""
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(root, status={"lifecycle": "published"})
    first = _run("--root", str(root))
    assert first.returncode == 0, first.stderr
    _unlist_record(root)
    check = _run("--check", "--root", str(root))
    assert check.returncode == 1, check.stdout + check.stderr
    assert "index_drift" in check.stderr


def test_unlist_record_does_not_drop_sibling_rows(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _fixture_release(root, plugin="alpha-tool", status={"lifecycle": "published"})
    _fixture_release(root, plugin="beta-tool")
    _unlist_record(root, plugin="alpha-tool")
    assert _row_ids(root) == ["northwind-instruments/beta-tool"]
