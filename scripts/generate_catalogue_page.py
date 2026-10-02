#!/usr/bin/env python3
"""Generate the public plugin catalogue page from the generated index.

Issue #224 slice-2 pivot (registry-hosted catalogue, design record §3.1/§3.3):
the catalogue page is a DEPLOY-TIME artifact. The Pages workflow, on every
push to main, runs ``generate_index.py`` (records -> index bytes, identical
to the committed ``index.json`` by the standing ``--check``) and then this
generator renders the page from those bytes and deploys. A deploy of commit
X serves X's catalogue by construction: there is no committed page to
hand-edit, no sync window, and no stale-commit deploy path. The committed
tree carries the generator and the template (``catalogue/index.template.html``)
— both reviewable; the rendered page is never committed.

#224 follow-on (records table + drill-down): the cards grid becomes the
mockup's 8-column records table; version and compatibility stamp statically
in rows (row data is data under the narrowed literal discipline — only
structural chrome refuses literals); each row's name links to a standalone
record page (generated per index row by the same ``main()``), enhanced
in-place by the vendored htmx drill-down.

Provenance (A06): the page footer stamps the generating commit SHA
(``generated from <sha>``) so any third party can verify currency against
the repository. The stamp is a real sha or the generator refuses.

Default-view rule (CR-22, load-bearing): the static rows are exactly the
rows with ``kind == "admitted-release"`` AND ``signature_state ==
"signed-valid"``. Everything else is absent from the static bytes and
reachable only through explicit client-side filters (which render it with
its kind badge — CR-56). In-flight submissions are structurally absent
everywhere: the index is generated from ``releases/``, and a submission
only becomes a release at publish.

Literal discipline (pivot §4 row 8, narrowed): this repository carries NO
website-style literal gate — the index legitimately carries version strings
and row-derived free text (``display_name``, ``summary``, advisory ids,
``source_revision``) is DATA, exempt from any ban. What refuses is a
three-component version literal or a ``{{`` in the STRUCTURAL slots this
generator stamps: the template's chrome, the provenance stamp, the snapshot
line, the caption, the wordmark variants and the row chrome (the blank
render — the shape the rows fill). Per-row refusals (unknown ``kind``) name
the offending row.

Usage::

    python scripts/generate_catalogue_page.py --dest DIR --sha SHA [--root REPO]
        [--registry-mark]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote

REPO = Path(__file__).resolve().parents[1]

#: (R2, pivot §4) The digest/revision display truncation length — a TWIN of
#: ``catalogue/assets/plugins.js`` TRUNCATE_AT, pinned equal by
#: ``tests/test_catalogue_page.py``. One constant, two carriers.
TRUNCATE_AT = 12

#: The two slice-1 unverified markers' display strings (CR-37/NFR-S1). An
#: unknown marker id renders VERBATIM — forward-honest, never dropped. This
#: map is the generation-time authority; ``catalogue/assets/plugins.js``
#: carries a twin for cloned rows, pinned byte-equal by the page tests.
MARKER_DISPLAY: dict[str, str] = {
    "conformance-evidence-self-attested": "conformance evidence self-attested",
    "review-is-process-not-proof": "review is process, not proof",
}

#: The record page's marker EXPLANATIONS (§2.6) — a SINGLE-CARRIER map
#: (record pages are static; no JS clones them), seeded with the mockup's
#: two sentences. An unknown marker id renders its id with no explanation
#: line (forward-honest, CR-37 kin) — pinned by the record-page tests.
MARKER_EXPLANATION: dict[str, str] = {
    "conformance-evidence-self-attested": (
        "The publisher ran and reported the conformance evidence."
    ),
    "review-is-process-not-proof": (
        "Review followed the registry process; it does not prove behaviour."
    ),
}

#: Publisher repository protection ids -> display labels, and states ->
#: display text (the mockup renders `declared-not-verified` as "declared,
#: not verified"; any other state renders verbatim — forward-honest).
PROTECTION_LABELS: dict[str, str] = {
    "push-protection": "Push protection",
    "code-scanning": "Code scanning",
}
PROTECTION_STATE_DISPLAY: dict[str, str] = {
    "declared-not-verified": "declared, not verified",
}

#: Machine kind -> rendered badge text (CR-56: a row never renders without
#: it). A TWIN of the JS KIND_DISPLAY, pinned by the page tests.
KIND_DISPLAY: dict[str, str] = {
    "admitted-release": "Admitted release",
    "community-shared": "Community shared",
    "in-tree-fixture": "In-tree fixture",
}

#: Maintenance state -> rendered badge text and badge tone (the mockup's
#: tone remapping: maintained/maintenance-only neutral inset, unmaintained
#: amber, unknown muted outline). Twins of the JS maps.
MAINTENANCE_DISPLAY: dict[str, str] = {
    "maintained": "Maintained",
    "maintenance_only": "Maintenance only",
    "unmaintained": "Unmaintained",
    "unknown": "Unknown",
}
MAINTENANCE_BADGE: dict[str, str] = {
    "maintained": "badge-version",
    "maintenance_only": "badge-version",
    "unmaintained": "badge-warning",
    "unknown": "badge-muted",
}

EMPTY_CAPS = "None declared"
EMPTY_ADVISORIES = "None"
EMPTY_COMPAT = "none declared"
HONEST_EMPTY = "No published releases yet"

#: Explicit-none strings are DATA riding rows, not chrome — they contain no
#: version literals by construction and are exempt from the structural scan.

SEMVER_RE = re.compile(r"\d+\.\d+\.\d+")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SLUG_RE = re.compile(r"[^A-Za-z0-9-]")
BRACES = "{{"

CARDS_BEGIN = "<!-- bw:catalogue-cards begin -->"
CARDS_END = "<!-- bw:catalogue-cards end -->"
PROVENANCE_MARKER = "<!-- bw:provenance -->"
SNAPSHOT_MARKER = "<!-- bw:snapshot -->"
CAPTION_MARKER = "<!-- bw:caption -->"
WORDMARK_BEGIN = "<!-- bw:wordmark begin -->"
WORDMARK_END = "<!-- bw:wordmark end -->"
RECORD_BEGIN = "<!-- bw:record begin -->"
RECORD_END = "<!-- bw:record end -->"

#: The record page sits five directories below the site root
#: (records/<registry_id>/<publisher>/<plugin>/<version>/) — every asset
#: and the catalogue link resolve through this prefix (R10: relative only).
UP_PREFIX = "../" * 5

#: The admission notice, verbatim from the mockup (§2.6 — adopt unchanged).
ADMISSION_NOTICE = (
    "Publication is not authorization. Admit this release on your own bench "
    "through your gateway's local admission, pinned to the manifest digest above."
)

#: The honest-negative hardware line (§2.6 — derived, rendered iff no
#: hardware-evidence entry exists).
NO_HARDWARE_LINE = "No hardware evidence is recorded for this release."

_SVG_ATTRS = (
    'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"'
)

#: Lucide icon bodies (circle/rect-free rewrites where the raw Lucide mark
#: carries a <circle>/<rect> shape — §2.8's pre-committed pick: rewrite the
#: icon, keep the strict shape bans). Same bytes serve the static rows and
#: (§2.6) the record pages; ``catalogue/assets/plugins.js`` carries the twin
#: bodies for cloned rows.
ICONS: dict[str, str] = {
    "signature": (
        f'<svg width="18" height="18" {_SVG_ATTRS}>'
        '<path d="m21 17-2.156-1.868A.5.5 0 0 0 18 15.5v.5a1 1 0 0 1-1 1h-2a1 1 0 0 1-1-1'
        'c0-2.545-3.991-3.97-8.5-4a1 1 0 0 0 0 5c4.153 0 4.745-11.295 5.708-13.5a2.5 2.5 0'
        ' 1 1 3.31 3.284"></path><path d="M3 21h18"></path></svg>'
    ),
    "circle-dashed": (
        f'<svg width="18" height="18" {_SVG_ATTRS}>'
        '<path d="M10.1 2.182a10 10 0 0 1 3.8 0"></path>'
        '<path d="M13.9 21.818a10 10 0 0 1-3.8 0"></path>'
        '<path d="M17.609 3.721a10 10 0 0 1 2.69 2.7"></path>'
        '<path d="M2.182 13.9a10 10 0 0 1 0-3.8"></path>'
        '<path d="M20.279 17.609a10 10 0 0 1-2.7 2.69"></path>'
        '<path d="M21.818 10.1a10 10 0 0 1 0 3.8"></path>'
        '<path d="M3.721 6.391a10 10 0 0 1 2.7-2.69"></path>'
        '<path d="M6.391 20.279a10 10 0 0 1-2.69-2.7"></path></svg>'
    ),
    "globe": (
        f'<svg width="15" height="15" {_SVG_ATTRS}>'
        '<path d="M2 12a10 10 0 1 0 20 0 10 10 0 1 0-20 0"></path>'
        '<path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"></path>'
        '<path d="M2 12h20"></path></svg>'
    ),
    "cpu": (
        f'<svg width="15" height="15" {_SVG_ATTRS}>'
        '<path d="M12 20v2"></path><path d="M12 2v2"></path>'
        '<path d="M17 20v2"></path><path d="M17 2v2"></path>'
        '<path d="M2 12h2"></path><path d="M2 17h2"></path><path d="M2 7h2"></path>'
        '<path d="M20 12h2"></path><path d="M20 17h2"></path><path d="M20 7h2"></path>'
        '<path d="M7 20v2"></path><path d="M7 2v2"></path>'
        '<path d="M6 4h12a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z">'
        '</path><path d="M9 8h6a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z">'
        "</path></svg>"
    ),
    "hard-drive": (
        f'<svg width="15" height="15" {_SVG_ATTRS}>'
        '<path d="M10 16h.01"></path>'
        '<path d="M2.212 11.577a2 2 0 0 0-.212.896V18a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-5.527a2'
        ' 2 0 0 0-.212-.896L18.55 5.11A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"></path>'
        '<path d="M21.946 12.013H2.054"></path><path d="M6 16h.01"></path></svg>'
    ),
    "triangle-alert": (
        f'<svg width="13" height="13" {_SVG_ATTRS}>'
        '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3">'
        '</path><path d="M12 9v4"></path><path d="M12 17h.01"></path></svg>'
    ),
}

#: The record page's extra icons (breadcrumb chevron, digest copy button,
#: report-file link) — circle/rect-free like every icon on this site (§2.8).
ICONS["chevron-right"] = (
    f'<svg width="14" height="14" {_SVG_ATTRS}><path d="m9 18 6-6-6-6"></path></svg>'
)
ICONS["copy"] = (
    f'<svg width="14" height="14" {_SVG_ATTRS}>'
    '<path d="M10 8h10a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H10a2 2 0 0 1-2-2V10'
    'a2 2 0 0 1 2-2z"></path>'
    '<path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"></path></svg>'
)
ICONS["file"] = (
    f'<svg width="14" height="14" {_SVG_ATTRS}>'
    '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588'
    'A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"></path>'
    '<path d="M14 2v5a1 1 0 0 0 1 1h5"></path><path d="M10 9H8"></path>'
    '<path d="M16 13H8"></path><path d="M16 17H8"></path></svg>'
)

#: The Registry sub-brand wordmark variant (§2.8), shipped DARK behind
#: ``--registry-mark``. The three stack-glyph bars are the vendored
#: styleguide's own bytes (Sub-brands grid); the hexagon carries the
#: mockup's nav-scale stroke (1.6); colors stay fixed in both themes.
_REGISTRY_MARK_RECTS = (
    '<rect x="7" y="9.2" width="10" height="1.7" rx="0.85" fill="#FFB020"/>'
    '<rect x="7" y="12" width="10" height="1.7" rx="0.85" fill="#FFB020"/>'
    '<rect x="7" y="14.8" width="7" height="1.7" rx="0.85" fill="#FFB020"/>'
)
REGISTRY_WORDMARK = (
    '<a class="wordmark" href="#catalogue">\n'
    '    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden="true">\n'
    '      <path d="M12 2 L20.66 7 L20.66 17 L12 22 L3.34 17 L3.34 7 Z" stroke="#FFB020"'
    ' stroke-width="1.6"/>\n'
    f"      {_REGISTRY_MARK_RECTS}\n"
    "    </svg>\n"
    '    <span>BenchWeave</span><span class="mark-pill">Registry</span>\n'
    "  </a>"
)

#: The signed/unsigned titles, verbatim from the mockup (§2.4 — icon plus
#: visible text, never icon-only).
SIG_TITLE_SIGNED = (
    "Publisher signature valid against the key recorded for this publisher. "
    "Provenance, not a quality or safety claim."
)
SIG_TITLE_UNSIGNED = "No publisher signature. Provenance cannot be checked."

#: The table caption's fixed tail (the count is derived, §2.3).
CAPTION_TAIL = "Select a name for its provenance, evidence and files."


def _esc(text: str) -> str:
    """HTML-escape a row-derived value (index rows are data, never markup)."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _short(value: str) -> str:
    return value[:TRUNCATE_AT] + "…" if len(value) > TRUNCATE_AT else value


def row_key(row: dict[str, Any]) -> str:
    return f"{row.get('package_id') or ''}@{row.get('version') or ''}"


def detail_id(row: dict[str, Any]) -> str:
    """The row's detail-host element id — a slug of the row key (raw keys
    carry ``/`` and ``@``, which CSS selectors cannot take unescaped). A
    TWIN of the JS ``detailId``, pinned by the page tests."""
    return "bw-detail-" + SLUG_RE.sub("-", row_key(row))


def _refuse_detail_id_collisions(rows: list[dict[str, Any]]) -> None:
    """Fold F9 (lane B F3): the detail-host slug folds every
    non-``[A-Za-z0-9-]`` character to ``-``, so distinct index-schema-legal
    identities (``a-b/c`` and ``a/b-c`` at one version) can share one host
    id — two rows would then drill into ONE host. The schema cannot
    express this (both identities are legal); generation refuses, naming
    both rows."""
    hosts: dict[str, str] = {}
    for row in rows:
        host = detail_id(row)
        label = f"{row.get('registry_id')}/{row.get('package_id')}/{row.get('version')}"
        previous = hosts.get(host)
        if previous is not None:
            raise SystemExit(
                f"page_detail_id_collision: {previous} and {label} share detail "
                f"host #{host} — the host slug folds [^A-Za-z0-9-] to '-', and "
                "two rows would drill into one host"
            )
        hosts[host] = label


def record_url(row: dict[str, Any]) -> str:
    """The row's standalone record page URL, relative to the catalogue page
    (R10: relative only — the page serves from a Pages subroot)."""
    return (
        f"records/{row.get('registry_id') or ''}/{row.get('package_id') or ''}"
        f"/{row.get('version') or ''}/index.html"
    )


def _compat_text(row: dict[str, Any]) -> str:
    compat = row.get("compatibility") or {}
    parts: list[str] = []
    if compat.get("otdp_versions"):
        parts.append("OTDP " + ", ".join(str(v) for v in compat["otdp_versions"]))
    if compat.get("adapter_api_versions"):
        parts.append("adapter " + ", ".join(str(v) for v in compat["adapter_api_versions"]))
    if compat.get("stg_versions"):
        parts.append("STG " + ", ".join(str(v) for v in compat["stg_versions"]))
    return " · ".join(parts) if parts else EMPTY_COMPAT


def _sig_cell(row: dict[str, Any], *, blank: bool = False) -> str:
    if blank:
        return '<td class="td-sig" data-bw-slot="signature"></td>'
    if row.get("signature_state") == "signed-valid":
        return (
            '<td class="td-sig" data-bw-slot="signature">'
            f'<span class="sig sig-signed" title="{_esc(SIG_TITLE_SIGNED)}">'
            f"{ICONS['signature']}<span>Signed</span></span></td>"
        )
    return (
        '<td class="td-sig" data-bw-slot="signature">'
        f'<span class="sig sig-unsigned" title="{_esc(SIG_TITLE_UNSIGNED)}">'
        f"{ICONS['circle-dashed']}<span>Unsigned</span></span></td>"
    )


def _markers_text(row: dict[str, Any]) -> str:
    markers = row.get("unverified_markers") or []
    if not markers:
        return ""
    joined = "; ".join(MARKER_DISPLAY.get(str(m), str(m)) for m in markers)
    return f"Unverified: {joined}"


def _evidence_cell(row: dict[str, Any], *, blank: bool = False) -> str:
    if blank:
        return '<td class="td-evidence" data-bw-slot="evidence"></td>'
    entries = row.get("evidence") or []
    parts: list[str] = []
    for entry in entries:
        level = _esc(str(entry.get("level") or "unknown"))
        result = _esc(str(entry.get("result") or "unknown"))
        tone = "badge-version" if result == "passed" else "badge-danger"
        if result == "partial":
            tone = "badge-warning"
        parts.append(f'<span class="badge {tone}">{level} · {result}</span>')
    # none -> no badge (§2.3): the record page carries the explicit-none
    return (
        '<td class="td-evidence" data-bw-slot="evidence">'
        f'<div class="cell-stack">{"".join(parts)}</div></td>'
    )


def _caps_cell(row: dict[str, Any], *, blank: bool = False) -> str:
    if blank:
        return '<td class="td-caps" data-bw-slot="capabilities"></td>'
    caps = row.get("capabilities") or {}
    lines: list[str] = []
    if caps.get("network_egress"):
        lines.append(f'<span class="cap-line">{ICONS["globe"]}<span>Network egress</span></span>')
    if caps.get("subprocess_or_native_library"):
        lines.append(
            f'<span class="cap-line">{ICONS["cpu"]}'
            "<span>Subprocess or native library</span></span>"
        )
    if caps.get("filesystem_writes_beyond_evidence_retention"):
        lines.append(
            f'<span class="cap-line">{ICONS["hard-drive"]}<span>Filesystem writes</span></span>'
        )
    body = f'<div class="cell-stack">{"".join(lines)}</div>' if lines else (
        f'<span class="text-muted">{EMPTY_CAPS}</span>'
    )
    return f'<td class="td-caps" data-bw-slot="capabilities">{body}</td>'


def _advisories_cell(row: dict[str, Any], *, blank: bool = False) -> str:
    if blank:
        return '<td class="td-adv" data-bw-slot="advisories"></td>'
    advisories = row.get("advisories") or []
    if not advisories:
        return (
            '<td class="td-adv" data-bw-slot="advisories">'
            f'<span class="text-muted">{EMPTY_ADVISORIES}</span></td>'
        )
    count = len(advisories)
    noun = "advisory" if count == 1 else "advisories"
    return (
        '<td class="td-adv" data-bw-slot="advisories">'
        f'<span class="badge badge-danger">{ICONS["triangle-alert"]}'
        f"{count} {noun}</span></td>"
    )


def _row_html(row: dict[str, Any], *, blank: bool = False) -> str:
    """One table row (plus its hidden detail host row). ``blank`` renders the
    hidden template pair: the same shape with every slot empty, cloned by the
    page's JS for rows the static bytes do not carry (one shape source — this
    generator — serves both the generated and the on-demand rows)."""
    kind = str(row.get("kind") or "")
    package_id = str(row.get("package_id") or "")
    if not blank and kind not in KIND_DISPLAY:
        raise SystemExit(f"page_input_invalid: unknown kind {kind!r} ({package_id or 'row'})")
    url = "" if blank else _esc(record_url(row))
    host_id = "" if blank else _esc(detail_id(row))
    display = "" if blank else _esc(str(row.get("display_name") or ""))
    release_line = "" if blank else _esc(f"{package_id} · {row.get('version') or ''}")
    kind_text = "" if blank else KIND_DISPLAY[kind]
    markers = "" if blank else _esc(_markers_text(row))
    publisher = "" if blank else _esc(str(row.get("publisher") or ""))
    maintenance = "" if blank else str(row.get("maintenance") or "unknown")
    maintenance_badge = MAINTENANCE_BADGE.get(maintenance, "badge-muted")
    maintenance_text = MAINTENANCE_DISPLAY.get(maintenance, maintenance)
    compat = "" if blank else _esc(_compat_text(row))
    attrs = "" if blank else f' data-bw-package-id="{_esc(package_id)}"'
    hx = (
        ""
        if blank
        else f' hx-get="{url}" hx-select="#release-detail" hx-target="#{host_id}"'
        ' hx-swap="innerHTML" hx-push-url="true"'
    )
    return "\n".join(
        [
            f'<tr class="bw-row"{attrs}>',
            f"  {_sig_cell(row, blank=blank)}",
            '  <td class="td-release"><div class="release-cell">',
            f'    <a class="release-name" data-bw-slot="display-name" href="{url}"{hx}>'
            f"{display}</a>",
            '    <span class="release-line mono" data-bw-slot="release-line">'
            f"{release_line}</span>",
            '    <span class="release-tags">'
            f'<span class="badge badge-version" data-bw-slot="kind">{_esc(kind_text)}</span>'
            f'<span class="markers-inline" data-bw-slot="markers">{markers}</span>'
            "</span>",
            "  </div></td>",
            f'  <td class="td-pub mono" data-bw-slot="publisher">{publisher}</td>',
            f"  {_evidence_cell(row, blank=blank)}",
            f"  {_caps_cell(row, blank=blank)}",
            '  <td class="td-maint">'
            f'<span class="badge {maintenance_badge}" data-bw-slot="maintenance">'
            f"{_esc(maintenance_text)}</span></td>",
            f"  {_advisories_cell(row, blank=blank)}",
            f'  <td class="td-compat mono" data-bw-slot="compat">{compat}</td>',
            "</tr>",
            f'<tr class="bw-detail-row" hidden><td colspan="8">'
            f'<div class="bw-detail-host" id="{host_id}"></div></td></tr>',
        ]
    )


def _default_row(row: dict[str, Any]) -> bool:
    return row.get("kind") == "admitted-release" and row.get("signature_state") == "signed-valid"


def _rows_from(index_bytes: bytes) -> list[dict[str, Any]]:
    """Parse and shape-check the index; typed refusals, no bare tracebacks."""
    try:
        document: Any = json.loads(index_bytes)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SystemExit(f"page_input_invalid: index is not parseable JSON ({exc})") from exc
    if not isinstance(document, dict):
        raise SystemExit("page_input_invalid: index is not a JSON object")
    rows = document.get("rows")
    if not isinstance(rows, list):
        raise SystemExit("page_input_invalid: index carries no rows list")
    for row in rows:
        if not isinstance(row, dict):
            raise SystemExit("page_input_invalid: index row is not an object")
    return rows


def render_cards(index_bytes: bytes) -> str:
    """The rows block for the given index bytes (pure; no filesystem).

    The hidden template pair plus one row pair per default-view row; zero
    default rows render the honest-empty sentence instead — never an empty
    table. Row kinds outside ``KIND_DISPLAY`` refuse, naming the row.
    """
    rows = _rows_from(index_bytes)
    for row in rows:
        kind = row.get("kind")
        if kind not in KIND_DISPLAY:
            raise SystemExit(
                f"page_input_invalid: unknown kind {kind!r} "
                f"({row.get('package_id') or 'row'})"
            )
    defaults = [row for row in rows if _default_row(row)]
    parts = [f'<template data-bw-template>\n{_row_html({}, blank=True)}\n</template>']
    for row in defaults:
        parts.append(_row_html(row))
    if not defaults:
        parts.append(
            f'<tr class="bw-empty-row"><td colspan="8">{HONEST_EMPTY}</td></tr>'
        )
    return "\n".join(parts)


def _check_structural(text: str, what: str) -> None:
    """Refuse version literals and ``{{`` in a STRUCTURAL slot only.

    Row-derived free text is exempt by design (pivot §4 row 8): the index
    carries version strings legitimately, and a summary saying 'requires
    OTDP 0.2.2' is data, not a stamped claim. The records table's statically
    stamped version/compat cells are row DATA riding between the markers —
    only the blank row shape (the chrome) passes through here.
    """
    literals = SEMVER_RE.findall(text)
    if literals:
        raise SystemExit(
            f"page_literal_refused: {what} carries three-component version "
            f"literal(s) {sorted(set(literals))} — structural slots render "
            "versions from the index at runtime, never as stamped literals"
        )
    if BRACES in text:
        raise SystemExit(
            f"page_braces_refused: {what} carries a {{{{ delimiter — the "
            "template carries no stamp tokens at all"
        )


def _stamp_html(sha: str, index_version: int = 1) -> str:
    if not SHA_RE.match(sha):
        raise SystemExit(
            "page_input_invalid: --sha must be a full 40-hex commit sha "
            f"(got {sha!r}) — the provenance stamp never guesses"
        )
    return (
        f'generated from <span class="mono" data-bw-stamp="{sha}">'
        f"{sha[:TRUNCATE_AT]}</span> · index v{index_version}"
    )


def _caption_html(shown: int) -> str:
    noun = "release" if shown == 1 else "releases"
    return f"{shown} {noun}. {CAPTION_TAIL}"


def _snapshot_html(sha: str, shown: int, total: int, publishers: int) -> str:
    return (
        '<dl class="snapshot-dl">'
        f'<dt>snapshot</dt><dd class="mono">{sha[:TRUNCATE_AT]}</dd>'
        '<dt>releases</dt><dd class="mono">'
        f'<span data-bw-shown="{shown}">{shown}</span> shown of {total}</dd>'
        f'<dt>publishers</dt><dd class="mono" data-bw-publishers>{publishers} vetted</dd>'
        "</dl>"
    )


def render_page(
    index_bytes: bytes,
    template: str,
    sha: str,
    *,
    publisher_count: int = 0,
    registry_mark: bool = False,
) -> str:
    """The deployable page (pure; no filesystem, deterministic).

    Structural literal/braces discipline covers the template's chrome, the
    provenance stamp, the snapshot line, the caption, both wordmark variants
    and the row chrome (the blank render); the rows' data rides between the
    markers as data.
    """
    try:
        parsed_stamp = json.loads(index_bytes)
        index_version = (
            int(parsed_stamp.get("index_version", 1))
            if isinstance(parsed_stamp, dict)
            else 1
        )
    except (ValueError, UnicodeDecodeError, TypeError):
        # a malformed or non-object index refuses in render_cards with the
        # typed page_input_invalid: prefix — the stamp default never masks it
        index_version = 1
    rows = _rows_from(index_bytes)
    defaults = [row for row in rows if _default_row(row)]
    _check_structural(_row_html({}, blank=True), "the row chrome")
    _check_structural(_stamp_html(sha, index_version), "the provenance stamp")
    _check_structural(REGISTRY_WORDMARK, "the Registry wordmark variant")
    _check_structural(
        _snapshot_html(sha, len(defaults), len(rows), publisher_count), "the snapshot line"
    )
    _check_structural(_caption_html(len(defaults)), "the caption")
    for marker, what in (
        (CARDS_BEGIN, "bw:catalogue-cards begin"),
        (CARDS_END, "bw:catalogue-cards end"),
        (PROVENANCE_MARKER, "bw:provenance"),
        (SNAPSHOT_MARKER, "bw:snapshot"),
        (CAPTION_MARKER, "bw:caption"),
        (WORDMARK_BEGIN, "bw:wordmark begin"),
        (WORDMARK_END, "bw:wordmark end"),
    ):
        if template.count(marker) != 1:
            raise SystemExit(
                "page_input_invalid: catalogue/index.template.html does not carry "
                f"exactly one {what} marker"
            )
    head, rest = template.split(CARDS_BEGIN, 1)
    _, tail = rest.split(CARDS_END, 1)
    chrome = head + tail
    for marker in (PROVENANCE_MARKER, SNAPSHOT_MARKER, CAPTION_MARKER):
        chrome = chrome.replace(marker, "", 1)
    if not registry_mark:
        chrome = chrome.replace(WORDMARK_BEGIN, "", 1).replace(WORDMARK_END, "", 1)
    _check_structural(chrome, "catalogue/index.template.html (structural chrome)")
    cards = render_cards(index_bytes)
    page = head + cards + tail
    snapshot_html = _snapshot_html(sha, len(defaults), len(rows), publisher_count)
    page = page.replace(SNAPSHOT_MARKER, snapshot_html, 1)
    page = page.replace(CAPTION_MARKER, _caption_html(len(defaults)), 1)
    if registry_mark:
        _head, _sep, wordmark_end = page.partition(WORDMARK_BEGIN)
        _marked, _sep2, _tail2 = wordmark_end.partition(WORDMARK_END)
        page = _head + WORDMARK_BEGIN + "\n  " + REGISTRY_WORDMARK + "\n  " + WORDMARK_END
        page += _tail2
    else:
        # F10 (reviewer R3, the fold): the unfired render strips its
        # wordmark delimiters from the OUTPUT — pre-fold they were stripped
        # from the structural-check copy only and leaked into the served
        # page.
        page = page.replace(WORDMARK_BEGIN, "").replace(WORDMARK_END, "")
    return page.replace(PROVENANCE_MARKER, _stamp_html(sha, index_version), 1)


def _release_tree_url(row: dict[str, Any], sha: str) -> str:
    """The row's versionless release directory AT THE STAMPED COMMIT (R7 —
    the mockup's own target for report links and the Open-release-files
    button; the per-file downloads carry the exact versioned raw URLs)."""
    registry_id = str(row.get("registry_id") or "")
    package_id = str(row.get("package_id") or "")
    return (
        f"https://github.com/madeinoz67/benchweave-registry/tree/{sha}/releases"
        f"/{registry_id}/{package_id}"
    )


def _raw_file_url(row: dict[str, Any], sha: str, name: str) -> str:
    """One release file, raw at the STAMPED commit (§2.7 — exact bytes, zero
    deploy weight; no LFS in this repo, disclosed residual). The file NAME
    is percent-encoded (fold F5, lane A F4): a name carrying '#', '?', a
    space or non-ASCII truncated or corrupted the href — quote encodes it
    and the raw host decodes it back."""
    return (
        f"https://raw.githubusercontent.com/madeinoz67/benchweave-registry/{sha}"
        f"/releases/{row.get('registry_id') or ''}/{row.get('package_id') or ''}"
        f"/{row.get('version') or ''}/{quote(str(name), safe='')}"
    )


def _copy_button(value: str) -> str:
    return (
        f'<button type="button" class="copy-button" data-bw-copy="{_esc(value)}" '
        f'aria-label="Copy digest">{ICONS["copy"]}</button>'
    )


def _kv_row(key: str, value_html: str) -> str:
    return (
        f'<tr><th scope="row">{_esc(key)}</th><td>{value_html}</td></tr>'
    )


def _date_part(value: Any) -> str:
    return str(value or "")[:10]


def _record_fragment(
    row: dict[str, Any],
    publisher_entry: dict[str, Any],
    files: list[dict[str, str]],
    sha: str,
) -> str:
    """The record page's main fragment (pure; §2.10 — no filesystem): every
    field of §2.6's set against the row model, the publisher entry (the
    render-time join) and the enumerated release files."""
    publisher = str(row.get("publisher") or "")
    plugin = str(row.get("package_id") or "").split("/")[-1]
    tree_url = _esc(_release_tree_url(row, sha))
    chevron = ICONS["chevron-right"]
    breadcrumb = (
        '<nav class="breadcrumb" aria-label="Breadcrumb">'
        f'<a href="{UP_PREFIX}index.html">Catalogue</a>{chevron}'
        f'<span class="mono">{_esc(publisher)}</span>{chevron}'
        f'<span class="mono" aria-current="page">{_esc(plugin)}</span></nav>'
    )
    signed = row.get("signature_state") == "signed-valid"
    version_badge = (
        '<span class="badge badge-version mono">'
        f'{_esc(str(row.get("version") or ""))}</span>'
    )
    kind_badge = (
        '<span class="badge badge-version">'
        f'{_esc(KIND_DISPLAY.get(str(row.get("kind")), str(row.get("kind") or "")))}</span>'
    )
    if signed:
        sig_pill = (
            f'<span class="sig-pill" title="{_esc(SIG_TITLE_SIGNED)}">'
            f"{ICONS['signature']}Signed by {_esc(publisher)}</span>"
        )
        sig_row = (
            f'<span class="sig-line">{ICONS["signature"]}Valid against the '
            "recorded ed25519 key</span>"
        )
    else:
        sig_pill = (
            f'<span class="sig-pill sig-pill-unsigned" title="{_esc(SIG_TITLE_UNSIGNED)}">'
            f"{ICONS['circle-dashed']}Unsigned</span>"
        )
        sig_row = '<span class="muted">No publisher signature</span>'
    validity = publisher_entry.get("key_validity") or {}
    not_before = validity.get("not_before")
    not_after = validity.get("not_after")
    if not_before and not_after:
        key_validity = (
            f'<span class="mono">{_esc(_date_part(not_before))} to '
            f'{_esc(_date_part(not_after))}</span>'
        )
    else:
        # F7 (reviewer R1): key_validity is optional — an absent bound
        # renders the honest none-recorded, never an empty " to " window.
        key_validity = '<span class="muted">none recorded</span>'
    vetted = publisher_entry.get("vetted_at")
    vetted_html = (
        f' <span class="muted">vetted {_esc(_date_part(vetted))}</span>'
        if vetted
        else ""
    )
    timestamp = row.get("timestamp")
    if timestamp is None and row.get("timestamp_recommended"):
        timestamp_html = (
            '<span class="badge badge-warning">none recorded, recommended</span>'
        )
    elif timestamp is None:
        timestamp_html = '<span class="muted">none recorded</span>'
    else:
        timestamp_html = f'<span class="mono">{_esc(str(timestamp))}</span>'
    gateway_ref = row.get("gateway_ref")
    gateway_html = (
        f'<span class="mono" title="{_esc(str(gateway_ref))}">'
        f"{_esc(_short(str(gateway_ref)))}</span>"
        if gateway_ref
        else '<span class="muted">none recorded</span>'
    )
    source = str(row.get("source_revision") or "")
    manifest_digest = str(row.get("manifest_sha256") or "")
    provenance = "<table>" + "".join(
        [
            _kv_row(
                "Publisher",
                f'<span class="mono">{_esc(publisher)}</span>{vetted_html}',
            ),
            _kv_row("Signature", sig_row),
            _kv_row("Key validity", key_validity),
            _kv_row("Timestamp", timestamp_html),
            _kv_row(
                "Source revision",
                f'<span class="mono break-all">{_esc(source)}</span>'
                f"{_copy_button(source)}",
            ),
            _kv_row(
                "Manifest SHA-256",
                f'<span class="mono break-all">{_esc(manifest_digest)}</span>'
                f"{_copy_button(manifest_digest)}",
            ),
            _kv_row("Gateway ref", gateway_html),
            _kv_row(
                "Licence",
                f'<span class="mono">{_esc(str(row.get("licence_spdx") or ""))}</span>',
            ),
        ]
    ) + "</table>"

    evidence_rows: list[str] = []
    for entry in row.get("evidence") or []:
        result = _esc(str(entry.get("result") or "unknown"))
        tone = "badge-version" if result == "passed" else "badge-danger"
        if result == "partial":
            tone = "badge-warning"
        report_path = str(entry.get("report_path") or "")
        report_html = (
            f'<a class="report-link mono" href="{tree_url}">{ICONS["file"]}'
            f"{_esc(report_path)}</a>"
            if report_path
            else '<span class="muted">none recorded</span>'
        )
        evidence_rows.append(
            f"<tr><td>{_esc(str(entry.get('level') or 'unknown'))}</td>"
            f'<td><span class="badge {tone}">{result}</span></td>'
            f"<td>{report_html}</td></tr>"
        )
    if not evidence_rows:
        evidence_rows.append(
            '<tr><td colspan="3" class="muted">no test evidence recorded</td></tr>'
        )
    has_hardware = any(
        str(entry.get("level")) == "hardware" for entry in row.get("evidence") or []
    )
    hardware_line = "" if has_hardware else f"<p class=\"muted\">{NO_HARDWARE_LINE}</p>"

    compat = row.get("compatibility") or {}

    def _joined(values: Any) -> str:
        items = [str(v) for v in (values or [])]
        return f'<span class="mono">{_esc(", ".join(items))}</span>' if items else (
            '<span class="muted">none declared</span>'
        )

    triples = row.get("transport_triples") or []
    if triples:
        triple_html = "<br>".join(
            f'<span class="mono" title="{_esc(str(t.get("sha256")))}">'
            f"{_esc(str(t.get('id')))} · {_esc(str(t.get('version')))} · "
            f"{_esc(_short(str(t.get('sha256'))))}</span>"
            for t in triples
        )
    else:
        triple_html = '<span class="muted">None declared</span>'
    compatibility = "<table>" + "".join(
        [
            _kv_row("OTDP", _joined(compat.get("otdp_versions"))),
            _kv_row("Adapter API", _joined(compat.get("adapter_api_versions"))),
            _kv_row("STG", _joined(compat.get("stg_versions"))),
            _kv_row("Transport providers", triple_html),
        ]
    ) + "</table>"

    caps = row.get("capabilities") or {}

    def _yes_no(flag: Any) -> str:
        return "Yes" if flag else "No"

    capabilities = "<table>" + "".join(
        [
            _kv_row("Network egress", _yes_no(caps.get("network_egress"))),
            _kv_row(
                "Subprocess or native library",
                _yes_no(caps.get("subprocess_or_native_library")),
            ),
            _kv_row(
                "Filesystem writes beyond evidence retention",
                _yes_no(caps.get("filesystem_writes_beyond_evidence_retention")),
            ),
        ]
    ) + "</table>"

    marker_lines = []
    for marker in row.get("unverified_markers") or []:
        mid = str(marker)
        explanation = MARKER_EXPLANATION.get(mid)
        explanation_html = (
            f'<span class="muted">{_esc(explanation)}</span>' if explanation else ""
        )
        marker_lines.append(
            f'<span class="marker-row"><span class="badge badge-warning mono">'
            f"{_esc(mid)}</span>{explanation_html}</span>"
        )
    markers_html = (
        '<div class="marker-list">' + "".join(marker_lines) + "</div>"
        if marker_lines
        else '<p class="muted">none recorded</p>'
    )

    file_items: list[str] = []
    for entry in files:
        name = _esc(str(entry.get("name") or ""))
        href = _esc(_raw_file_url(row, sha, str(entry.get("name") or "")))
        digest = str(entry.get("digest") or "")
        digest_html = (
            f' <span class="mono break-all muted">{_esc(digest)}</span>'
            if digest
            else ""
        )
        file_items.append(f'<li><a href="{href}">{name}</a>{digest_html}</li>')
    files_html = (
        f'<ul class="file-list">{"".join(file_items)}</ul>' if file_items
        else '<p class="muted">none present</p>'
    )

    protections = publisher_entry.get("publisher_repo_protections") or []
    if protections:
        protection_rows = "".join(
            "<dt>"
            + _esc(
                PROTECTION_LABELS.get(
                    str(p.get("protection")), str(p.get("protection"))
                )
            )
            + "</dt><dd><span class=\"badge badge-warning\">"
            + _esc(
                PROTECTION_STATE_DISPLAY.get(
                    str(p.get("state")), str(p.get("state"))
                )
            )
            + "</span></dd>"
            for p in protections
        )
        protections_html = f"<dl>{protection_rows}</dl>"
    else:
        protections_html = '<p class="muted">none recorded</p>'

    advisories = row.get("advisories") or []
    if advisories:
        advisories_html = "".join(
            f'<span class="badge badge-danger mono">{_esc(str(a))}</span>' for a in advisories
        )
    else:
        advisories_html = "None"
    firmware = row.get("firmware_attestation")
    if firmware is None:
        firmware_html = '<span class="muted">No vendor attestation</span>'
    else:
        firmware_html = (
            f'<span class="mono">{_esc(str(firmware.get("vendor")))} · manifest '
            f"{_esc(str(firmware.get('manifest')))}</span>"
        )
    maintenance = str(row.get("maintenance") or "unknown")

    return "\n".join(
        [
            breadcrumb,
            '<div class="record-head">',
            f'<div class="badge-row">{version_badge}{kind_badge}{sig_pill}</div>',
            f"<h1>{_esc(str(row.get('display_name') or ''))}</h1>",
            f'<p class="summary">{_esc(str(row.get("summary") or ""))}</p>',
            "</div>",
            '<div class="record-grid">',
            '<div class="record-main">',
            '<section aria-labelledby="prov-h"><h2 id="prov-h">Provenance</h2>'
            f"{provenance}</section>",
            f'<section aria-labelledby="ev-h"><h2 id="ev-h">Evidence</h2>'
            f"<table>{''.join(evidence_rows)}</table>{hardware_line}</section>",
            f'<section aria-labelledby="compat-h"><h2 id="compat-h">Compatibility</h2>'
            f"{compatibility}</section>",
            f'<section aria-labelledby="caps-h"><h2 id="caps-h">Declared capabilities</h2>'
            f"{capabilities}</section>",
            f'<section aria-labelledby="unv-h"><h2 id="unv-h">Unverified markers</h2>'
            f"{markers_html}</section>",
            "</div>",
            '<aside class="record-aside">',
            '<div class="aside-card">',
            "<h2>Admission</h2>",
            f'<p class="muted">{ADMISSION_NOTICE}</p>',
            f'<a class="open-files-button" href="{tree_url}">Open release files'
            f"{ICONS['chevron-right']}</a>",
            f"<h3>Release files</h3>{files_html}",
            "</div>",
            '<div class="aside-card"><h2>Status</h2><dl>'
            f'<dt>Maintenance</dt><dd><span class="badge '
            f'{MAINTENANCE_BADGE.get(maintenance, "badge-muted")}">'
            f"{_esc(MAINTENANCE_DISPLAY.get(maintenance, maintenance))}</span></dd>"
            f"<dt>Advisories</dt><dd>{advisories_html}</dd>"
            f"<dt>Firmware</dt><dd>{firmware_html}</dd>"
            "</dl></div>",
            '<div class="aside-card"><h2>Publisher repository</h2>'
            f"{protections_html}</div>",
            "</aside>",
            "</div>",
        ]
    )


def render_record_page(
    row: dict[str, Any],
    publisher_entry: dict[str, Any],
    files: list[dict[str, str]],
    sha: str,
    template: str,
    *,
    index_version: int = 1,
    registry_mark: bool = False,
) -> str:
    """One deployable record page (pure; no filesystem, deterministic)."""
    for marker, what in (
        (RECORD_BEGIN, "bw:record begin"),
        (RECORD_END, "bw:record end"),
        (PROVENANCE_MARKER, "bw:provenance"),
        (WORDMARK_BEGIN, "bw:wordmark begin"),
        (WORDMARK_END, "bw:wordmark end"),
    ):
        if template.count(marker) != 1:
            raise SystemExit(
                "page_input_invalid: catalogue/record.template.html does not "
                f"carry exactly one {what} marker"
            )
    head, rest = template.split(RECORD_BEGIN, 1)
    _, tail = rest.split(RECORD_END, 1)
    chrome = head + tail
    for marker in (PROVENANCE_MARKER,):
        chrome = chrome.replace(marker, "", 1)
    if not registry_mark:
        chrome = chrome.replace(WORDMARK_BEGIN, "", 1).replace(WORDMARK_END, "", 1)
    _check_structural(chrome, "catalogue/record.template.html (structural chrome)")
    fragment = _record_fragment(row, publisher_entry, files, sha)
    # F10 (reviewer R3, the fold): the record begin/end markers are
    # generation-time delimiters — they do not ride the served page.
    page = head + fragment + tail
    if registry_mark:
        _head, _sep, rest2 = page.partition(WORDMARK_BEGIN)
        _marked, _sep2, tail2 = rest2.partition(WORDMARK_END)
        page = (
            _head + WORDMARK_BEGIN + "\n  " + REGISTRY_WORDMARK + "\n  "
            + WORDMARK_END + tail2
        )
    else:
        # F10: the unfired render strips its wordmark delimiters from the
        # output too (the fired posture keeps them — they wrap the
        # switched-in mark).
        page = page.replace(WORDMARK_BEGIN, "").replace(WORDMARK_END, "")
    return page.replace(PROVENANCE_MARKER, _stamp_html(sha, index_version), 1)


def _load_publishers(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "records" / "publishers.json"
    if not path.is_file():
        return {}
    try:
        document: Any = json.loads(path.read_bytes())
    except (ValueError, UnicodeDecodeError) as exc:
        raise SystemExit(
            f"page_input_invalid: records/publishers.json is not parseable JSON ({exc})"
        ) from exc
    publishers = document.get("publishers") if isinstance(document, dict) else None
    if not isinstance(publishers, list):
        return {}
    entries: dict[str, dict[str, Any]] = {}
    for entry in publishers:
        if isinstance(entry, dict) and entry.get("publisher_id"):
            entries[str(entry["publisher_id"])] = entry
    return entries


def _release_dir(root: Path, row: dict[str, Any]) -> Path:
    return (
        root / "releases" / str(row.get("registry_id") or "")
        / str(row.get("package_id") or "") / str(row.get("version") or "")
    )


def _release_files(root: Path, row: dict[str, Any]) -> list[dict[str, str]]:
    """Every regular file in the row's release directory (§2.7), sorted —
    the manifest entry displays the ROW's digest, the payload entry the
    MANIFEST-DECLARED archive digest, others link raw with no claim.
    Symlinks are skipped (fold F5, lane A F4): a symlink is not a release
    file, and listing one linked bytes the tree never published."""
    release_dir = _release_dir(root, row)
    if not release_dir.is_dir():
        raise SystemExit(
            "page_release_dir_missing: "
            f"{row.get('registry_id')}/{row.get('package_id')}/{row.get('version')}"
        )
    payload_digest = ""
    manifest_path = release_dir / "manifest.json"
    if manifest_path.is_file():
        try:
            declared: Any = json.loads(manifest_path.read_bytes()).get("payload", {})
            if isinstance(declared, dict):
                payload_digest = str(declared.get("sha256") or "")
        except (ValueError, UnicodeDecodeError):
            payload_digest = ""
    files: list[dict[str, str]] = []
    for path in sorted(
        p for p in release_dir.iterdir() if p.is_file() and not p.is_symlink()
    ):
        name = path.name
        digest = ""
        if name == "manifest.json":
            digest = str(row.get("manifest_sha256") or "")
        elif name == "payload.zip":
            digest = payload_digest
        files.append({"name": name, "digest": digest})
    return files


def _verify_row_signature(
    root: Path, row: dict[str, Any], publisher_entry: dict[str, Any]
) -> None:
    """§2.7's honesty upgrade: every row rendered as signed is VERIFIED at
    generation time with the clone verifier's own check
    (``verify.release_signature_verifies`` — the exact publisher-key-over-
    manifest.sig check ``scripts/verify.py`` performs). A mismatch is a
    typed refusal — a tampered signature never renders a page claiming
    validity, and nothing deploys."""
    import verify

    label = f"{row.get('registry_id')}/{row.get('package_id')}/{row.get('version')}"
    try:
        ok = verify.release_signature_verifies(
            root, str(row.get("publisher") or ""), _release_dir(root, row)
        )
    except ValueError as exc:
        # F4 (lane A F3, the fold): a corrupt recorded key body raises
        # ValueError from load_pem_public_key — a signature-path refusal,
        # typed and naming the row, never a bare traceback.
        raise SystemExit(
            f"page_signature_invalid: {label} — the publisher's recorded "
            f"ed25519_public_key_pem is not a parseable public key ({exc})"
        ) from exc
    if not ok:
        raise SystemExit(
            f"page_signature_invalid: {label} — the row claims signed-valid but "
            "its manifest.sig does not verify against the publisher's recorded "
            "key (or the key/signature files are absent)"
        )


def _publisher_entry_or_refuse(
    row: dict[str, Any], publishers: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    entry = publishers.get(str(row.get("publisher") or ""))
    if entry is None:
        raise SystemExit(
            f"page_publisher_unknown: {row.get('publisher')} "
            f"({row.get('package_id') or 'row'}) — the page never guesses a "
            "key or a vetting date"
        )
    return entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument("--dest", type=Path, required=True, help="deploy directory to write")
    parser.add_argument("--sha", required=True, help="the generating commit sha (40 hex)")
    parser.add_argument(
        "--registry-mark",
        action="store_true",
        help="ship the Registry sub-brand wordmark (§2.8 — dark by default; "
        "flips only on the owner's word)",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    dest = args.dest.resolve()
    template = (root / "catalogue" / "index.template.html").read_text(encoding="utf-8")
    record_template = (root / "catalogue" / "record.template.html").read_text(encoding="utf-8")
    index_bytes = (root / "index.json").read_bytes()
    publishers = _load_publishers(root)
    publisher_count = len(publishers)
    rows = _rows_from(index_bytes)
    try:
        index_version = int(json.loads(index_bytes)["index_version"])
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        index_version = 1
    # The verification pass runs BEFORE anything is written: a bad signature
    # refuses the whole deploy, not a fragment of it (§2.7 — nothing deploys).
    # The detail-host collision check rides the same pre-write pass (F9).
    _refuse_detail_id_collisions(rows)
    for row in rows:
        _publisher_entry_or_refuse(row, publishers)
        if row.get("signature_state") == "signed-valid":
            _verify_row_signature(root, row, publishers[str(row.get("publisher"))])
    page = render_page(
        index_bytes, template, args.sha,
        publisher_count=publisher_count, registry_mark=args.registry_mark,
    )
    (dest / "assets").mkdir(parents=True, exist_ok=True)
    (dest / "index.html").write_text(page, encoding="utf-8")
    (dest / "index.json").write_bytes(index_bytes)
    for asset, source in (
        ("plugins.js", root / "catalogue" / "assets" / "plugins.js"),
        ("catalogue.css", root / "catalogue" / "assets" / "catalogue.css"),
        ("htmx.min.js", root / "vendored" / "htmx" / "htmx.min.js"),
    ):
        (dest / "assets" / asset).write_bytes(source.read_bytes())
    written = 0
    for row in rows:
        entry = _publisher_entry_or_refuse(row, publishers)
        files = _release_files(root, row)
        record_page = render_record_page(
            row, entry, files, args.sha, record_template,
            index_version=index_version, registry_mark=args.registry_mark,
        )
        out = dest / record_url(row)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(record_page, encoding="utf-8")
        written += 1
    table_rows = page.count('class="bw-row"')
    print(
        f"generate_catalogue_page: wrote {dest}/index.html "
        f"({table_rows} row(s) incl. template) and {written} record page(s), "
        f"generated from {args.sha}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
