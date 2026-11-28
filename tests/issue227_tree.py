"""The three-kind records tree the issue #227 slice-5 arms run on.

author: Stephen Eaton

One builder serves the gate, the index generator, the page generator and the
browser arm, so every arm states its expectation against the SAME tree: an
admitted signed release, an in-tree-fixture release, and a community-shared
listing. The tree is gate-valid as built (``validate_records.validate_tree``
returns no findings), which makes each arm's control non-vacuous: a mutant
planted into it reddens for the planted reason, not because the base tree was
already broken.

Invented names only (the slice-2/slice-3 fixture namespace). The admitted
release carries a FRESH ed25519 key per tree, so the page generator's
generation-time signature verification proves a real signature.

Nothing here is a contract: the expected values (the shared marker id, the
refusal prefixes) are written in the arms that assert them.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import validate_records as vr
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

REPO = Path(__file__).resolve().parents[1]
INDEX_GENERATOR = REPO / "scripts" / "generate_index.py"

#: The three listings, as (publisher, plugin, version).
ADMITTED: tuple[str, str, str] = ("northwind-instruments", "alpha-tool", "1.0.0")
FIXTURE: tuple[str, str, str] = ("northwind-instruments", "fixture-tool", "0.0.1")
SHARED: tuple[str, str, str] = ("harborline-systems", "anchor-meter", "0.4.0")

#: The shared listing's pinned source (an invented repository at a 40-hex digest).
REVISION = "9" * 40
SOURCE_URL = "https://github.com/harborline-example/anchor-meter"

#: A key no fixture listing uses until an arm plants something there.
UNLISTED: tuple[str, str, str] = ("harborline-systems", "cargo-scale", "1.0.0")

#: A second listing an arm adds when it needs a sibling (it must survive
#: another listing's takedown).
SHARED_SIBLING: tuple[str, str, str] = ("harborline-systems", "bore-probe", "1.1.0")

Key = tuple[str, str, str]


def package_id(key: Key) -> str:
    return f"{key[0]}/{key[1]}"


@dataclass(frozen=True)
class ThreeKindTree:
    """A built tree plus the key its admitted release is signed with."""

    root: Path
    signing_key: Ed25519PrivateKey

    def release_dir(self, key: Key) -> Path:
        return self.root / "releases" / "benchweave-registry" / key[0] / key[1] / key[2]

    def lifecycle_dir(self, key: Key) -> Path:
        return self.root / "records" / "lifecycle" / key[0] / key[1] / key[2]

    def publish_path(self, key: Key = ADMITTED) -> Path:
        return self.lifecycle_dir(key) / "1-publish.json"

    def share_record_path(self, key: Key = SHARED) -> Path:
        return self.lifecycle_dir(key) / "1-share.json"

    def read_record(self, path: Path) -> dict[str, Any]:
        parsed: Any = json.loads(path.read_bytes())
        assert isinstance(parsed, dict)
        return parsed


def _canon(obj: object) -> bytes:
    return vr.canonical_bytes(obj)


def _copy(record: dict[str, Any]) -> dict[str, Any]:
    mutated: Any = json.loads(json.dumps(record))
    assert isinstance(mutated, dict)
    return mutated


def with_lifecycle(record: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """A copy of ``record`` whose lifecycle block gains ``changes`` (a
    ``None`` value deletes the member)."""
    mutated = _copy(record)
    block = mutated["lifecycle"]
    for name, value in changes.items():
        if value is None:
            block.pop(name, None)
        else:
            block[name] = value
    return mutated


def with_shared(record: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """The same, applied to the lifecycle ``shared`` block."""
    mutated = _copy(record)
    shared = mutated["lifecycle"]["shared"]
    for name, value in changes.items():
        if value is None:
            shared.pop(name, None)
        else:
            shared[name] = value
    return mutated


def with_top(record: dict[str, Any], **changes: Any) -> dict[str, Any]:
    """The same, applied to the record's top-level members."""
    mutated = _copy(record)
    for name, value in changes.items():
        if value is None:
            mutated.pop(name, None)
        else:
            mutated[name] = value
    return mutated


def share_record(key: Key = SHARED, **lifecycle: Any) -> dict[str, Any]:
    """A canonical community-shared listing record: CR-57's carried set
    (publisher identity, a pinned immutable source ref, licence, declared
    compatibility) plus the capability declaration, all author-declared."""
    record: dict[str, Any] = {
        "actor": key[0],
        "created_at": "2026-11-20T00:00:00Z",
        "kind": "community-shared",
        "lifecycle": {
            "op": "share",
            "publisher": key[0],
            "plugin": key[1],
            "version": key[2],
            "reason": "author-shared standalone plugin; not submitted for admission",
            "shared": {
                "capabilities": {
                    "network_egress": False,
                    "subprocess_or_native_library": False,
                    "filesystem_writes_beyond_evidence_retention": False,
                },
                "compatibility": {
                    "otdp_versions": ["0.2.2"],
                    "adapter_api_versions": ["1.2"],
                    "stg_versions": ["1.4"],
                },
                "display_name": "Anchor meter",
                "licence_spdx": "BSD-3-Clause",
                "source": {"url": SOURCE_URL, "revision": REVISION},
                "summary": "Author-declared summary for the community-shared fixture listing.",
            },
        },
        "record_type": "lifecycle",
        "record_version": "1.2.0",
    }
    return with_lifecycle(record, **lifecycle) if lifecycle else record


def takedown_record(key: Key = SHARED, **lifecycle: Any) -> dict[str, Any]:
    """The recorded takedown of a shared listing (Q20/CR-28): actor, reason
    and timestamp ride the lifecycle record's own fields."""
    record: dict[str, Any] = {
        "actor": "madeinoz67",
        "created_at": "2026-11-27T00:00:00Z",
        "kind": "community-shared",
        "lifecycle": {
            "op": "takedown",
            "publisher": key[0],
            "plugin": key[1],
            "version": key[2],
            "reason": "takedown requested by a third party: the pinned source is gone",
        },
        "record_type": "lifecycle",
        "record_version": "1.2.0",
    }
    return with_lifecycle(record, **lifecycle) if lifecycle else record


def lifecycle_record(op: str, key: Key, *, kind: str = "admitted-release") -> dict[str, Any]:
    """A bare lifecycle record for ``key`` (the slice-3 fixture shape)."""
    return {
        "actor": "madeinoz67",
        "created_at": "2026-11-21T00:00:00Z",
        "kind": kind,
        "lifecycle": {
            "op": op,
            "publisher": key[0],
            "plugin": key[1],
            "version": key[2],
            "reason": f"fixture {op} record",
        },
        "record_type": "lifecycle",
        "record_version": "1.1.0",
    }


def review_record(
    key: Key, kind: str = "admitted-release", submission_digest: str = "a" * 64
) -> dict[str, Any]:
    """A complete, schema-valid review record for ``key`` (the digest chain's
    review half; ``submission_digest`` is D_sub)."""
    return {
        "actor": "madeinoz67",
        "created_at": "2026-10-02T00:00:00Z",
        "kind": kind,
        "record_type": "review",
        "record_version": "1.0.0",
        "review": {
            "capability_declaration": {
                "network_egress": False,
                "subprocess_or_native_library": False,
                "filesystem_writes_beyond_evidence_retention": False,
            },
            "checklist_id": "review-checklist",
            "checklist_version": "1",
            "closure_digest": vr.closure_digest_of_dependencies([]),
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
            "execution_model_disclosure": (
                "in-process execution with full gateway authority; no Python sandbox"
            ),
            "outcome": "accepted",
            "platform_findings": [{"source": "code-scanning", "state": "consulted-no-findings"}],
            "plugin": key[1],
            "publisher": key[0],
            "reviewer_id": "madeinoz67",
            "source_revision": REVISION,
            "submission_manifest_sha256": submission_digest,
            "version": key[2],
        },
    }


def write_record(root: Path, record: dict[str, Any], name: str | None = None) -> Path:
    """Write one lifecycle record under its key's directory, canonically.
    ``name`` defaults to ``<seq>-<op>.json`` at the key's next sequence."""
    block = record["lifecycle"]
    target = (
        root
        / "records"
        / "lifecycle"
        / str(block["publisher"])
        / str(block["plugin"])
        / str(block["version"])
    )
    target.mkdir(parents=True, exist_ok=True)
    if name is None:
        taken = [int(m.group(1)) for p in target.iterdir() if (m := re.match(r"(\d+)-", p.name))]
        name = f"{max(taken, default=0) + 1}-{block['op']}.json"
    path = target / name
    path.write_bytes(_canon(record))
    return path


def write_review(root: Path, record: dict[str, Any]) -> Path:
    """Write a review record under ``records/submissions/<p>/<x>/<v>/``."""
    block = record["review"]
    target = (
        root
        / "records"
        / "submissions"
        / str(block["publisher"])
        / str(block["plugin"])
        / str(block["version"])
    )
    target.mkdir(parents=True, exist_ok=True)
    path = target / "review-1.json"
    path.write_bytes(_canon(record))
    return path


def write_minimal_review(
    root: Path, publisher: str, plugin: str, version: str, *, kind: str = "admitted-release"
) -> Path:
    """The least a release needs for a catalogue row (issue #227 slice 5): one
    kind-carrying record. The synthetic release trees of the generator and
    page suites carry this and nothing more — a row's kind is generated from a
    record, never defaulted."""
    return write_review(
        root,
        {
            "actor": "madeinoz67",
            "created_at": "2026-10-02T00:00:00Z",
            "kind": kind,
            "record_type": "review",
            "record_version": "1.0.0",
            "review": {"plugin": plugin, "publisher": publisher, "version": version},
        },
    )


def plant_bare_release(root: Path, key: Key) -> Path:
    """A release directory at ``key`` carrying only an identity manifest —
    enough for the gate's release census to see a release there."""
    release_dir = root / "releases" / "benchweave-registry" / key[0] / key[1] / key[2]
    release_dir.mkdir(parents=True)
    manifest = {
        "registry_id": "benchweave-registry",
        "package_id": package_id(key),
        "version": key[2],
    }
    path = release_dir / "manifest.json"
    path.write_bytes(_canon(manifest))
    return path


def _release(
    root: Path,
    key: Key,
    *,
    kind: str,
    display_name: str,
    signing_key: Ed25519PrivateKey | None,
) -> None:
    """One gate-valid release: payload, review record, signed manifest,
    publish record — the digest chain the validity gate walks (CR-11/14/38)."""
    publisher, plugin, version = key
    release_dir = root / "releases" / "benchweave-registry" / publisher / plugin / version
    release_dir.mkdir(parents=True)
    member = b"'''Synthetic fixture plugin (issue #227 slice-5 fixture set).'''\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("plugin/__init__.py", date_time=(2026, 1, 1, 0, 0, 0))
        archive.writestr(info, member)
    payload = buffer.getvalue()
    submission: dict[str, Any] = {
        "registry_id": "benchweave-registry",
        "package_id": f"{publisher}/{plugin}",
        "version": version,
        "publisher_id": publisher,
        "display_name": display_name,
        "summary": f"Synthetic {kind} release for the issue #227 slice-5 arms.",
        "licence": {"spdx_expression": "MIT", "file": "LICENSE"},
        "compatibility": {
            "otdp_versions": ["0.2.2"],
            "adapter_api_versions": ["1.1"],
            "stg_versions": ["1.4"],
        },
        "dependencies": [],
        "evidence": [
            {
                "level": "simulated",
                "report_path": "evidence/protocol-evidence.md",
                "result": "passed",
            }
        ],
        "source": {"url": f"https://github.com/{publisher}-example/{plugin}", "revision": REVISION},
        "payload": {
            "bytes": len(payload),
            "files": [
                {
                    "path": "plugin/__init__.py",
                    "role": "implementation",
                    "bytes": len(member),
                    "sha256": vr.sha256_hex(member),
                }
            ],
            "media_type": "application/zip",
            "sha256": vr.sha256_hex(payload),
        },
        "manifest_version": "0.1.1",
    }
    submission_bytes = _canon(submission)

    review_path = write_review(root, review_record(key, kind, vr.sha256_hex(submission_bytes)))

    manifest = {name: value for name, value in submission.items() if name != "manifest_version"}
    manifest["review"] = {
        "checklist_id": "review-checklist",
        "checklist_version": "1",
        "outcome": "accepted",
        "record_sha256": vr.sha256_hex(review_path.read_bytes()),
        "reviewer_id": "madeinoz67",
    }
    manifest_bytes = _canon(manifest)
    (release_dir / "manifest.json").write_bytes(manifest_bytes)
    (release_dir / "submission-manifest.json").write_bytes(submission_bytes)
    (release_dir / "payload.zip").write_bytes(payload)
    signed = signing_key is not None
    if signing_key is not None:
        (release_dir / "manifest.sig").write_bytes(signing_key.sign(submission_bytes))

    publish: dict[str, Any] = {
        "actor": "madeinoz67",
        "created_at": "2026-10-02T00:00:00Z",
        "kind": kind,
        "record_type": "lifecycle",
        "record_version": "1.0.0",
        "lifecycle": {
            "op": "publish",
            "publisher": publisher,
            "plugin": plugin,
            "version": version,
            "reason": f"fixture publish record ({kind})",
            "release_manifest_sha256": vr.sha256_hex(manifest_bytes),
            "closure": {"prior": None, "added": [], "changed": [], "removed": []},
            "closure_digest": vr.closure_digest_of_dependencies([]),
            "signature_state": "signed-valid" if signed else "unsigned",
        },
    }
    written = write_record(root, publish)
    assert written.name == "1-publish.json", written


def _publishers(signing_key: Ed25519PrivateKey) -> dict[str, Any]:
    """The slice-3 fixture publishers (both vetted), with the admitted
    publisher's key replaced by this tree's fresh public key."""
    source = (
        REPO / "tests" / "fixtures" / "issue225" / "queue-records" / "records" / "publishers.json"
    )
    document: Any = json.loads(source.read_bytes())
    assert isinstance(document, dict)
    pem = (
        signing_key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    for entry in document["publishers"]:
        if entry["publisher_id"] == ADMITTED[0]:
            entry["ed25519_public_key_pem"] = pem
    return document


def three_kind_tree(root: Path, *, site_sources: bool = False) -> ThreeKindTree:
    """Build the gate-valid three-kind tree under ``root``.

    ``site_sources`` also copies the catalogue templates, assets and the
    vendored styleguide/htmx beside it, so ``generate_catalogue_page.py
    --root <root>`` renders a site from this tree.
    """
    (root / "records").mkdir(parents=True)
    signing_key = Ed25519PrivateKey.generate()
    (root / "records" / "publishers.json").write_bytes(_canon(_publishers(signing_key)))
    (root / "lane-rules.json").write_bytes((REPO / "lane-rules.json").read_bytes())
    (root / "vetting-checklist.md").write_bytes((REPO / "vetting-checklist.md").read_bytes())
    _release(
        root,
        ADMITTED,
        kind="admitted-release",
        display_name="Northwind alpha tool",
        signing_key=signing_key,
    )
    _release(
        root,
        FIXTURE,
        kind="in-tree-fixture",
        display_name="Northwind fixture tool",
        signing_key=None,
    )
    write_record(root, share_record())
    if site_sources:
        shutil.copytree(REPO / "catalogue", root / "catalogue")
        shutil.copytree(REPO / "vendored", root / "vendored")
    return ThreeKindTree(root=root, signing_key=signing_key)


def run_generator(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    """``generate_index.py --root <root> [*extra]``, never raising."""
    return subprocess.run(
        [sys.executable, str(INDEX_GENERATOR), "--root", str(root), *extra],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )


def generate(root: Path) -> list[dict[str, Any]]:
    """Run the index generator over ``root`` and return its rows."""
    result = run_generator(root)
    assert result.returncode == 0, result.stdout + result.stderr
    document: Any = json.loads((root / "index.json").read_bytes())
    assert isinstance(document, dict)
    return [row for row in document["rows"] if isinstance(row, dict)]


def rows_by_key(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Rows keyed ``<package_id>@<version>``."""
    return {f"{row['package_id']}@{row['version']}": row for row in rows}


def three_kind_index(root: Path) -> bytes:
    """The generated index bytes of a freshly built three-kind tree."""
    three_kind_tree(root)
    generate(root)
    return (root / "index.json").read_bytes()
