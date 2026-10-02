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
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
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
    no JS clones them) — seeded with the mockup's two sentences, and an
    unknown marker id renders its id with no explanation line."""
    module = _module()
    assert module.MARKER_EXPLANATION == {
        "conformance-evidence-self-attested": (
            "The publisher ran and reported the conformance evidence."
        ),
        "review-is-process-not-proof": (
            "Review followed the registry process; it does not prove behaviour."
        ),
    }
    plugins_js = (REPO / "catalogue" / "assets" / "plugins.js").read_text(encoding="utf-8")
    assert "MARKER_EXPLANATION" not in plugins_js, (
        "the explanation map grew a JS twin — record pages are static by design"
    )
    row = _row("harborline-systems/harborline-relay16")  # carries the unknown marker
    page = _render_record(row, FILES)
    assert "community-shared-not-vetted" in page
    unknown_row = re.search(
        r'<span class="badge badge-warning mono">community-shared-not-vetted'
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
    result = _run(
        [sys.executable, str(GENERATOR), "--dest", str(dest), "--sha", SHA]
    )
    assert result.returncode == 0, result.stderr
    page_path = (
        dest / "records" / "benchweave-registry" / "madeinoz67" / "dps150"
        / "0.1.0" / "index.html"
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
