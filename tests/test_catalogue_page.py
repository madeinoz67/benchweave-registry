"""The catalogue page contract (issue #224 slice-2 pivot §3.1/§3.3/§4/§5).

The page is a DEPLOY-TIME artifact (never committed), so the discipline is
structural: these arms render the page from the committed template plus the
committed index (or the 10-row fixture) and pin the properties the deploy
must not lose — DOM containment (the §4 row 1 HIGH's standing guard: every
slot inside its card), the default-view rule (B3'), the CR-20 field
contract, the narrowed literal refusal (§4 row 8: row free text is data),
the whole-page honesty scan (B3'), the provenance stamp (A06), and the
Python/JS twin constants (R2). The deploy-gate browser arm
(scripts/verify_catalogue_browser.py in the Pages workflow) is the
wiring-level companion.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
from collections.abc import Iterator
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[1]
GENERATOR = REPO / "scripts" / "generate_catalogue_page.py"
TEMPLATE = REPO / "catalogue" / "index.template.html"
PLUGINS_JS = REPO / "catalogue" / "assets" / "plugins.js"
FIXTURE = REPO / "tests" / "fixtures" / "plugins-index.fixture.json"
INDEX = REPO / "index.json"

SHA = "0" * 39 + "1"  # invented 40-hex sha for render tests

# The records-table row slots (the #224 follow-on's column set — the CR-20
# field contract itself moves to the record page, whose arms live in
# tests/test_catalogue_record.py). Rendered or explicitly none.
ROW_SLOTS = (
    "display-name",
    "release-line",
    "publisher",
    "kind",
    "markers",
    "signature",
    "evidence",
    "capabilities",
    "maintenance",
    "advisories",
    "compat",
)

# The table's eight columns, in order (the mockup's set, §2.3).
COLUMNS = (
    "Signature",
    "Release",
    "Publisher",
    "Evidence",
    "Declared capabilities",
    "Maintenance",
    "Advisories",
    "Compatibility",
)

# The Registry sub-brand mark's three stack-glyph bars, extracted from the
# vendored styleguide's Sub-brands grid (§2.8: the fired posture's rects are
# byte-matched against the vendored spec, never retyped).
VENDORED_STYLEGUIDE = REPO / "vendored" / "gateway" / "public-site-styleguide.html"

# The lede (B3', amended by the #224 follow-on §5): the mockup's wording —
# pinned so a drift toward a service claim reddens. It makes no service claim.
LEDE = (
    "Published plugin releases, rendered from the registry repository of record. "
    "Publication is discovery and provenance, never authorization: installing a "
    "plugin stays local admission on your own bench."
)

# The pinned footer negation (the honesty amendment, §5): "registry service"
# may appear ONLY here, in honest negation, exactly once. The rendered form
# carries the anchor on "registry repository of record"; the pin is against
# the artifact's real bytes.
FOOTER_SENTENCE = (
    "Rendered view of the "
    '<a href="https://github.com/madeinoz67/benchweave-registry">'
    "registry repository of record</a>. There is no hosted registry service."
)


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("generate_catalogue_page", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _render(
    index_bytes: bytes, sha: str = SHA, *, publisher_count: int = 0, registry_mark: bool = False
) -> str:
    return str(
        _module().render_page(
            index_bytes, _template(), sha,
            publisher_count=publisher_count, registry_mark=registry_mark,
        )
    )


def _cards(page: str) -> list[str]:
    return page.split('data-bw-package-id="')[1:]


# ── DOM containment (§4 row 1 — the HIGH's standing guard) ────────────────────


class _Node:
    __slots__ = ("tag", "attrs", "parent", "children")

    def __init__(self, tag: str, attrs: dict[str, str], parent: _Node | None) -> None:
        self.tag = tag
        self.attrs = attrs
        self.parent = parent
        self.children: list[_Node] = []


_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}


class _Tree(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.roots: list[_Node] = []
        self.stack: list[_Node] = []

    def _add(self, tag: str, attrs: list[tuple[str, str | None]]) -> _Node:
        clean = {key: (value or "") for key, value in attrs}
        node = _Node(tag, clean, self.stack[-1] if self.stack else None)
        (self.stack[-1].children if self.stack else self.roots).append(node)
        return node

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = self._add(tag, attrs)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._add(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return


def _parse(html: str) -> list[_Node]:
    tree = _Tree()
    tree.feed(html)
    tree.close()
    return tree.roots


def _walk(nodes: list[_Node]) -> Iterator[_Node]:
    for node in nodes:
        yield node
        yield from _walk(node.children)


def _ancestor_classes(node: _Node) -> list[str]:
    classes: list[str] = []
    current = node.parent
    while current is not None:
        classes.append(current.attrs.get("class", ""))
        current = current.parent
    return classes


def assert_dom_containment(html: str) -> None:
    """Every data-bw-slot descends from its table row (``tr.bw-row``); every
    row is either the hidden template shape or a package-identified row; every
    row carries its kind slot inside the Release cell (§5's reshaped
    containment arm — the unclosed-tag HIGH's standing guard, table form).
    Substring containment proves none of this — an unclosed row opening tag
    leaves the slots parsed-but-orphaned."""
    nodes = list(_walk(_parse(html)))
    slots = [n for n in nodes if "data-bw-slot" in n.attrs]
    assert slots, "precondition: the page carries slot elements"
    for slot in slots:
        classes = _ancestor_classes(slot)
        assert any("bw-row" in c.split() for c in classes), (
            f"slot data-bw-slot={slot.attrs['data-bw-slot']!r} does not descend "
            "from its tr.bw-row (an unclosed row opening tag?)"
        )
    rows = [n for n in nodes if n.tag == "tr" and "bw-row" in n.attrs.get("class", "").split()]
    assert rows, "precondition: the page carries rows"
    for row in rows:
        in_template = any(ancestor.tag == "template" for ancestor in _ancestors(row))
        assert in_template or row.attrs.get("data-bw-package-id"), (
            "a row carries neither the template shape nor a package id"
        )
        release_cells = [
            child
            for child in _walk(row.children)
            if child.tag == "td" and "td-release" in child.attrs.get("class", "").split()
        ]
        assert release_cells, (
            f"row {row.attrs.get('data-bw-package-id', '(template)')} has no Release cell"
        )
        kinds = [
            child
            for child in _walk(release_cells[0].children)
            if child.attrs.get("data-bw-slot") == "kind"
        ]
        assert kinds, (
            f"row {row.attrs.get('data-bw-package-id', '(template)')} has no kind "
            "badge inside its Release cell (CR-56)"
        )


def _ancestors(node: _Node) -> Iterator[_Node]:
    current = node.parent
    while current is not None:
        yield current
        current = current.parent


def test_dom_containment_on_the_fixture_page() -> None:
    """The standing guard for the unclosed-tag HIGH: on the fixture page
    (6 default rows + template), every slot sits inside its row."""
    assert_dom_containment(_render(FIXTURE.read_bytes()))


def test_dom_containment_on_the_committed_index_page() -> None:
    assert_dom_containment(_render(INDEX.read_bytes()))


def test_dom_containment_on_the_empty_catalogue() -> None:
    """Zero rows still parses and carries no orphan slots."""
    assert_dom_containment(_render(b'{"index_version": 1, "rows": []}'))


# ── default view, CR-20, kind tags (B3') ──────────────────────────────────────


def test_default_page_excludes_non_default_kinds_and_unsigned() -> None:
    """B3's honesty arm on the fixture: the static cards are exactly the
    admitted-release + signed-valid rows. A community-shared row, an
    in-tree-fixture row, and an admitted-but-UNSIGNED row are all absent
    from the static bytes (reachable only through explicit filters, which
    the node lane proves always tag them)."""
    page = _render(FIXTURE.read_bytes())
    for pid in (
        "copperleaf-labs/copperleaf-daq",
        "copperleaf-labs/copperleaf-shunt",
        "copperleaf-labs/copperleaf-therm",
        "northwind-instruments/northwind-load",
        "northwind-instruments/northwind-psu",
        "northwind-instruments/northwind-scope",
    ):
        assert f'data-bw-package-id="{pid}"' in page, f"default row missing: {pid}"
    for pid in (
        "harborline-systems/harborline-relay",  # admitted-release but unsigned
        "harborline-systems/harborline-relay16",  # community-shared
        "harborline-systems/harborline-pwm",  # community-shared + unsigned
        "northwind-instruments/northwind-cal",  # admitted-release + hardware evidence, but unsigned
        "northwind-instruments/northwind-fixture",  # in-tree-fixture
    ):
        assert f'data-bw-package-id="{pid}"' not in page, f"non-default row rendered: {pid}"


def test_static_rows_carry_the_column_slots() -> None:
    """The reshaped structural arm: every static row carries the column
    slots (rendered or the table's explicit-none form)."""
    page = _render(FIXTURE.read_bytes())
    cards = _cards(page)
    assert len(cards) == 6, f"the fixture's default view is 6 rows, got {len(cards)}"
    for card in cards:
        for slot in ROW_SLOTS:
            assert f'data-bw-slot="{slot}"' in card, f"row lacks column slot {slot}"


def test_the_table_carries_the_mockups_eight_columns() -> None:
    """B-T's column arm: exactly the mockup's eight columns, in order."""
    page = _render(FIXTURE.read_bytes())
    head = page.split("<thead>", 1)[1].split("</thead>", 1)[0]
    headers = re.findall(r"<th[^>]*>([^<]+)</th>", head)
    assert tuple(headers) == COLUMNS, headers


def test_every_default_row_is_kind_badged_in_the_release_cell() -> None:
    """CR-56's static half, scoped (§5): a row never renders without its
    kind badge — inside the Release cell, in the mockup's display case."""
    page = _render(FIXTURE.read_bytes())
    for card in _cards(page):
        release = card.split('class="td-release"', 1)[1]
        assert 'data-bw-slot="kind"' in release and "Admitted release" in release


def test_every_static_row_is_signed_with_icon_and_text_and_title() -> None:
    """B-T/B-I's static half: default rows are signed by definition — the
    signature cell carries the Lucide signature icon, the visible text
    'Signed', and the provenance title verbatim (never icon-only)."""
    page = _render(FIXTURE.read_bytes())
    for card in _cards(page):
        sig = card.split('class="td-sig"', 1)[1].split("</td>", 1)[0]
        assert "<svg" in sig, "a static row's signature cell lost its icon"
        assert ">Signed<" in sig, "a static row's signature cell lost its visible text"
        assert "Publisher signature valid against the key recorded for this publisher." in card
        assert "sig-unsigned" not in card, (
            "an unsigned cell rendered in the static default view (the legend's "
            "'Unsigned' word is fine; the cell class is the discriminator)"
        )


def test_version_and_compatibility_stamp_statically_in_rows() -> None:
    """B-T (mockup-driven): rows stamp version and compatibility as static
    data (§2.3) — the release line carries package and version, the compat
    cell carries the joined string; no hidden slot waits for JS."""
    page = _render(FIXTURE.read_bytes())
    assert "northwind-instruments/northwind-psu · 0.1.0" in page
    assert ">OTDP 0.2.2 · adapter 1.1 · STG 1.4<" in page
    assert 'data-bw-slot="compat" hidden' not in page


def test_empty_evidence_renders_no_badge_and_advisories_none_renders_muted() -> None:
    """§2.3's explicit-none split: the TABLE renders no badge for empty
    evidence (the record page carries the explicit-none) and muted 'None'
    for absent advisories."""
    page = _render(FIXTURE.read_bytes())
    # northwind-load carries no evidence and no advisories (card index 3:
    # defaults sort daq, shunt, therm, load, psu, scope)
    load = _cards(page)[3]
    assert "northwind-load" in load
    evidence = load.split('class="td-evidence"', 1)[1].split("</td>", 1)[0]
    assert "badge" not in evidence, "empty evidence rendered a badge in the table"
    advisories = load.split('class="td-adv"', 1)[1].split("</td>", 1)[0]
    assert ">None<" in advisories
    assert "text-muted" in advisories


def test_capability_lines_and_none_declared() -> None:
    """The capabilities cell: one icon+label line per TRUE capability; a row
    with no true capability renders muted 'None declared'."""
    page = _render(FIXTURE.read_bytes())
    cards = _cards(page)
    # northwind-psu: network_egress only
    psu = next(card for card in cards if "northwind-psu" in card)
    caps = psu.split('class="td-caps"', 1)[1].split("</td>", 1)[0]
    assert "Network egress" in caps and "<svg" in caps
    assert "Subprocess or native library" not in caps


def test_template_row_is_the_single_shape_source() -> None:
    page = _render(FIXTURE.read_bytes())
    assert page.count("data-bw-template") == 1, "exactly one template row required"


def test_empty_catalogue_renders_the_honest_empty_sentence() -> None:
    page = _render(b'{"index_version": 1, "rows": []}')
    assert "No published releases yet" in page
    assert 'class="bw-empty-row"' in page, "the honest empty renders as a table row"
    assert "data-bw-template" in page, "the template row survives the empty state"


def test_page_generation_is_deterministic() -> None:
    once = _render(FIXTURE.read_bytes())
    twice = _render(FIXTURE.read_bytes())
    assert once == twice


def test_generated_page_carries_no_template_markers() -> None:
    page = _render(FIXTURE.read_bytes())
    assert "bw:catalogue-cards begin" not in page
    assert "bw:provenance -->" not in page


# ── provenance (A06) ──────────────────────────────────────────────────────────


def test_the_provenance_stamp_names_the_generating_commit() -> None:
    page = _render(FIXTURE.read_bytes())
    assert "generated from <span" in page, "the stamp sentence drifted"
    stamped = re.search(r'data-bw-stamp="([0-9a-f]{40})"', page)
    assert stamped is not None and stamped.group(1) == SHA
    assert SHA in page
    # the mockup's stamp line: short sha display (the full sha rides the
    # data-bw-stamp attribute) plus the index format version (§2.1/§2.10)
    assert f">{SHA[:12]}</span> · index v1" in page, (
        "the stamp line lost its short-sha display or its index version"
    )


def test_a_non_commit_sha_refuses() -> None:
    """The stamp never guesses: a short or non-hex sha refuses rather than
    stamping something unverifiable."""
    with pytest.raises(SystemExit, match="page_input_invalid:"):
        _render(FIXTURE.read_bytes(), sha="not-a-sha")
    with pytest.raises(SystemExit, match="page_input_invalid:"):
        _render(FIXTURE.read_bytes(), sha="3f4ad11")


# ── honesty (B3' — whole page) ────────────────────────────────────────────────


def test_whole_page_makes_no_service_claim() -> None:
    """B3's whole-page scan, AMENDED by the #224 follow-on (§5): the mockup's
    footer uses "registry service" in honest negation, so the strict substring
    ban became a pinned-negation + count arm — the phrase occurs EXACTLY ONCE,
    in the footer sentence pinned verbatim below, and no AFFIRMATIVE service
    claim exists anywhere (lede, prose, comments). The domain ban and the
    mark-glyph shape bans (no <rect>, no <circle> — every icon is
    circle/rect-free by rewrite, §2.8) stand unchanged."""
    page = _render(FIXTURE.read_bytes())
    lowered = page.lower()
    assert lowered.count("registry service") == 1, (
        f"'registry service' occurs {lowered.count('registry service')} time(s) — "
        "exactly one is required (the footer's honest negation)"
    )
    assert FOOTER_SENTENCE in page, "the pinned footer negation drifted"
    assert "registry.benchweave.dev" not in lowered
    assert "<rect" not in page, "a stack-glyph (Registry sub-brand mark) shape rendered"
    assert "<circle" not in page, (
        "a circle-bearing glyph rendered (icons are rewritten circle-free)"
    )


def test_the_lede_is_string_pinned() -> None:
    page = _render(FIXTURE.read_bytes())
    assert LEDE in page, "the plain-language lede drifted"


def test_no_affirmative_service_claim_in_the_template() -> None:
    """The committed chrome carries the same honesty as the render: the phrase
    appears exactly once (the pinned footer negation, statically in the
    template) and the domain never appears."""
    template = _template()
    assert template.lower().count("registry service") == 1, (
        "the template must carry 'registry service' exactly once — the footer's "
        "honest negation"
    )
    assert "There is no hosted registry service." in template
    assert "registry.benchweave.dev" not in template.lower()


# ── fail-closed at generation ─────────────────────────────────────────────────


def test_renderer_refuses_unknown_kind_and_names_the_row() -> None:
    bad = json.dumps(
        {"index_version": 1, "rows": [{"kind": "mystery", "package_id": "a/b"}]}
    ).encode()
    with pytest.raises(SystemExit, match=r"page_input_invalid: unknown kind 'mystery' \(a/b\)"):
        _render(bad)


def test_renderer_refuses_an_unparseable_index() -> None:
    with pytest.raises(SystemExit, match="page_input_invalid:"):
        _render(b"not json at all")


def test_renderer_refuses_a_non_object_index() -> None:
    with pytest.raises(SystemExit, match="page_input_invalid:"):
        _render(b'["yanked"]')


def test_structural_literal_refusal_covers_the_template_chrome() -> None:
    """A three-component version literal in a STRUCTURAL slot (here: the
    template's prose) refuses — the chrome is stamped, not data."""
    sabotaged = _template().replace(
        "Plugin catalogue", "Plugin catalogue v0.9.9", 1
    )
    assert "0.9.9" in sabotaged
    with pytest.raises(SystemExit, match="page_literal_refused:"):
        _module().render_page(FIXTURE.read_bytes(), sabotaged, SHA)


def test_structural_braces_refusal_covers_the_template_chrome() -> None:
    sabotaged = _template().replace(
        "Plugin catalogue", "Plugin catalogue {{stg-otdp}}", 1
    )
    with pytest.raises(SystemExit, match="page_braces_refused:"):
        _module().render_page(FIXTURE.read_bytes(), sabotaged, SHA)


def test_row_free_text_is_data_not_a_stamped_claim() -> None:
    """The §4 row 8 narrowing, pinned (records-table form): row data carrying
    a version substring is DATA — the render succeeds and the string appears
    in the row. The relocated gateway renderer refused this whole class (4/4
    repros, whole-render brick); this arm refuses to go back."""
    row = {
        "kind": "admitted-release",
        "signature_state": "signed-valid",
        "package_id": "northwind-instruments/alpha-tool",
        "version": "1.4.2",
        "display_name": "Northwind alpha (requires OTDP 0.2.2 host support)",
        "summary": "Requires OTDP 0.2.2 and STG 1.4 host support.",
        "advisories": ["BW-ADV-099"],
        "source_revision": "a" * 40,
    }
    page = _render(json.dumps({"index_version": 1, "rows": [row]}).encode())
    assert "Northwind alpha (requires OTDP 0.2.2 host support)" in page


def test_row_version_and_compat_stamp_as_data() -> None:
    """The §2.3 flip: statically stamped version/compat cells ride between
    the markers as DATA — a row carrying three-component versions renders
    (only the blank row chrome refuses literals)."""
    row = {
        "kind": "admitted-release",
        "signature_state": "signed-valid",
        "package_id": "northwind-instruments/alpha-tool",
        "version": "1.4.2",
        "display_name": "Northwind alpha",
        "compatibility": {
            "otdp_versions": ["0.2.2"],
            "adapter_api_versions": ["1.1"],
            "stg_versions": ["1.4"],
        },
    }
    page = _render(json.dumps({"index_version": 1, "rows": [row]}).encode())
    assert "northwind-instruments/alpha-tool · 1.4.2" in page
    assert "OTDP 0.2.2 · adapter 1.1 · STG 1.4" in page


def test_a_missing_marker_pair_refuses() -> None:
    with pytest.raises(SystemExit, match="page_input_invalid:"):
        _module().render_page(FIXTURE.read_bytes(), "<html><body>x</body></html>", SHA)


# ── twin constants (R2 + the marker map) ──────────────────────────────────────


def test_marker_display_map_twins_agree() -> None:
    """The unverified-marker display map has two carriers (Python at
    generation, JS for cloned rows); the twins must stay equal or a marker
    renders two ways on one page."""
    js = PLUGINS_JS.read_text(encoding="utf-8")
    pattern = re.compile(r"'([a-z0-9-]+)':\s*'([^']*)'")
    js_map = dict(pattern.findall(js.split("MARKER_DISPLAY", 1)[1].split("}", 1)[0]))
    assert js_map == _module().MARKER_DISPLAY, (js_map, _module().MARKER_DISPLAY)


def test_the_display_map_twins_agree() -> None:
    """The records-table display maps (kind badge text, maintenance badge
    text and tone) each have two carriers — the generator stamps the static
    rows, the JS clones the rest; unequal twins render one row two ways."""
    module = _module()
    js = PLUGINS_JS.read_text(encoding="utf-8")
    pattern = re.compile(r"'([a-z0-9_-]+)':\s*'([^']*)'")

    def js_map(name: str) -> dict[str, str]:
        chunk = js.split(f"var {name}", 1)[1]
        return dict(pattern.findall(chunk.split("}", 1)[0]))

    assert js_map("KIND_DISPLAY") == module.KIND_DISPLAY, (
        js_map("KIND_DISPLAY"), module.KIND_DISPLAY,
    )
    assert js_map("MAINTENANCE_DISPLAY") == module.MAINTENANCE_DISPLAY
    assert js_map("MAINTENANCE_BADGE") == module.MAINTENANCE_BADGE


def test_detail_id_and_record_url_twins_agree() -> None:
    """The detail-host id slug and the record-page URL have two carriers
    (the generator stamps them on static rows; the JS sets them on clones) —
    unequal twins send htmx to a target that does not exist."""
    module = _module()
    js = PLUGINS_JS.read_text(encoding="utf-8")
    assert "replace(/[^A-Za-z0-9-]/g, '-')" in js, "the JS lost its slug rewrite"
    node = shutil.which("node")
    assert node is not None, "node missing — see test_node_is_present in the search suite"
    script = (
        "const m = require(process.argv[1]);"
        "const row = {package_id: 'northwind-instruments/alpha-tool',"
        " version: '1.4.2', registry_id: 'benchweave-registry'};"
        "console.log(m.detailId(row) + ' ' + m.recordUrl(row));"
    )
    result = subprocess.run(
        [node, "-e", script, str(PLUGINS_JS)],
        capture_output=True, text=True, check=False, cwd=REPO,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    want_id = module.detail_id(
        {"package_id": "northwind-instruments/alpha-tool", "version": "1.4.2"}
    )
    want = (
        f"{want_id} "
        "records/benchweave-registry/northwind-instruments/alpha-tool/1.4.2/index.html"
    )
    assert result.stdout.strip() == want, (result.stdout, want)


def test_truncate_at_twins_agree() -> None:
    """R2: the truncation length is one constant with two carriers — the
    Python TRUNCATE_AT and the JS `var TRUNCATE_AT = <n>;` must pin equal
    or the static card and the cloned card truncate differently."""
    js = PLUGINS_JS.read_text(encoding="utf-8")
    match = re.search(r"var TRUNCATE_AT = (\d+);", js)
    assert match is not None, "plugins.js lost its named TRUNCATE_AT"
    assert int(match.group(1)) == _module().TRUNCATE_AT


def test_short_uses_the_twin_constant() -> None:
    assert _module()._short("a" * 40) == "a" * 12 + "…"
    assert _module()._short("short") == "short"


# ── the advisory-yank gap, pinned as a documented reading (§4 row 7) ─────────


def test_a_yanked_releases_advisory_appears_on_no_catalogue_surface(tmp_path: Path) -> None:
    """DEFERRED-WITH-PIN (pivot §4 row 7): a yanked release's row drops from
    the index (CR-25 — proven in tests/test_generate_index.py), and with it
    every advisory it carried — so the releases most likely to carry
    advisories are the ones the catalogue says least about. This arm makes
    that gap a DOCUMENTED READING, not an accident: the advisory id appears
    on no catalogue surface (index bytes or page bytes).

    REOPEN TRIGGER: slice 4 / gateway issue #226 (response reach) — its
    design pass owns the advisories-only surface. Until then this gap is
    the accepted honest state, and this test failing means something
    changed without that design."""
    import shutil
    import subprocess
    import sys

    root = tmp_path / "repo"
    root.mkdir()
    release = (
        root / "releases" / "benchweave-registry" / "northwind-instruments" / "alpha-tool"
        / "1.0.0"
    )
    release.mkdir(parents=True)
    manifest = {
        "registry_id": "benchweave-registry",
        "package_id": "northwind-instruments/alpha-tool",
        "version": "1.0.0",
        "publisher_id": "northwind-instruments",
        "display_name": "Northwind alpha",
        "summary": "Synthetic fixture for the advisory-yank pin.",
        "licence": {"spdx_expression": "MIT"},
        "compatibility": {"otdp_versions": [], "adapter_api_versions": [], "stg_versions": []},
        "evidence": [],
        "source": {"revision": "0" * 40},
    }
    (release / "manifest.json").write_bytes(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    # Fold R1: the planted status documents carry the bound release block
    # (the directory's identity + the manifest digest on disk).
    manifest_digest = hashlib.sha256(
        (release / "manifest.json").read_bytes()
    ).hexdigest()
    bound_release = {
        "registry_id": "benchweave-registry",
        "package_id": "northwind-instruments/alpha-tool",
        "version": "1.0.0",
        "manifest_sha256": manifest_digest,
    }
    (release / "status.json").write_bytes(
        json.dumps(
            {
                "lifecycle": "yanked",
                "release": bound_release,
                "advisories": [
                    {
                        "id": "BW-ADV-YANK-001",
                        "severity": "high",
                        "summary": "synthetic advisory on a yanked release",
                        "url": "https://example.invalid/advisories/BW-ADV-YANK-001",
                    }
                ],
            }
        ).encode()
    )
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "generate_index.py"), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    index_bytes = (root / "index.json").read_bytes()
    assert b"BW-ADV-YANK-001" not in index_bytes, "the yanked row survived the index"
    page = _render(index_bytes)
    assert "BW-ADV-YANK-001" not in page, "a yanked release's advisory reached the page"
    assert "No published releases yet" in page
    # control: the same release NOT yanked surfaces the advisory — the pin
    # is about the yank's consequence, not about advisory rendering
    (release / "status.json").write_bytes(
        json.dumps({"lifecycle": "published", "release": bound_release, "advisories": [
            {
                "id": "BW-ADV-YANK-001",
                "severity": "high",
                "summary": "synthetic advisory on a yanked release",
                "url": "https://example.invalid/advisories/BW-ADV-YANK-001",
            }
        ]}).encode()
    )
    shutil.rmtree(root / "index.json", ignore_errors=True)
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "generate_index.py"), "--root", str(root)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    published_index = (root / "index.json").read_bytes()
    assert b"BW-ADV-YANK-001" in published_index, (
        "control: the published row's advisory must reach the index (the "
        "fixture ships no manifest.sig, so the row is unsigned and outside "
        "the page's default view by CR-22 — that exclusion is pinned by "
        "test_default_page_excludes_non_default_kinds_and_unsigned)"
    )


def test_the_committed_template_its_index_and_the_page_agree() -> None:
    """The end-to-end shape on the real tree: rendering the committed index
    through the committed template yields a page whose cards match the
    committed index's default rows (the dogfood row)."""
    page = _render(INDEX.read_bytes())
    rows = json.loads(INDEX.read_bytes())["rows"]
    defaults = [
        row for row in rows
        if row.get("kind") == "admitted-release" and row.get("signature_state") == "signed-valid"
    ]
    assert len(_cards(page)) == len(defaults)
    for row in defaults:
        assert f'data-bw-package-id="{row["package_id"]}"' in page


# ── fold R7/R10 (2026-10-02 round-2 refute; records-table follow-on) ──────────


def test_row_drill_anchors_point_at_relative_record_urls() -> None:
    """R7/R10 (records-table form): the row's drill anchor is a RELATIVE
    record-page URL (R10 — the page serves from a Pages subroot); the
    stamped-commit pinning moves to the record pages' own links, whose arms
    live in tests/test_catalogue_record.py. With htmx loaded the anchor also
    carries the drill wiring; without JS it is a plain link."""
    page = _render(FIXTURE.read_bytes())
    cards = _cards(page)
    assert cards, "precondition: default rows render"
    for card in cards:
        anchor = re.search(r'<a class="release-name"[^>]*href="([^"]+)"', card)
        assert anchor is not None, "a row carries no drill anchor"
        url = anchor.group(1)
        assert url.startswith("records/benchweave-registry/"), (
            f"the drill anchor is not a relative record URL: {url}"
        )
        assert url.endswith("/index.html"), url
        assert 'hx-select="#release-detail"' in card and "hx-push-url" in card
        slug = re.search(r'hx-target="#(bw-detail-[a-z0-9-]+)"', card)
        assert slug is not None, "the row carries no detail-host target"


def test_no_root_absolute_urls_in_the_template_or_wiring() -> None:
    """R10 (critic F8): the template and the wiring never reference
    root-absolute URLs (`src="/`, `href="/`, `fetch('/` and the double-quoted
    fetch twin) — the page is served from a Pages subroot, a root-absolute
    reference 404s there, and the loopback-served CI cannot catch the class;
    this static refusal can."""
    for name, text in (
        ("catalogue/index.template.html", _template()),
        ("catalogue/assets/plugins.js", PLUGINS_JS.read_text(encoding="utf-8")),
    ):
        for literal in ('src="/', 'href="/', "fetch('/", 'fetch("/'):
            assert literal not in text, f"{name} carries the root-absolute form {literal!r}"


# ── page chrome: snapshot line, nav placeholders, theme switcher, htmx ────────


def test_the_snapshot_line_carries_stamp_counts_and_publishers() -> None:
    """§2.1: `snapshot <sha12>` (the stamp, short), `N shown of M` (the
    default counts, statically; JS updates `shown` on filter), `P vetted`
    (len(publishers)) — honest '0 vetted' on an empty registry."""
    page = _render(FIXTURE.read_bytes(), publisher_count=2)
    assert "<dt>snapshot</dt>" in page and f"<dd class=\"mono\">{SHA[:12]}</dd>" in page
    assert 'data-bw-shown="6"' in page and ">6</span> shown of 11<" in page
    assert "2 vetted" in page
    bare = _render(FIXTURE.read_bytes())
    assert "0 vetted" in bare, "the honest zero-publisher registry must render 0 vetted"


def test_nav_placeholders_are_marked_non_links() -> None:
    """§2.1: Publishers and Advisories are slice-4 surfaces and the
    publication prose is maintainer-facing today — they render as muted
    NON-LINKS (no href a static page cannot honor), aria-disabled, naming
    the future surface; Catalogue is the only live link."""
    template = _template()
    catalogue = re.search(r"<nav[^>]*>(.*?)</nav>", template, re.DOTALL)
    assert catalogue is not None, "the template lost its nav"
    nav = catalogue.group(1)
    assert 'href="#catalogue" aria-current="page"' in nav
    for label in ("Publishers", "Advisories", "How publication works"):
        entry = re.search(rf'<span class="nav-future"[^>]*>{label}</span>', nav)
        assert entry is not None, f"{label} is not a marked non-link"
        assert "href" not in entry.group(0), f"{label} carries an href"
        assert 'aria-disabled="true"' in entry.group(0), f"{label} is not aria-disabled"
        assert 'title="' in entry.group(0), f"{label} names no future surface"


def test_the_theme_switcher_button_and_toggle_wiring_exist() -> None:
    """§2.1: the header carries the switcher button (aria-labelled) and the
    wiring toggles data-theme on the html element, persisted in localStorage
    (the icon is the circle-free sun rewrite — see the honesty arms)."""
    template = _template()
    assert 'id="bw-theme-toggle"' in template and 'aria-label="Switch colour theme"' in template
    js = PLUGINS_JS.read_text(encoding="utf-8")
    assert "data-theme" in js and "localStorage" in js and "bw-theme" in js


def test_htmx_is_served_same_origin_before_the_wiring_with_no_cdn() -> None:
    """§2.5/B-S: the vendored htmx loads same-origin (assets/htmx.min.js),
    BEFORE plugins.js; neither the template nor the wiring references any
    CDN (the vendor is digest-pinned — tests/test_htmx_vendor.py)."""
    template = _template()
    htmx_at = template.find('src="assets/htmx.min.js"')
    js_at = template.find('src="assets/plugins.js"')
    assert htmx_at != -1 and js_at != -1 and htmx_at < js_at, (
        "the template must load assets/htmx.min.js before assets/plugins.js"
    )
    for name, text in (
        ("catalogue/index.template.html", template),
        ("catalogue/assets/plugins.js", PLUGINS_JS.read_text(encoding="utf-8")),
    ):
        for host in ("unpkg.com", "cdn.jsdelivr", "cdnjs.cloudflare", "esm.sh"):
            assert host not in text, f"{name} references the CDN host {host}"


# ── the mark, both postures (§2.8 — ships DARK behind --registry-mark) ───────

WORDMARK_BEGIN_MARKER = "<!-- bw:wordmark begin -->"
WORDMARK_END_MARKER = "<!-- bw:wordmark end -->"


def _vendored_mark_rects() -> list[str]:
    guide = VENDORED_STYLEGUIDE.read_text(encoding="utf-8")
    return re.findall(r'<rect [^>]*rx="0.85"[^>]*/>', guide)


def test_the_unfired_posture_ships_no_mark_shapes() -> None:
    """§2.8's unfired arm: the default render carries zero <rect> (no
    stack-glyph bars), zero <circle>, and no Registry pill — the mark ships
    dark pending the owner's word."""
    page = _render(FIXTURE.read_bytes())
    assert page.count("<rect") == 0, "the unfired render carries a stack-glyph shape"
    assert "<circle" not in page, "a circle-bearing glyph rendered"
    assert "mark-pill" not in page, "the Registry pill rendered unfired"
    assert ">Registry<" not in page, "a Registry wordmark label rendered unfired"


def test_the_fired_posture_pins_the_three_spec_rects_byte_exactly() -> None:
    """§2.8's fired arm: --registry-mark renders the Registry variant —
    exactly the vendored spec's three stack-glyph bars (byte-matched, never
    retyped), inside the single header wordmark block, with the pill; the
    circle ban still holds (the Standards tag glyph stays gated)."""
    spec_rects = _vendored_mark_rects()
    assert len(spec_rects) == 3, (
        f"the vendored styleguide's Sub-brands grid carries {len(spec_rects)} "
        "stack-glyph bars — the fired arm's spec moved; re-derive"
    )
    page = _render(FIXTURE.read_bytes(), registry_mark=True)
    assert page.count("<rect") == 3, (
        f"the fired render carries {page.count('<rect')} rect(s), expected exactly 3"
    )
    for rect in spec_rects:
        assert rect in page, f"a spec bar is absent or retyped: {rect}"
    assert ">Registry<" in page, "the fired wordmark lost its Registry pill"
    assert "<circle" not in page, "the fired posture still bans the tag-glyph circle"
    # all three bars sit inside the single header wordmark block
    wordmark = page.split(WORDMARK_BEGIN_MARKER, 1)[1].split(WORDMARK_END_MARKER, 1)[0]
    for rect in spec_rects:
        assert rect in wordmark, "a spec bar rendered outside the wordmark block"
    # the gateway weave is GONE in the fired variant (the mark replaces it)
    assert "L17 7 L7 17" not in wordmark, "the fired wordmark kept the gateway weave"
