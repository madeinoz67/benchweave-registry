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

Provenance (A06): the page footer stamps the generating commit SHA
(``generated from <sha>``) so any third party can verify currency against
the repository. The stamp is a real sha or the generator refuses.

Default-view rule (CR-22, load-bearing): the static cards are exactly the
rows with ``kind == "admitted-release"`` AND ``signature_state ==
"signed-valid"``. Everything else is absent from the static bytes and
reachable only through explicit client-side filters (which render it with
its kind tag — CR-56). In-flight submissions are structurally absent
everywhere: the index is generated from ``releases/``, and a submission
only becomes a release at publish.

Seven contract fields per row (CR-20 — rendered or explicitly "none"):
publisher; the immutable release id; compatibility (JS-filled, verbatim per
CR-19); licence and provenance; test evidence; maintenance; advisories.
Unverified markers render via ``MARKER_DISPLAY`` (the two slice-1 markers);
any unknown marker id renders verbatim — forward-honest, never dropped.

Literal discipline (pivot §4 row 8, narrowed): this repository carries NO
website-style literal gate — the index legitimately carries version strings
and row-derived free text (``display_name``, ``summary``, advisory ids,
``source_revision``) is DATA, exempt from any ban. What refuses is a
three-component version literal or a ``{{`` in the STRUCTURAL slots this
generator stamps: the template's chrome, the provenance stamp, and the card
chrome (the blank render — the shape the rows fill). Per-row refusals
(unknown ``kind``) name the offending row.

Usage::

    python scripts/generate_catalogue_page.py --dest DIR --sha SHA [--root REPO]
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

#: Machine kind -> rendered tag text (CR-56: a row never renders without it).
KIND_DISPLAY: dict[str, str] = {
    "admitted-release": "admitted-release",
    "community-shared": "community-shared",
    "in-tree-fixture": "in-tree-fixture",
}

#: Maintenance state -> badge class (unknown is the muted pill).
MAINTENANCE_BADGE: dict[str, str] = {
    "maintained": "badge-success",
    "maintenance_only": "badge-warning",
    "unmaintained": "badge-danger",
    "unknown": "badge-version",
}

EMPTY_EVIDENCE = "no test evidence"
EMPTY_ADVISORIES = "no advisories"
HONEST_EMPTY = "No published releases yet"

SEMVER_RE = re.compile(r"\d+\.\d+\.\d+")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
BRACES = "{{"

CARDS_BEGIN = "<!-- bw:catalogue-cards begin -->"
CARDS_END = "<!-- bw:catalogue-cards end -->"
PROVENANCE_MARKER = "<!-- bw:provenance -->"


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


def _release_dir_url(row: dict[str, Any], ref: str) -> str:
    """The versionless releases directory of the row's package AT THE STAMPED
    COMMIT (fold R7, critic F6): the page's click-through must show the exact
    bytes the page was generated from, matching the footer's `generated from
    <sha>` verifiability claim — a `main` link quietly drifts to whatever
    main holds today. The page's wiring upgrades the href to the exact
    version directory at runtime."""
    registry_id = str(row.get("registry_id") or "")
    package_id = str(row.get("package_id") or "")
    return (
        f"https://github.com/madeinoz67/benchweave-registry/tree/{ref}/releases"
        f"/{registry_id}/{package_id}"
    )


def _evidence_html(row: dict[str, Any]) -> str:
    entries = row.get("evidence") or []
    parts: list[str] = []
    for entry in entries:
        level = _esc(str(entry.get("level") or "unknown"))
        result = _esc(str(entry.get("result") or "unknown"))
        tone = "badge-success" if result == "passed" else "badge-danger"
        if result == "partial":
            tone = "badge-warning"
        parts.append(f'<span class="badge {tone}">{level} · {result}</span>')
        path = entry.get("report_path")
        if path:
            parts.append(f"<code>{_esc(str(path))}</code>")
    if not parts:
        parts.append(f'<span class="text-muted">{EMPTY_EVIDENCE}</span>')
    return " ".join(parts)


def _advisories_html(row: dict[str, Any]) -> str:
    advisories = row.get("advisories") or []
    if not advisories:
        return f'<span class="text-muted">{EMPTY_ADVISORIES}</span>'
    return " ".join(
        f'<span class="badge badge-danger">{_esc(str(item))}</span>' for item in advisories
    )


def _markers_html(row: dict[str, Any]) -> str:
    markers = row.get("unverified_markers") or []
    return " ".join(
        f'<span class="badge badge-warning">{_esc(MARKER_DISPLAY.get(str(m), str(m)))}</span>'
        for m in markers
    )


def _card(row: dict[str, Any], *, sha: str, blank: bool = False) -> str:
    """One catalogue card. ``blank`` renders the hidden template card: the
    same shape with every slot empty, cloned by the page's JS for rows the
    static bytes do not carry (so one shape source — this generator —
    serves both the generated and the on-demand cards). ``sha`` pins the
    card's release link to the stamped commit (fold R7)."""
    kind = str(row.get("kind") or "")
    package_id = str(row.get("package_id") or "")
    if not blank and kind not in KIND_DISPLAY:
        raise SystemExit(f"page_input_invalid: unknown kind {kind!r} ({package_id or 'row'})")
    values: dict[str, str] = {
        "display-name": "" if blank else str(row.get("display_name") or ""),
        "summary": "" if blank else str(row.get("summary") or ""),
        "publisher": "" if blank else str(row.get("publisher") or ""),
        "licence": "" if blank else str(row.get("licence_spdx") or ""),
        "release-id": ""
        if blank
        else f"{row.get('registry_id') or ''}/{row.get('package_id') or ''}",
        "source-revision": "" if blank else str(row.get("source_revision") or ""),
    }
    maintenance = "" if blank else str(row.get("maintenance") or "unknown")
    badge = MAINTENANCE_BADGE.get(maintenance, "badge-version")
    kind_text = "" if blank else KIND_DISPLAY[kind]
    summary = _esc(values["summary"])
    source = values["source-revision"]
    source_title = "" if blank else f' title="{_esc(source)}"'
    source_text = "" if blank else _short(source)
    attrs = (
        "" if blank else f' data-bw-package-id="{_esc(str(row.get("package_id") or ""))}"'
    )
    evidence = "" if blank else _evidence_html(row)
    advisories = "" if blank else _advisories_html(row)
    markers = "" if blank else _markers_html(row)
    head = (
        '<div class="spec-head">'
        f'<h4 data-bw-slot="display-name">{_esc(values["display-name"])}</h4>'
        '<span class="badge badge-version" data-bw-slot="version" hidden></span>'
        "</div>"
    )
    meta_identity = (
        '<p class="catalogue-meta">'
        f'<span data-bw-slot="publisher">{_esc(values["publisher"])}</span> · '
        f'<span data-bw-slot="licence">{_esc(values["licence"])}</span> · '
        f'<span class="badge {badge}" data-bw-slot="maintenance">{_esc(maintenance)}</span> · '
        f'<span class="badge badge-info" data-bw-slot="kind">{_esc(kind_text)}</span>'
        "</p>"
    )
    meta_release = (
        '<p class="catalogue-meta">'
        f'<span class="mono" data-bw-slot="release-id">{_esc(values["release-id"])}</span> · '
        '<span class="mono" data-bw-slot="digest" hidden></span>'
        "</p>"
    )
    meta_source = (
        '<p class="catalogue-meta">source: '
        f'<span class="mono" data-bw-slot="source-revision"{source_title}>'
        f"{_esc(source_text)}</span></p>"
    )
    evidence_link = (
        '<a class="spec-link" data-bw-slot="evidence-link" '
        f'href="{_esc(_release_dir_url(row, sha))}">release files →</a>'
    )
    return "\n".join(
        [
            # The opening tag is closed here — the relocated renderer's
            # unclosed `{attrs}` shape (pivot §4 row 1, HIGH) put 13 of 15
            # slots outside the card in a real browser; the DOM-containment
            # test in tests/test_catalogue_page.py is the standing guard.
            f'<div class="spec-card"{attrs}>',
            head,
            f'<p data-bw-slot="summary">{summary}</p>',
            meta_identity,
            meta_release,
            '<p class="catalogue-meta" data-bw-slot="compat" hidden></p>',
            f'<p class="catalogue-meta">evidence: <span data-bw-slot="evidence">'
            f"{evidence}</span> {evidence_link}</p>",
            f'<p class="catalogue-meta">advisories: '
            f'<span data-bw-slot="advisories">{advisories}</span></p>',
            f'<p class="catalogue-meta">unverified: '
            f'<span data-bw-slot="markers">{markers}</span></p>',
            meta_source,
            "</div>",
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


def render_cards(index_bytes: bytes, sha: str) -> str:
    """The cards block for the given index bytes (pure; no filesystem).

    The hidden template card plus one card per default-view row; zero
    default rows render the honest-empty sentence instead — never an empty
    page. Row kinds outside ``KIND_DISPLAY`` refuse, naming the row. The
    ``sha`` pins every card's release link to the stamped commit (R7).
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
    parts = [f'<template data-bw-template>\n{_card({}, blank=True, sha=sha)}\n</template>']
    for row in defaults:
        parts.append(_card(row, sha=sha))
    if not defaults:
        parts.append(f'<p class="catalogue-empty-static">{HONEST_EMPTY}</p>')
    return "\n".join(parts)


def _check_structural(text: str, what: str) -> None:
    """Refuse version literals and ``{{`` in a STRUCTURAL slot only.

    Row-derived free text is exempt by design (pivot §4 row 8): the index
    carries version strings legitimately, and a summary saying 'requires
    OTDP 0.2.2' is data, not a stamped claim.
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


def render_page(index_bytes: bytes, template: str, sha: str) -> str:
    """The deployable page (pure; no filesystem, deterministic).

    Structural literal/braces discipline covers the template's chrome, the
    provenance stamp and the card chrome (the blank render); the cards'
    row data rides between the markers as data.
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
    _check_structural(_card({}, blank=True, sha=sha), "the card chrome")
    _check_structural(_stamp_html(sha, index_version), "the provenance stamp")
    if template.count(CARDS_BEGIN) != 1 or template.count(CARDS_END) != 1:
        raise SystemExit(
            "page_input_invalid: catalogue/index.template.html does not carry "
            "exactly one bw:catalogue-cards marker pair"
        )
    if template.count(PROVENANCE_MARKER) != 1:
        raise SystemExit(
            "page_input_invalid: catalogue/index.template.html does not carry "
            "exactly one bw:provenance marker"
        )
    head, rest = template.split(CARDS_BEGIN, 1)
    _, tail = rest.split(CARDS_END, 1)
    chrome = head + tail.replace(PROVENANCE_MARKER, "", 1)
    _check_structural(chrome, "catalogue/index.template.html (structural chrome)")
    cards = render_cards(index_bytes, sha)
    page = head + cards + tail
    return page.replace(PROVENANCE_MARKER, _stamp_html(sha, index_version), 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument("--dest", type=Path, required=True, help="deploy directory to write")
    parser.add_argument("--sha", required=True, help="the generating commit sha (40 hex)")
    args = parser.parse_args()
    root = args.root.resolve()
    dest = args.dest.resolve()
    template = (root / "catalogue" / "index.template.html").read_text(encoding="utf-8")
    index_bytes = (root / "index.json").read_bytes()
    page = render_page(index_bytes, template, args.sha)
    (dest / "assets").mkdir(parents=True, exist_ok=True)
    (dest / "index.html").write_text(page, encoding="utf-8")
    (dest / "index.json").write_bytes(index_bytes)
    (dest / "assets" / "plugins.js").write_bytes(
        (root / "catalogue" / "assets" / "plugins.js").read_bytes()
    )
    (dest / "assets" / "catalogue.css").write_bytes(
        (root / "catalogue" / "assets" / "catalogue.css").read_bytes()
    )
    cards = page.count('class="spec-card"')
    print(
        f"generate_catalogue_page: wrote {dest}/index.html "
        f"({cards} card(s) incl. template, generated from {args.sha})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
