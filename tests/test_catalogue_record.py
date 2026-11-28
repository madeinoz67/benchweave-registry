"""The record pages (issue #224 follow-on §2.5-§2.7; acceptance B-F/B-V/B-L).

One standalone page per index row at ``records/<registry_id>/<package_id>/
<version>/index.html``, generated at deploy time by the same ``main()``.
The fragment renderer is pure over ``(row, publisher_entry, files, sha)``;
the e2e arms build synthetic trees (the yank-pin precedent) with FRESH
ed25519 keys, run ``generate_index.py`` + the page generator as
subprocesses, and pin the join, the generation-time signature verification
and the download bindings against real rendered artifacts.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import validate_records as vr
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from issue227_tree import (
    ADMITTED,
    SHARED,
    generate,
    rows_by_key,
    three_kind_tree,
    write_minimal_review,
)
from issue227_tree import (
    FIXTURE as FIXTURE_RELEASE,
)
from test_catalogue_page import FOOTER_PARAGRAPH, assert_no_service_claim_vocabulary

REPO = Path(__file__).resolve().parents[1]
GENERATOR = REPO / "scripts" / "generate_catalogue_page.py"
RECORD_TEMPLATE = REPO / "catalogue" / "record.template.html"
INDEX_GENERATOR = REPO / "scripts" / "generate_index.py"
FIXTURE = REPO / "tests" / "fixtures" / "plugins-index.fixture.json"

SHA = "0" * 39 + "1"  # invented 40-hex sha for render tests

PUBLISHER_ENTRY: dict[str, Any] = {
    "publisher_id": "northwind-instruments",
    "github": "northwind-instruments",
    "namespace": "northwind-instruments",
    "vetted_at": "2026-10-01T00:00:00Z",
    "key_validity": {
        "not_before": "2026-01-01T00:00:00Z",
        "not_after": "2030-01-01T00:00:00Z",
    },
    "publisher_repo_protections": [
        {"protection": "push-protection", "state": "declared-not-verified"},
        {"protection": "code-scanning", "state": "declared-not-verified"},
    ],
}

FILES = [
    {"name": "manifest.json", "digest": ""},
    {"name": "manifest.sig", "digest": ""},
    {"name": "payload.zip", "digest": ""},
    {"name": "submission-manifest.json", "digest": ""},
]


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("generate_catalogue_page", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _template() -> str:
    return RECORD_TEMPLATE.read_text(encoding="utf-8")


def _rows() -> list[dict[str, Any]]:
    return list(json.loads(FIXTURE.read_text(encoding="utf-8"))["rows"])


def _row(package_id: str) -> dict[str, Any]:
    return next(row for row in _rows() if row["package_id"] == package_id)


def _render_record(
    row: dict[str, Any],
    files: list[dict[str, str]] | None = None,
    sha: str = SHA,
    **kwargs: Any,
) -> str:
    module = _module()
    return str(
        module.render_record_page(
            row, PUBLISHER_ENTRY, files or [], sha, _template(), **kwargs
        )
    )


# ── the fragment field set (B-F) ──────────────────────────────────────────────


def test_every_fragment_field_renders() -> None:
    """B-F: the §2.6 field set on a fully-populated row — CR-20 seven,
    identity trio, kind badge, signature line, key validity, vetted date,
    protections, the D-S2b trio, transport providers, marker explanations."""
    row = _row("northwind-instruments/northwind-psu")
    row["manifest_sha256"] = "e" * 64
    page = _render_record(row, FILES)
    # breadcrumb + identity
    assert 'href="../../../../../index.html">Catalogue</a>' in page
    assert ">northwind-instruments</span>" in page and "northwind-psu" in page
    assert ">0.1.0<" in page, "the version badge"
    assert "Admitted release" in page, "the kind badge"
    assert "Signed by northwind-instruments" in page, "the signed pill"
    assert "Valid against the recorded ed25519 key" in page
    assert "2026-01-01 to 2030-01-01" in page, "the key-validity window"
    assert "vetted 2026-10-01" in page
    # CR-20: provenance fields
    assert "none recorded, recommended" in page, "the timestamp badge"
    assert row["source_revision"] in page, "the full source revision"
    assert "e" * 64 in page, "the full manifest digest"
    assert row["gateway_ref"] in page, "the gateway ref (title-carried)"
    assert ">MIT<" in page
    # evidence: table + report link at the stamp
    assert ">simulated<" in page and ">passed<" in page
    assert (
        'href="https://github.com/madeinoz67/benchweave-registry/tree/'
        f'{SHA}/releases/benchweave-registry/northwind-instruments/northwind-psu"'
    ) in page
    assert "evidence/protocol-evidence.md" in page
    # compatibility trio + transport providers (D-S2b part 1)
    assert ">0.2.2<" in page and ">1.1<" in page and ">1.4<" in page
    assert "None declared" in page, "empty transport triples"
    # capabilities (part 2) rendered Yes/No
    assert ">Yes<" in page and ">No<" in page
    # markers with explanations
    assert "conformance-evidence-self-attested" in page
    assert "The publisher ran and reported the conformance evidence." in page
    assert "Review followed the registry process; it does not prove behaviour." in page
    # aside: admission + status + protections (part 3)
    assert (
        "Publication is not authorization. Admit this release on your own bench "
        "through your gateway's local admission, pinned to the manifest digest "
        "above." in page
    )
    assert "Open release files" in page
    assert "Push protection" in page and "Code scanning" in page
    assert page.count("declared, not verified") == 2, "states render verbatim"
    assert ">Maintained<" in page, "the maintenance badge (psu is maintained)"
    assert "No vendor attestation" in page


def test_unsigned_rows_render_the_unsigned_surfaces() -> None:
    row = _row("harborline-systems/harborline-relay")  # admitted-release, unsigned
    page = _render_record(row, FILES)
    assert ">Unsigned<" in page
    assert "No publisher signature" in page
    assert "Valid against the recorded ed25519 key" not in page
    assert "Signed by" not in page


def test_the_hardware_negative_line_derives_both_ways() -> None:
    row = _row("northwind-instruments/northwind-cal")  # hardware + simulated
    with_hw = _render_record(row, FILES)
    assert "No hardware evidence is recorded for this release." not in with_hw
    without_hw = _render_record(_row("northwind-instruments/northwind-psu"), FILES)
    assert "No hardware evidence is recorded for this release." in without_hw


def test_explicit_none_everywhere_on_an_empty_row() -> None:
    """CR-20's "or explicitly none", record-page form."""
    row: dict[str, Any] = {
        "registry_id": "benchweave-registry",
        "package_id": "northwind-instruments/empty-tool",
        "version": "0.0.1",
        "kind": "admitted-release",
        "publisher": "northwind-instruments",
        "signature_state": "unsigned",
        "manifest_sha256": "f" * 64,
        "display_name": "Empty tool",
        "summary": "",
        "licence_spdx": "unknown",
        "compatibility": {
            "otdp_versions": [], "adapter_api_versions": [], "stg_versions": [],
        },
        "evidence": [],
        "maintenance": "unknown",
        "advisories": [],
        "transport_triples": [],
        "unverified_markers": [],
        "timestamp": None,
        "timestamp_recommended": False,
        "gateway_ref": None,
        "firmware_attestation": None,
        "source_revision": "0" * 40,
    }
    page = _render_record(row, [])
    assert "no test evidence recorded" in page
    assert page.count("none declared") == 3, "OTDP / adapter / STG"
    assert "None declared" in page, "transport providers"
    assert ">None<" in page, "advisories"
    assert "No vendor attestation" in page
    assert "none recorded" in page, "gateway ref / timestamp"
    assert "none present" in page, "the files list on an empty release dir"
    bare = _module().render_record_page(
        row, {"publisher_id": "northwind-instruments"}, [], SHA, _template()
    )
    assert "none recorded" in str(bare), "publisher repository card"


def test_the_marker_explanation_map_is_single_carrier() -> None:
    """§5: MARKER_EXPLANATION lives in ONE carrier (record pages are static;
    no JS clones them) — seeded with the mockup's two sentences and extended
    by issue #227 slice 5 with the shared marker's, and an unknown marker id
    renders its id with no explanation line."""
    module = _module()
    assert module.MARKER_EXPLANATION == {
        "conformance-evidence-self-attested": (
            "The publisher ran and reported the conformance evidence."
        ),
        "review-is-process-not-proof": (
            "Review followed the registry process; it does not prove behaviour."
        ),
        "community-shared-not-reviewed": (
            "The author shared this entry. The registry did not review it and did "
            "not check anything in it."
        ),
    }
    plugins_js = (REPO / "catalogue" / "assets" / "plugins.js").read_text(encoding="utf-8")
    assert "MARKER_EXPLANATION" not in plugins_js, (
        "the explanation map grew a JS twin — record pages are static by design"
    )
    # The unknown id is planted on an admitted row: since issue #227 slice 5
    # the fixture's shared rows carry only the shared marker (a known one).
    row = _row("northwind-instruments/northwind-psu")
    row["unverified_markers"] = list(row["unverified_markers"]) + ["future-marker-unmapped"]
    page = _render_record(row, FILES)
    assert "future-marker-unmapped" in page
    unknown_row = re.search(
        r'<span class="badge badge-warning mono">future-marker-unmapped'
        r"</span>(.*?)</span>",
        page,
        re.DOTALL,
    )
    assert unknown_row is not None and unknown_row.group(1) == "", (
        "an unknown marker id must render with NO explanation line"
    )


def test_record_pages_are_deterministic_and_stamp_the_index_version() -> None:
    row = _row("northwind-instruments/northwind-psu")
    once = _render_record(row, FILES)
    twice = _render_record(row, FILES)
    assert once == twice
    assert f">{SHA[:12]}</span> · index v1" in once


def test_record_pages_make_no_service_claim_in_both_mark_postures() -> None:
    row = _row("northwind-instruments/northwind-psu")
    page = _render_record(row, FILES)
    lowered = page.lower()
    assert lowered.count("registry service") == 1, (
        "the record page's footer negation is the phrase's only occurrence"
    )
    assert "There is no hosted registry service." in page
    assert "registry.benchweave.dev" not in lowered
    assert "<rect" not in page and "<circle" not in page, (
        "the unfired record page carries no mark shapes (icons are rewrites)"
    )
    fired = _render_record(row, FILES, registry_mark=True)
    assert fired.count("<rect") == 3, "the fired record page carries the three bars"
    assert "<circle" not in fired


def test_the_record_footer_negation_is_pinned_and_vocabulary_scoped() -> None:
    """Fold F3 on the record pages: the same footer paragraph pinned exact
    (any ". One is coming." suffix reddens) and the service-claim
    vocabulary scoped to it, both mark postures."""
    row = _row("northwind-instruments/northwind-psu")
    for posture in (False, True):
        page = _render_record(row, FILES, registry_mark=posture)
        assert page.count(FOOTER_PARAGRAPH) == 1, (
            f"the record footer paragraph drifted (registry_mark={posture})"
        )
        assert_no_service_claim_vocabulary(
            page, f"the record page (registry_mark={posture})"
        )


# ── R10: the record template ──────────────────────────────────────────────────


def test_record_template_uses_the_up_prefix_and_loads_no_external_js() -> None:
    template = _template()
    assert 'href="../../../../../assets/catalogue.css"' in template
    assert _module().UP_PREFIX == "../" * 5
    assert "<script src=" not in template, "record pages load no external JS (B-S)"
    for literal in ('src="/', 'href="/', "fetch('/", 'fetch("/'):
        assert literal not in template, f"root-absolute form {literal!r}"
    assert "bw-theme-toggle" in template and "data-bw-copy" in template, (
        "the inline script must wire the theme toggle and the copy buttons"
    )
    assert "navigator.clipboard" in template


# ── downloads (B-L) ───────────────────────────────────────────────────────────


def test_the_files_section_lists_every_file_raw_at_the_stamp() -> None:
    row = _row("northwind-instruments/northwind-psu")
    row["manifest_sha256"] = "a" * 64
    files = [
        {"name": "manifest.json", "digest": "a" * 64},
        {"name": "manifest.sig", "digest": ""},
        {"name": "payload.zip", "digest": "b" * 64},
        {"name": "submission-manifest.json", "digest": ""},
    ]
    page = _render_record(row, files)
    base = (
        f"https://raw.githubusercontent.com/madeinoz67/benchweave-registry/{SHA}"
        "/releases/benchweave-registry/northwind-instruments/northwind-psu/0.1.0"
    )
    for name in ("manifest.json", "manifest.sig", "payload.zip", "submission-manifest.json"):
        assert f'href="{base}/{name}"' in page, f"{name} is not linked raw-at-stamp"
    # the manifest entry displays the row's digest; the payload entry the
    # manifest-declared digest; the others carry no digest claim
    listed = re.findall(r'<li><a href="[^"]+">([a-z.-]+)</a>(.*?)</li>', page)
    assert [name for name, _ in listed] == [
        "manifest.json", "manifest.sig", "payload.zip", "submission-manifest.json",
    ]
    by_name = dict(listed)
    assert "a" * 64 in by_name["manifest.json"]
    assert "b" * 64 in by_name["payload.zip"]
    assert "b" * 64 not in by_name["manifest.sig"]
    assert "b" * 64 not in by_name["submission-manifest.json"]


# ── the 2026-10-02 fold rows (F4/F5/F7/F9/F10, record-page surfaces) ──────────


def test_key_validity_renders_none_recorded_when_either_bound_is_absent() -> None:
    """F7 (reviewer R1): key_validity is optional — a publisher entry
    missing either bound rendered an empty " to " window; both halves now
    render the honest 'none recorded'."""
    row = _row("northwind-instruments/northwind-psu")
    module = _module()

    def _validity_cell(page: str) -> str:
        assert "Key validity</th><td>" in page
        return page.split("Key validity</th><td>", 1)[1].split("</td>", 1)[0]

    for entry in (
        {"publisher_id": "northwind-instruments"},
        {**PUBLISHER_ENTRY, "key_validity": {"not_before": "2026-01-01T00:00:00Z"}},
        {**PUBLISHER_ENTRY, "key_validity": {"not_after": "2030-01-01T00:00:00Z"}},
    ):
        page = str(module.render_record_page(row, entry, FILES, SHA, _template()))
        cell = _validity_cell(page)
        assert "none recorded" in cell, f"an absent bound rendered as a window: {cell!r}"
        assert " to " not in cell, cell
    control = str(
        module.render_record_page(row, PUBLISHER_ENTRY, FILES, SHA, _template())
    )
    assert "2026-01-01 to 2030-01-01" in _validity_cell(control)


def test_download_hrefs_percent_encode_unsafe_file_names() -> None:
    """F5 (lane A F4): a release file named report#2.md truncated at the
    fragment (the href became …report + fragment 2.md) and report?q.md lost
    its query — the name is percent-encoded in the href now; the DISPLAY
    name stays the human-readable file name."""
    row = _row("northwind-instruments/northwind-psu")
    files = [
        {"name": "manifest.json", "digest": ""},
        {"name": "report#2.md", "digest": ""},
        {"name": "report?q.md", "digest": ""},
        {"name": "räport ü.md", "digest": ""},
    ]
    page = _render_record(row, files)
    base = (
        f"https://raw.githubusercontent.com/madeinoz67/benchweave-registry/{SHA}"
        "/releases/benchweave-registry/northwind-instruments/northwind-psu/0.1.0"
    )
    assert f'href="{base}/report%232.md"' in page, "the # file name truncated"
    assert f'href="{base}/report%3Fq.md"' in page, "the ? file name truncated"
    assert f'href="{base}/r%C3%A4port%20%C3%BC.md"' in page, (
        "the non-ASCII file name is not percent-encoded"
    )
    assert ">report#2.md<" in page, "the display name must stay readable"
    assert ">räport ü.md<" in page


def test_release_file_enumeration_skips_symlinks(tmp_path: Path) -> None:
    """F5's second half: a symlink inside the release directory is not a
    release file — enumeration lists regular files only (pre-fold a symlink
    listed and linked raw)."""
    root = tmp_path / "repo"
    release = (
        root / "releases" / "benchweave-registry" / "northwind-instruments"
        / "northwind-psu" / "0.1.0"
    )
    release.mkdir(parents=True)
    (release / "manifest.json").write_text("{}")
    (release / "payload.zip").write_bytes(b"PK")
    (release / "notes.md").write_text("real file")
    (release / "link.md").symlink_to(release / "notes.md")
    row = {
        "registry_id": "benchweave-registry",
        "package_id": "northwind-instruments/northwind-psu",
        "version": "0.1.0",
    }
    names = [entry["name"] for entry in _module()._release_files(root, row)]
    assert names == ["manifest.json", "notes.md", "payload.zip"], (
        f"enumeration must list the regular files only, got {names}"
    )
    assert "link.md" not in names


def test_the_unfired_record_render_strips_the_wordmark_markers() -> None:
    """F10 on the record template: the unfired render carries no marker of
    its family — the wordmark delimiters were stripped from the
    structural-check copy only, the record begin/end delimiters are the
    fragment's own wrappers. The fired posture keeps its wordmark
    delimiters (the switch's documented state)."""
    row = _row("northwind-instruments/northwind-psu")
    page = _render_record(row, FILES)
    for marker in (
        "bw:wordmark begin",
        "bw:wordmark end",
        "bw:provenance -->",
        "bw:record begin",
        "bw:record end",
    ):
        assert marker not in page, f"a template marker survived the render: {marker}"
    fired = _render_record(row, FILES, registry_mark=True)
    assert "bw:wordmark begin" in fired and "bw:wordmark end" in fired


def test_e2e_a_corrupt_recorded_key_refuses_typed_not_a_traceback(
    tmp_path: Path,
) -> None:
    """F4 (lane A F3): a publisher entry whose PEM body is corrupt made the
    generator die with a BARE ValueError traceback from
    load_pem_public_key; the key path now refuses with the typed
    page_signature_invalid: prefix naming the row."""
    root, _private = _synthetic_repo(tmp_path)
    publishers_path = root / "records" / "publishers.json"
    document = json.loads(publishers_path.read_bytes())
    document["publishers"][0]["ed25519_public_key_pem"] = (
        "-----BEGIN PUBLIC KEY-----\nnot-a-key-body-at-all\n-----END PUBLIC KEY-----\n"
    )
    publishers_path.write_bytes(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    )
    result = _generate_site(root, tmp_path / "site")
    assert result.returncode != 0, "a corrupt recorded key must refuse the deploy"
    assert "page_signature_invalid:" in result.stderr, result.stderr
    assert "benchweave-registry/quarrystone-labs/alpha-meter/1.0.0" in result.stderr, (
        "the refusal names the row"
    )
    assert "Traceback" not in result.stderr, (
        "the corrupt-key refusal must be typed, not a bare traceback"
    )


def test_e2e_colliding_detail_host_slugs_refuse_naming_both_rows(
    tmp_path: Path,
) -> None:
    """F9 (lane B F3): the detail-host slug folds every non-[A-Za-z0-9-]
    character to '-', so `quarrystone-labs/alpha-meter` and
    `quarrystone-labs-alpha/meter` at one version — both index-schema-legal
    identities — share one host id and two rows drill into ONE host.
    Generation refuses, naming both rows (pre-fold it generated
    silently)."""
    root, _private = _synthetic_repo(tmp_path)
    _write_release(
        root, publisher="quarrystone-labs-alpha", plugin="meter", version="1.0.0",
        private_key=None,
    )
    publishers_path = root / "records" / "publishers.json"
    document = json.loads(publishers_path.read_bytes())
    document["publishers"].append(
        {
            "publisher_id": "quarrystone-labs-alpha",
            "github": "quarrystone-labs-alpha",
            "namespace": "quarrystone-labs-alpha",
            "ed25519_public_key_pem": document["publishers"][0][
                "ed25519_public_key_pem"
            ],
            "vetted_at": "2026-10-01T00:00:00Z",
        }
    )
    publishers_path.write_bytes(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    )
    result = _generate_site(root, tmp_path / "site")
    assert result.returncode != 0, "colliding detail-host slugs must refuse"
    assert "page_detail_id_collision:" in result.stderr, result.stderr
    for label in (
        "benchweave-registry/quarrystone-labs/alpha-meter/1.0.0",
        "benchweave-registry/quarrystone-labs-alpha/meter/1.0.0",
    ):
        assert label in result.stderr, f"the refusal must name both rows: {label}"
    assert not (tmp_path / "site" / "index.html").is_file(), (
        "nothing deploys on refusal"
    )


# ── typed refusals (unit half) ────────────────────────────────────────────────


def test_a_publisher_join_miss_refuses() -> None:
    module = _module()
    row = _row("northwind-instruments/northwind-psu")
    with pytest.raises(SystemExit, match="page_publisher_unknown: northwind-instruments"):
        module._publisher_entry_or_refuse(row, {})


def test_a_missing_release_dir_refuses() -> None:
    module = _module()
    row = _row("northwind-instruments/northwind-psu")
    with pytest.raises(SystemExit, match="page_release_dir_missing:"):
        module._release_files(Path("/nonexistent-repo-root"), row)


# ── e2e: synthetic trees with fresh keys (B-V/B-L, the yank-pin precedent) ───


def _write_release(
    root: Path,
    *,
    publisher: str,
    plugin: str,
    version: str,
    private_key: Ed25519PrivateKey | None,
    evidence: list[dict[str, str]] | None = None,
) -> None:
    release = root / "releases" / "benchweave-registry" / publisher / plugin / version
    release.mkdir(parents=True)
    payload = b"PK-synthetic-payload-" + version.encode()
    manifest: dict[str, Any] = {
        "registry_id": "benchweave-registry",
        "package_id": f"{publisher}/{plugin}",
        "version": version,
        "publisher_id": publisher,
        "display_name": f"{plugin} display name",
        "summary": f"Synthetic {plugin} release for the record-page e2e.",
        "licence": {"spdx_expression": "MIT"},
        "compatibility": {
            "otdp_versions": ["0.2.2"], "adapter_api_versions": ["1.1"],
            "stg_versions": ["1.4"],
        },
        "evidence": evidence if evidence is not None else [
            {"level": "simulated", "report_path": "evidence/e2e-evidence.md",
             "result": "passed"},
        ],
        "payload": {"sha256": hashlib.sha256(payload).hexdigest(), "files": []},
        "source": {"revision": "c" * 40},
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    (release / "manifest.json").write_bytes(manifest_bytes)
    submission = dict(manifest)
    submission["manifest_version"] = "0.1.1"
    submission_bytes = json.dumps(
        submission, sort_keys=True, separators=(",", ":")
    ).encode()
    (release / "submission-manifest.json").write_bytes(submission_bytes)
    (release / "payload.zip").write_bytes(payload)
    if private_key is not None:
        (release / "manifest.sig").write_bytes(private_key.sign(submission_bytes))
    # Issue #227 slice 5: a release row's kind is generated from a record,
    # never defaulted — the synthetic release carries one kind-carrying record.
    write_minimal_review(root, publisher, plugin, version)


def _synthetic_repo(tmp_path: Path) -> tuple[Path, Ed25519PrivateKey]:
    root = tmp_path / "repo"
    root.mkdir()
    # the generator reads its templates/assets relative to --root
    shutil.copytree(REPO / "catalogue", root / "catalogue")
    shutil.copytree(REPO / "vendored", root / "vendored")
    private = Ed25519PrivateKey.generate()
    pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    publishers = {
        "publishers_version": 1,
        "publishers": [
            {
                "publisher_id": "quarrystone-labs",
                "github": "quarrystone-labs",
                "namespace": "quarrystone-labs",
                "ed25519_public_key_pem": pem,
                "vetted_at": "2026-10-01T00:00:00Z",
                "key_validity": {
                    "not_before": "2026-01-01T00:00:00Z",
                    "not_after": "2030-01-01T00:00:00Z",
                },
                "publisher_repo_protections": [
                    {"protection": "push-protection", "state": "declared-not-verified"},
                ],
            }
        ],
    }
    (root / "records").mkdir()
    (root / "records" / "publishers.json").write_text(
        json.dumps(publishers, sort_keys=True, separators=(",", ":"))
    )
    _write_release(
        root, publisher="quarrystone-labs", plugin="alpha-meter", version="1.0.0",
        private_key=private,
    )
    _write_release(
        root, publisher="quarrystone-labs", plugin="beta-probe", version="0.3.0",
        private_key=None,  # unsigned
        evidence=[{"level": "hardware", "report_path": "evidence/hw.md", "result": "passed"}],
    )
    return root, private


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _generate_site(root: Path, dest: Path) -> subprocess.CompletedProcess[str]:
    result = _run([sys.executable, str(INDEX_GENERATOR), "--root", str(root)])
    assert result.returncode == 0, result.stderr
    return _run(
        [sys.executable, str(GENERATOR), "--root", str(root),
         "--dest", str(dest), "--sha", SHA]
    )


def test_e2e_every_row_gets_a_page_and_signed_rows_verify(tmp_path: Path) -> None:
    root, _private = _synthetic_repo(tmp_path)
    dest = tmp_path / "site"
    result = _generate_site(root, dest)
    assert result.returncode == 0, result.stderr
    signed_page = (
        dest / "records" / "benchweave-registry" / "quarrystone-labs"
        / "alpha-meter" / "1.0.0" / "index.html"
    ).read_text(encoding="utf-8")
    assert "Valid against the recorded ed25519 key" in signed_page
    assert "Signed by quarrystone-labs" in signed_page
    assert "vetted 2026-10-01" in signed_page
    unsigned_page = (
        dest / "records" / "benchweave-registry" / "quarrystone-labs"
        / "beta-probe" / "0.3.0" / "index.html"
    ).read_text(encoding="utf-8")
    assert ">Unsigned<" in unsigned_page
    assert "Valid against the recorded ed25519 key" not in unsigned_page
    # the hardware row's negative line is absent (beta-probe carries hardware)
    assert "No hardware evidence is recorded for this release." not in unsigned_page
    assert "No hardware evidence is recorded for this release." in signed_page


def test_e2e_a_planted_bad_signature_refuses_and_nothing_deploys(tmp_path: Path) -> None:
    """B-V: a tampered manifest.sig never renders a validity claim — the
    generator refuses with the typed prefix and writes nothing."""
    root, _private = _synthetic_repo(tmp_path)
    sig = (
        root / "releases" / "benchweave-registry" / "quarrystone-labs"
        / "alpha-meter" / "1.0.0" / "manifest.sig"
    )
    sig.write_bytes(b"tampered-signature-bytes")
    dest = tmp_path / "site"
    result = _generate_site(root, dest)
    assert result.returncode != 0, "a tampered signature must refuse the deploy"
    assert "page_signature_invalid:" in result.stderr, result.stderr
    assert (
        "benchweave-registry/quarrystone-labs/alpha-meter/1.0.0" in result.stderr
    ), "the refusal names the row"
    assert not (dest / "index.html").is_file(), "nothing deploys on refusal"


def test_e2e_the_signature_verification_is_the_only_thing_that_refuses(
    tmp_path: Path,
) -> None:
    """RED-sanity by mechanism reversion (the acceptance rule's form): with
    ONLY the verify call removed (a sandbox copy of the generator), the
    tampered-signature tree renders — proving the refusal discriminates
    exactly on the verification mechanism, not on some incidental refusal."""
    root, _private = _synthetic_repo(tmp_path)
    (
        root / "releases" / "benchweave-registry" / "quarrystone-labs"
        / "alpha-meter" / "1.0.0" / "manifest.sig"
    ).write_bytes(b"tampered-signature-bytes")
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    generator_copy = sandbox / "generate_catalogue_page.py"
    generator_copy.write_text(
        GENERATOR.read_text(encoding="utf-8").replace(
            "            _verify_row_signature(root, row, publishers[str(row.get(\"publisher\"))])",
            "            pass  # verify call reverted (RED-sanity sandbox)",
        )
    )
    assert "verify call reverted" in generator_copy.read_text(encoding="utf-8"), (
        "the sandbox neutralization must have applied"
    )
    result = _run([sys.executable, str(INDEX_GENERATOR), "--root", str(root)])
    assert result.returncode == 0, result.stderr
    dest = tmp_path / "site"
    result = _run(
        [sys.executable, str(generator_copy), "--root", str(root),
         "--dest", str(dest), "--sha", SHA]
    )
    assert result.returncode == 0, (
        "with only the verify call reverted the tampered tree renders — "
        f"the refusal is the mechanism: {result.stderr}"
    )
    page = (
        dest / "records" / "benchweave-registry" / "quarrystone-labs"
        / "alpha-meter" / "1.0.0" / "index.html"
    ).read_text(encoding="utf-8")
    assert "Valid against the recorded ed25519 key" in page, (
        "the reverted sandbox renders the validity claim the real generator refuses"
    )


def test_e2e_a_publisher_join_miss_refuses(tmp_path: Path) -> None:
    root, _private = _synthetic_repo(tmp_path)
    publishers_path = root / "records" / "publishers.json"
    publishers_path.write_text(
        json.dumps({"publishers_version": 1, "publishers": []})
    )
    result = _generate_site(root, tmp_path / "site")
    assert result.returncode != 0
    assert "page_publisher_unknown: quarrystone-labs" in result.stderr


def test_e2e_download_digests_bind_to_the_generating_tree(tmp_path: Path) -> None:
    """B-L's recomputation arms: the manifest entry's displayed digest equals
    a fresh sha256 of the file at the href's path in the generating tree, and
    the payload entry displays the manifest-DECLARED archive digest."""
    root, _private = _synthetic_repo(tmp_path)
    dest = tmp_path / "site"
    result = _generate_site(root, dest)
    assert result.returncode == 0, result.stderr
    page = (
        dest / "records" / "benchweave-registry" / "quarrystone-labs"
        / "alpha-meter" / "1.0.0" / "index.html"
    ).read_text(encoding="utf-8")
    release = (
        root / "releases" / "benchweave-registry" / "quarrystone-labs"
        / "alpha-meter" / "1.0.0"
    )
    on_disk = sorted(p.name for p in release.iterdir() if p.is_file())
    listed = re.findall(r'<li><a href="([^"]+)">([a-z.-]+)</a>(.*?)</li>', page)
    assert [name for _, name, _ in listed] == on_disk, (
        f"the files section must list exactly the release dir's regular files: "
        f"{on_disk}"
    )
    digests = {name: tail for _href, name, tail in listed}
    # manifest entry: displayed == recomputed at the href's path
    recomputed = hashlib.sha256((release / "manifest.json").read_bytes()).hexdigest()
    assert recomputed in digests["manifest.json"], (
        "the displayed manifest digest does not equal a fresh recomputation"
    )
    # payload entry: displayed == manifest-declared
    declared = json.loads((release / "manifest.json").read_bytes())["payload"]["sha256"]
    assert declared in digests["payload.zip"], (
        "the displayed payload digest is not the manifest-declared value"
    )
    # the payload digest is genuinely verified end-to-end by verify.py's check
    assert declared == hashlib.sha256((release / "payload.zip").read_bytes()).hexdigest()
    # and every href is raw-at-stamp under the row's versioned path
    for href, _name, _tail in listed:
        assert href.startswith(
            f"https://raw.githubusercontent.com/madeinoz67/benchweave-registry/{SHA}"
            "/releases/benchweave-registry/quarrystone-labs/alpha-meter/1.0.0/"
        ), href


def test_e2e_a_yanked_row_gets_no_record_page(tmp_path: Path) -> None:
    """The yank pin, extended: a yanked release drops from the index (CR-25)
    and with it its record page — no fragment for a row that is not there."""
    root, _private = _synthetic_repo(tmp_path)
    release = (
        root / "releases" / "benchweave-registry" / "quarrystone-labs"
        / "beta-probe" / "0.3.0"
    )
    manifest_digest = hashlib.sha256((release / "manifest.json").read_bytes()).hexdigest()
    (release / "status.json").write_text(
        json.dumps({
            "lifecycle": "yanked",
            "release": {
                "registry_id": "benchweave-registry",
                "package_id": "quarrystone-labs/beta-probe",
                "version": "0.3.0",
                "manifest_sha256": manifest_digest,
            },
            "advisories": [],
        })
    )
    dest = tmp_path / "site"
    result = _generate_site(root, dest)
    assert result.returncode == 0, result.stderr
    assert not (
        dest / "records" / "benchweave-registry" / "quarrystone-labs"
        / "beta-probe" / "0.3.0" / "index.html"
    ).exists(), "a yanked row must not get a record page"
    assert (
        dest / "records" / "benchweave-registry" / "quarrystone-labs"
        / "alpha-meter" / "1.0.0" / "index.html"
    ).is_file(), "the surviving row keeps its page"


def test_e2e_the_committed_tree_generates_its_own_record_page(tmp_path: Path) -> None:
    """The dogfood agreement: main() over the REAL tree renders the index
    page plus the committed release's record page, with its signature
    verified at generation time and its downloads bound to the real files."""
    dest = tmp_path / "site"
    result = _run([sys.executable, str(GENERATOR), "--dest", str(dest), "--sha", SHA])
    assert result.returncode == 0, result.stderr
    page_path = (
        dest / "records" / "benchweave-registry" / "madeinoz67" / "dps150" / "0.1.0" / "index.html"
    )
    assert page_path.is_file(), "the dogfood release's record page"
    page = page_path.read_text(encoding="utf-8")
    assert "Valid against the recorded ed25519 key" in page
    release = REPO / "releases" / "benchweave-registry" / "madeinoz67" / "dps150" / "0.1.0"
    listed = re.findall(r'<li><a href="([^"]+)">([a-z.-]+)</a>', page)
    on_disk = sorted(p.name for p in release.iterdir() if p.is_file())
    assert [name for _, name in listed] == on_disk, (
        f"the dogfood page's files must equal the real release dir: {on_disk}"
    )
    recomputed = hashlib.sha256((release / "manifest.json").read_bytes()).hexdigest()
    assert recomputed in page, "the dogfood manifest digest display drifted"
    assert (dest / "assets" / "htmx.min.js").is_file()


# ── issue #227 slice 5: the shared-listing record page (E2, E5) ──────────────
#
# A community-shared row gets its own record page: kind badge, the unverified
# marker, the publisher identity and the pinned source — and no release-class
# claim. The same fragment serves the standalone page (no JS) and the htmx
# drill-down (it is what #release-detail carries), so one render test covers
# both views.

SHARED_MARKER = "community-shared-not-reviewed"
SHARED_TITLE = "<title>Community-shared listing, BenchWeave Registry</title>"

#: Claims a release page makes and a shared-listing page must never make.
ADMITTED_CLASS_CLAIMS = (
    "Valid against the recorded ed25519 key",
    "Signed by",
    "Admitted release",
    "Open release files",
    "Release files",
    "Publication is not authorization. Admit this release",
    "Manifest SHA-256",
)

HARBORLINE_ENTRY: dict[str, Any] = {
    "publisher_id": "harborline-systems",
    "github": "harborline-example",
    "namespace": "harborline-systems",
    "vetted_at": "2026-10-02T00:00:00Z",
    "key_validity": {
        "not_before": "2026-01-01T00:00:00Z",
        "not_after": "2030-01-01T00:00:00Z",
    },
    "publisher_repo_protections": [
        {"protection": "push-protection", "state": "declared-not-verified"},
    ],
}


def _shared_page(row: dict[str, Any] | None = None, module: Any = None, **kwargs: Any) -> str:
    row = dict(row if row is not None else _row("harborline-systems/harborline-pwm"))
    return str(
        (module or _module()).render_record_page(
            row, HARBORLINE_ENTRY, [], SHA, _template(), **kwargs
        )
    )


def _assert_shared_page(page: str, row: dict[str, Any]) -> None:
    """The shared-row render test (E2, E5). Two callers: the positive arm and
    the reversion arm that removes the marker string."""
    assert "Community shared" in page, "the kind badge is missing"
    assert SHARED_MARKER in page, "the unverified marker is missing"
    assert "The author shared this entry." in page, "the shared notice is missing"
    assert row["publisher"] in page, "the publisher identity is missing"
    assert row["source_revision"] in page, "the pinned source revision is missing"
    assert f"{row['source_url']}/tree/{row['source_revision']}" in page, (
        "the pinned source is not one step away"
    )
    for claim in ADMITTED_CLASS_CLAIMS:
        assert claim not in page, f"a shared listing renders a release claim: {claim!r}"


def test_a_shared_row_renders_kind_marker_publisher_and_pinned_source() -> None:
    """E2: one step from the catalogue — the shared page shows the kind, the
    unverified marker with its explanation, the publisher identity and the
    pinned source (full revision, a link to it), under a title that does not
    call the entry a release."""
    row = _row("harborline-systems/harborline-pwm")
    page = _shared_page(row)
    _assert_shared_page(page, row)
    assert SHARED_TITLE in page
    assert (
        "The author shared this entry. The registry did not review it and did "
        "not check anything in it." in page
    ), "the marker explanation is missing"
    assert (
        "The author shared this entry. The registry did not review it and did "
        "not admit it. The registry did not check anything on this page." in page
    ), "the shared notice"
    assert "It covers the publisher identity only." in page
    assert f'data-bw-marker="{SHARED_MARKER}"' in page and ">Unverified<" in page
    assert f'href="{row["source_url"]}"' in page, "the repository link"
    assert ">BSD-3-Clause<" in page, "the declared licence"
    # pwm declares OTDP 0.2.1, adapter API 1.1 and STG 1.5 (the fixture row)
    assert ">0.2.1<" in page and ">1.1<" in page and ">1.5<" in page, "compatibility"
    assert "vetted 2026-10-02" in page, "the publisher's vetting date"


def test_the_marker_is_structural_on_the_shared_record_page() -> None:
    """E5: the marker renders from the row's KIND. A shared row whose own
    marker list is empty, or carries a foreign id, still renders it."""
    row = _row("harborline-systems/harborline-pwm")
    for planted in ([], ["future-marker-unmapped"], ["review-is-process-not-proof"]):
        page = _shared_page({**row, "unverified_markers": planted})
        _assert_shared_page(page, row)
        if "future-marker-unmapped" in planted:
            assert "future-marker-unmapped" in page, "a foreign marker still renders"


def test_e5_removing_the_marker_string_fails_the_render(tmp_path: Path) -> None:
    """The pre-committed kill (RED-sanity by mechanism reversion): with the
    marker string removed from the generator, the shared-row render test
    fails. The unmutated generator must pass it first — a reversion arm whose
    positive arm is already red proves nothing."""
    # The row's OWN marker list is emptied, so the generator is the marker's
    # only source: with the string removed, nothing else can supply it.
    row = _row("harborline-systems/harborline-pwm")
    stripped = {**row, "unverified_markers": []}
    _assert_shared_page(_shared_page(stripped), row)
    source = GENERATOR.read_text(encoding="utf-8")
    mutated = source.replace(SHARED_MARKER, "community-shared-marker-removed")
    assert mutated != source and SHARED_MARKER not in mutated, "the plant did not apply"
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    copy = sandbox / "generate_catalogue_page.py"
    copy.write_text(mutated, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("generate_catalogue_page_mutated", copy)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(AssertionError, match="unverified marker is missing"):
        _assert_shared_page(_shared_page(stripped, module=module), row)


def test_the_shared_page_keeps_the_honesty_arms_of_every_page() -> None:
    """The whole-page honesty discipline holds on the new page kind too: the
    footer negation paragraph pinned exact, no service-claim vocabulary
    outside it, no mark shapes unfired, the three bars fired."""
    for posture in (False, True):
        page = _shared_page(registry_mark=posture)
        assert page.count(FOOTER_PARAGRAPH) == 1
        assert_no_service_claim_vocabulary(page, f"the shared page (registry_mark={posture})")
        assert "<circle" not in page
        assert page.count("<rect") == (3 if posture else 0)
    plain = _shared_page()
    assert "bw:record begin" not in plain and "bw:provenance -->" not in plain
    assert f">{SHA[:12]}</span> · index v1" in plain
    # the footer negation is the phrase's only occurrence
    assert plain.lower().count("registry service") == 1


@pytest.mark.parametrize("url", ["http://example.invalid/anchor-meter", "javascript:alert(1)"])
def test_a_shared_row_with_a_non_https_source_refuses(url: str) -> None:
    """The pinned-source link is the one external link this slice builds from
    row data: a non-https source_url never reaches a page (the index schema
    refuses it upstream; the page generator refuses it again, typed)."""
    row = {**_row("harborline-systems/harborline-pwm"), "source_url": url}
    with pytest.raises(SystemExit, match=r"page_input_invalid: .*https source_url"):
        _shared_page(row)


def test_an_admitted_row_still_renders_the_release_page() -> None:
    """Scope guard: the release fragment is untouched for release rows — the
    kind dispatch is by kind only."""
    row = _row("northwind-instruments/northwind-psu")
    page = str(_module().render_record_page(row, PUBLISHER_ENTRY, FILES, SHA, _template()))
    assert "Admitted release" in page and "Open release files" in page
    assert SHARED_MARKER not in page and SHARED_TITLE not in page


def test_e2e_the_three_kind_tree_deploys_a_page_for_every_row(tmp_path: Path) -> None:
    """E2 end to end: the deploy writes a record page per index row — the
    shared listing's among them (the pre-slice deploy refused the whole site
    on a shared row: no release directory to list) — and the catalogue page's
    static rows are exactly the admitted signed release."""
    root = tmp_path / "repo"
    three_kind_tree(root, site_sources=True)
    generate(root)
    dest = tmp_path / "site"
    result = _run(
        [sys.executable, str(GENERATOR), "--root", str(root), "--dest", str(dest), "--sha", SHA]
    )
    assert result.returncode == 0, result.stderr
    page = (
        (dest / "records" / "benchweave-registry" / SHARED[0] / SHARED[1] / SHARED[2])
        .joinpath("index.html")
        .read_text(encoding="utf-8")
    )
    rows = rows_by_key(generate(root))
    _assert_shared_page(page, rows[f"{SHARED[0]}/{SHARED[1]}@{SHARED[2]}"])
    admitted = _deployed_page(dest, ADMITTED)
    assert "Valid against the recorded ed25519 key" in admitted, "the signed row still verifies"
    assert "Open release files" in admitted, "the admitted row keeps its release page"
    assert "In-tree fixture" in _deployed_page(dest, FIXTURE_RELEASE)
    catalogue = (dest / "index.html").read_text(encoding="utf-8")
    assert f'data-bw-package-id="{ADMITTED[0]}/{ADMITTED[1]}"' in catalogue
    assert f'data-bw-package-id="{SHARED[0]}/{SHARED[1]}"' not in catalogue, (
        "a shared listing reached the static default view"
    )


def test_e2e_a_signed_shared_row_refuses_and_nothing_deploys(tmp_path: Path) -> None:
    """A community-shared row can never be signed. The generator never emits
    one (the index schema refuses it); if one reaches the page generator the
    deploy refuses with a typed finding before it writes anything."""
    root = tmp_path / "repo"
    three_kind_tree(root, site_sources=True)
    generate(root)
    index_path = root / "index.json"
    document = json.loads(index_path.read_bytes())
    for row in document["rows"]:
        if row["kind"] == "community-shared":
            row["signature_state"] = "signed-valid"
    index_path.write_bytes(vr.canonical_bytes(document))
    dest = tmp_path / "site"
    result = _run(
        [sys.executable, str(GENERATOR), "--root", str(root), "--dest", str(dest), "--sha", SHA]
    )
    assert result.returncode != 0, "a signed community-shared row deployed"
    assert "page_input_invalid:" in result.stderr and "signed-valid" in result.stderr
    assert f"{SHARED[0]}/{SHARED[1]}/{SHARED[2]}" in result.stderr, "the refusal names the row"
    assert "Traceback" not in result.stderr
    assert not dest.exists() or not any(dest.iterdir()), "something deployed on refusal"


def _deployed_page(dest: Path, key: tuple[str, str, str]) -> str:
    """One deployed record page's text, read back from the site tree."""
    page = dest.joinpath("records", "benchweave-registry", *key, "index.html")
    assert page.is_file(), f"no record page deployed for {key}"
    return page.read_text(encoding="utf-8")
