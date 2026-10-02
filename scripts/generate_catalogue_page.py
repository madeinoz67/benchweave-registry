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
    return page.replace(PROVENANCE_MARKER, _stamp_html(sha, index_version), 1)


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
    index_bytes = (root / "index.json").read_bytes()
    publishers_path = root / "records" / "publishers.json"
    publisher_count = 0
    if publishers_path.is_file():
        try:
            publishers = json.loads(publishers_path.read_bytes()).get("publishers", [])
            publisher_count = len(publishers) if isinstance(publishers, list) else 0
        except (ValueError, UnicodeDecodeError):
            raise SystemExit(
                "page_input_invalid: records/publishers.json is not parseable JSON"
            ) from None
    page = render_page(
        index_bytes, template, args.sha,
        publisher_count=publisher_count, registry_mark=args.registry_mark,
    )
    (dest / "assets").mkdir(parents=True, exist_ok=True)
    (dest / "index.html").write_text(page, encoding="utf-8")
    (dest / "index.json").write_bytes(index_bytes)
    for asset in ("plugins.js", "catalogue.css", "htmx.min.js"):
        (dest / "assets" / asset).write_bytes(
            (root / "catalogue" / "assets" / asset).read_bytes()
            if asset != "htmx.min.js"
            else (root / "vendored" / "htmx" / "htmx.min.js").read_bytes()
        )
    rows = page.count('class="bw-row"')
    print(
        f"generate_catalogue_page: wrote {dest}/index.html "
        f"({rows} row(s) incl. template, generated from {args.sha})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
