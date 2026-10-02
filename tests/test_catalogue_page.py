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

# CR-20's seven contract fields, as the card slots the renderer must carry
# (rendered or explicitly "none" — the value arms are below).
CONTRACT_SLOTS = (
    "display-name",
    "summary",
    "publisher",
    "licence",
    "maintenance",
    "kind",
    "release-id",
    "version",
    "digest",
    "compat",
    "evidence-link",
    "source-revision",
)

# The lede (B3'): plain language, exactly what exists — pinned so a drift
# toward a service claim reddens. Deliberately does NOT contain the phrase
# "registry service" even in negation: the whole-page scan is strict.
LEDE = "The catalogue of published releases, rendered from the registry repository of record."


def _module() -> Any:
    spec = importlib.util.spec_from_file_location("generate_catalogue_page", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _render(index_bytes: bytes, sha: str = SHA) -> str:
    return str(_module().render_page(index_bytes, _template(), sha))


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
    """Every data-bw-slot descends from its spec-card; every card is either
    the hidden template shape or a package-identified row card; every card
    carries its kind slot. Substring containment proves none of this — an
    unclosed card opening tag leaves the slots parsed-but-orphaned."""
    nodes = list(_walk(_parse(html)))
    slots = [n for n in nodes if "data-bw-slot" in n.attrs]
    assert slots, "precondition: the page carries slot elements"
    for slot in slots:
        classes = _ancestor_classes(slot)
        assert any("spec-card" in c.split() for c in classes), (
            f"slot data-bw-slot={slot.attrs['data-bw-slot']!r} does not descend "
            "from its spec-card (an unclosed card opening tag?)"
        )
    cards = [n for n in nodes if n.tag == "div" and "spec-card" in n.attrs.get("class", "").split()]
    assert cards, "precondition: the page carries cards"
    for card in cards:
        in_template = any(
            ancestor.tag == "template" for ancestor in _ancestors(card)
        )
        assert in_template or card.attrs.get("data-bw-package-id"), (
            "a card carries neither the template shape nor a package id"
        )
        kinds = [
            child
            for child in _walk(card.children)
            if child.attrs.get("data-bw-slot") == "kind"
        ]
        assert kinds, f"card {card.attrs.get('data-bw-package-id', '(template)')} has no kind slot"


def _ancestors(node: _Node) -> Iterator[_Node]:
    current = node.parent
    while current is not None:
        yield current
        current = current.parent


def test_dom_containment_on_the_fixture_page() -> None:
    """The standing guard for the relocated renderer's HIGH: on the fixture
    page (6 default cards + template), every slot sits inside its card."""
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
        "northwind-instruments/northwind-fixture",  # in-tree-fixture
    ):
        assert f'data-bw-package-id="{pid}"' not in page, f"non-default row rendered: {pid}"


def test_static_cards_carry_the_contract_fields() -> None:
    """CR-20's structural arm: every card carries the contract slots
    (rendered or explicitly "none")."""
    page = _render(FIXTURE.read_bytes())
    cards = _cards(page)
    assert len(cards) == 6, f"the fixture's default view is 6 cards, got {len(cards)}"
    for card in cards:
        for slot in CONTRACT_SLOTS:
            assert f'data-bw-slot="{slot}"' in card, f"card lacks contract slot {slot}"


def test_every_default_card_is_kind_tagged() -> None:
    """CR-56's static half: a row never renders without its kind tag."""
    page = _render(FIXTURE.read_bytes())
    for card in _cards(page):
        assert 'data-bw-slot="kind"' in card and "admitted-release" in card


def test_explicit_none_for_absent_evidence_and_advisories() -> None:
    """CR-20's "or explicitly none"."""
    page = _render(FIXTURE.read_bytes())
    assert "no test evidence" in page
    assert "no advisories" in page


def test_template_card_is_the_single_shape_source() -> None:
    page = _render(FIXTURE.read_bytes())
    assert page.count("data-bw-template") == 1, "exactly one template card required"


def test_empty_catalogue_renders_the_honest_empty_sentence() -> None:
    page = _render(b'{"index_version": 1, "rows": []}')
    assert "No published releases yet" in page
    assert "data-bw-template" in page, "the template card survives the empty state"


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


def test_a_non_commit_sha_refuses() -> None:
    """The stamp never guesses: a short or non-hex sha refuses rather than
    stamping something unverifiable."""
    with pytest.raises(SystemExit, match="page_input_invalid:"):
        _render(FIXTURE.read_bytes(), sha="not-a-sha")
    with pytest.raises(SystemExit, match="page_input_invalid:"):
        _render(FIXTURE.read_bytes(), sha="3f4ad11")


# ── honesty (B3' — whole page) ────────────────────────────────────────────────


def test_whole_page_makes_no_service_claim() -> None:
    """B3's whole-page scan: the phrase 'registry service' appears nowhere
    (lede, footer, prose, comments), no registry.benchweave.dev URL, and
    no sub-brand mark glyph (the styleguide's stack-glyph bars and
    tag-glyph dot ship no <rect>/<circle> shapes)."""
    page = _render(FIXTURE.read_bytes())
    lowered = page.lower()
    assert "registry service" not in lowered, "the page claims a registry service"
    assert "registry.benchweave.dev" not in lowered
    assert "<rect" not in page, "a stack-glyph (Registry sub-brand mark) shape rendered"
    assert "<circle" not in page, "a tag-glyph (Standards sub-brand mark) shape rendered"


def test_the_lede_is_string_pinned() -> None:
    page = _render(FIXTURE.read_bytes())
    assert LEDE in page, "the plain-language lede drifted"


def test_no_registry_service_language_in_the_template() -> None:
    """The committed chrome carries the same honesty as the render."""
    template = _template().lower()
    assert "registry service" not in template
    assert "registry.benchweave.dev" not in template


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
    """The §4 row 8 narrowing, pinned: a summary (or display name, or
    advisory id, or source revision) carrying a version substring is DATA —
    the render succeeds and the string appears on the card. The relocated
    gateway renderer refused this whole class (4/4 repros, whole-render
    brick); this arm refuses to go back."""
    row = {
        "kind": "admitted-release",
        "signature_state": "signed-valid",
        "package_id": "northwind-instruments/alpha-tool",
        "display_name": "Northwind alpha",
        "summary": "Requires OTDP 0.2.2 and STG 1.4 host support.",
        "advisories": ["BW-ADV-099"],
        "source_revision": "a" * 40,
    }
    page = _render(json.dumps({"index_version": 1, "rows": [row]}).encode())
    assert "Requires OTDP 0.2.2" in page
    assert "BW-ADV-099" in page


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


# ── fold R7/R10 (2026-10-02 round-2 refute) ───────────────────────────────────


def test_card_release_links_pin_to_the_stamped_commit() -> None:
    """R7 (critic F6): every card's release link points at the STAMPED
    commit's tree, not `main` — the page's click-through must show the exact
    bytes the page was generated from, matching its verifiability contract
    (the footer says `generated from <sha>`; the links must not quietly
    drift to whatever main holds today). The template's header nav link is
    a browse link and stays on main by design."""
    page = _render(FIXTURE.read_bytes())
    cards = _cards(page)
    assert cards, "precondition: default cards render"
    for card in cards:
        href = re.search(r'data-bw-slot="evidence-link"\s+href="([^"]+)"', card)
        assert href is not None, "a card carries no evidence link"
        assert href.group(1).startswith(
            f"https://github.com/madeinoz67/benchweave-registry/tree/{SHA}/releases/"
        ), f"card link is not stamped-commit-pinned: {href.group(1)}"
    # the JS twin builds the same pinned shape (ref read from the page's own
    # stamp at runtime; 'main' remains only as the no-JS fallback)
    js = PLUGINS_JS.read_text(encoding="utf-8")
    assert "function releaseDirUrl(row, ref)" in js, (
        "plugins.js releaseDirUrl lost its ref parameter"
    )
    assert "data-bw-stamp" in js, "the wiring no longer reads the page's stamp"
    assert "'https://github.com/madeinoz67/benchweave-registry/tree/' + (ref" in js or (
        "tree/' + (ref" in js
    ), "the JS URL base no longer carries the ref"


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
