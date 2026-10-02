"""The style authority for the registry-hosted catalogue (pivot §4.9/§6.3).

The gateway's ``docs/internal/public-site-styleguide.html`` stays the
authored authority; this repository vendors a digest-pinned copy
(``vendored/gateway/public-site-styleguide.html``) and the catalogue page's
CSS (``catalogue/assets/catalogue.css``) is disciplined against it: the
token blocks are copied verbatim, and every ``var()`` the page's CSS
references must resolve in the token block — no new colors, fonts, radii or
shadows can ride in through the page. Repinning the vendor is a deliberate
recorded act (the pin record), never a silent drift.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STYLEGUIDE = REPO / "vendored" / "gateway" / "public-site-styleguide.html"
STYLEGUIDE_PIN = REPO / "vendored" / "gateway" / "public-site-styleguide.pin.json"
PAGE_CSS = REPO / "catalogue" / "assets" / "catalogue.css"

#: The vendored bytes' origin (the slice-2 branch tip that carries the two
#: declared component shapes; main's copy predates them).
ORIGIN = "madeinoz67/benchweave@635e5b9:docs/internal/public-site-styleguide.html"

_VAR_REF = re.compile(r"var\(\s*(--[a-z0-9-]+)")
_TOKEN_DECL = re.compile(r"^\s{2,}(--[a-z0-9-]+)\s*:\s*([^;]+);", re.MULTILINE)
_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _style_block(html: str) -> str:
    start = html.index("<style>") + len("<style>")
    end = html.index("</style>")
    return html[start:end]


def _token_declarations(text: str) -> list[tuple[str, str]]:
    """Every token declaration IN ORDER — a token is declared once per theme
    (light :root, dark auto, dark forced), so last-wins dict shape would
    silently drop the light values."""
    return _TOKEN_DECL.findall(text)


def _tokens(text: str) -> dict[str, str]:
    return dict(_token_declarations(text))


def test_the_vendored_styleguide_is_digest_pinned_to_its_origin() -> None:
    pin_text = STYLEGUIDE_PIN.read_text(encoding="utf-8")
    import json

    pin = json.loads(pin_text)
    assert pin["source"] == ORIGIN, pin["source"]
    digest = hashlib.sha256(STYLEGUIDE.read_bytes()).hexdigest()
    assert digest == pin["sha256"], (
        f"the vendored styleguide drifted from its pin (on-disk {digest}, "
        f"pinned {pin['sha256']}) — repin deliberately or restore"
    )
    # A recorded divergence (registry-authored sections pending gateway
    # adoption) must name its sections and convergence path — the #224
    # follow-on form; an UNRECORDED divergence still reddens above.
    if "divergence" in pin:
        assert pin["divergence"]["sections"], "a recorded divergence names no sections"
        assert pin["divergence"]["converges"], "a recorded divergence names no convergence path"


def test_the_vendored_copy_declares_the_catalogue_component_shapes() -> None:
    """§4.9 + the #224 follow-on (§7): the declared shapes (filter bar,
    catalogue meta line, records table, record page) are declared IN the
    vendored copy — as AUTHORED bytes since the gateway's adoption (PR
    #346) and the 2026-10-03 convergence re-copy; the interim
    registry-authored divergence is closed."""
    html = STYLEGUIDE.read_text(encoding="utf-8")
    block = _style_block(html)
    assert "Filter bar" in html and "filter-bar" in block
    assert "Catalogue meta line" in html and "catalogue-meta" in block
    assert "Records table" in html and "bw-records" in block, (
        "the records-table component declaration is missing"
    )
    assert "Record page" in html and "record-grid" in block, (
        "the record-page component declaration is missing"
    )
    assert "pending gateway adoption" not in html, (
        "the divergence is converged: the vendor must be byte-identical to "
        "the authored authority, divergence note gone"
    )


def test_the_page_css_token_block_is_the_styleguide_block_verbatim() -> None:
    """The styleguide's own instruction: copy the CSS custom properties from
    the :root block verbatim — never re-derive. The page CSS's declaration
    LIST must equal the styleguide's, in order, name for name, value for
    value (order matters: a token is declared once per theme block)."""
    guide_tokens = _token_declarations(_style_block(STYLEGUIDE.read_text(encoding="utf-8")))
    page_tokens = _token_declarations(PAGE_CSS.read_text(encoding="utf-8"))
    assert page_tokens, "the page CSS token block did not parse"
    divergence = next(
        (i for i, (page, guide) in enumerate(
            zip(page_tokens, guide_tokens, strict=False)  # lengths may differ
        ) if page != guide),
        min(len(page_tokens), len(guide_tokens)),
    )
    assert page_tokens == guide_tokens, (
        "catalogue/assets/catalogue.css token block differs from the vendored "
        f"styleguide's declaration list (page {len(page_tokens)} declarations, "
        f"guide {len(guide_tokens)}, first divergence at index {divergence})"
    )


def test_every_var_reference_in_the_page_css_resolves() -> None:
    """The CI-arm substance (§4.9): every var() the page's CSS references
    resolves in the token block — an unresolved reference would render as
    the initial value (usually nothing) in both themes."""
    css = PAGE_CSS.read_text(encoding="utf-8")
    tokens = set(_tokens(css))
    assert tokens, "precondition: the token block parsed"
    references = set(_VAR_REF.findall(css))
    assert references, "precondition: the CSS references tokens"
    unresolved = sorted(references - tokens)
    assert not unresolved, f"unresolved var() reference(s) in the page CSS: {unresolved}"


def test_the_page_css_introduces_no_offtoken_color_values() -> None:
    """No new colors: every hex literal in the page CSS RULES (comments
    stripped — an issue number in a comment is not a color) must appear as
    a token VALUE in the vendored styleguide's declarations (any theme
    block; color-mix() composes tokens, not new hex)."""
    css = _COMMENT.sub("", PAGE_CSS.read_text(encoding="utf-8"))
    guide_values = {
        value.strip()
        for _, value in _token_declarations(_style_block(STYLEGUIDE.read_text(encoding="utf-8")))
    }
    hexes = set(re.findall(r"#[0-9A-Fa-f]{3,8}\b", css))
    rogue = sorted(
        h for h in hexes
        if h not in guide_values and h.upper() not in {v.upper() for v in guide_values}
    )
    assert not rogue, f"color value(s) outside the vendored token set: {rogue}"
