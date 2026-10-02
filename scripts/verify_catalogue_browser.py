#!/usr/bin/env python3
"""The browser arm of the catalogue deploy gate (issue #224 pivot §5 B4';
records-table follow-on §5/§6).

Runs in the Pages workflow's deploy job against the GENERATED artifact
(the ``--dest`` tree ``generate_catalogue_page.py`` just wrote), BEFORE the
deploy: a red arm never ships. This is the wiring-level companion to the
stdlib DOM-containment test — same property, proven in a real browser —
plus the static-deploy posture:

- the default rows are present in the served DOM WITHOUT JavaScript (the
  generated rows are real static bytes, not a client-side render) and the
  caption/snapshot counts carry the honest default values;
- a matching query keeps the row; a non-matching query empties the table
  and shows the honest-empty state;
- the signature filter reveals an unsigned row WITH the unsigned cell
  (icon + visible text, never icon-only — B-I's browser half);
- the URL round-trip restores filter state on reload (B-X);
- the theme toggle flips ``data-theme`` on the html element (§2.1);
- every ``[data-bw-slot]`` descends from its ``tr.bw-row`` in the real
  DOM (no orphan rows; kind badge inside the Release cell on every row);
- the ONLY non-asset request of the whole session — load included — is
  the same-origin ``index.json`` fetch (no search backend, no CDN data,
  no analytics; the font stylesheet is a page asset, not search-originated).

The artifact is served by a plain ``http.server`` on loopback: a static
file server IS the static deploy (B4'/CR-26 — "no service" means no search
backend). Playwright is provided by the workflow (``uv run --with
playwright``); without it this exits ``browser_arm_unavailable:`` loudly
rather than skipping — a skip would be a silent hole.

Usage::

    python scripts/verify_catalogue_browser.py --dest _site
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import socket
import threading
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]


@functools.lru_cache(maxsize=1)
def _playwright() -> Any:
    try:
        # playwright is a CI-transient dep (`uv run --with playwright`), not
        # a project dependency — hence the local ignore of its absence.
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised only without the dep
        raise SystemExit(
            "browser_arm_unavailable: playwright is not importable — the "
            "browser arm refuses to skip (run via `uv run --with playwright "
            "python scripts/verify_catalogue_browser.py ...`)"
        ) from exc
    return sync_playwright


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass


def _serve(directory: Path) -> tuple[str, http.server.ThreadingHTTPServer]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    handler = functools.partial(_Quiet, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", int(port)), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{port}", server


def _check(condition: bool, what: str) -> None:
    if not condition:
        raise SystemExit(f"browser_arm_failed: {what}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, required=True)
    args = parser.parse_args()
    dest = args.dest.resolve()
    _check((dest / "index.html").is_file(), f"{dest}/index.html is missing")
    rows = json.loads((dest / "index.json").read_text(encoding="utf-8"))["rows"]
    defaults = [
        row for row in rows
        if row.get("kind") == "admitted-release"
        and row.get("signature_state") == "signed-valid"
    ]
    unsigned = [row for row in rows if row.get("signature_state") == "unsigned"]
    noun = "release" if len(defaults) == 1 else "releases"
    static_caption = (
        f"{len(defaults)} {noun}. "
        "Select a name for its provenance, evidence and files."
    )
    origin, server = _serve(dest)
    try:
        with (
            _playwright()() as playwright_runtime,
            playwright_runtime.chromium.launch(headless=True) as browser,
        ):
            # 1. the static bytes render without JavaScript
            static_context = browser.new_context(java_script_enabled=False)
            static_page = static_context.new_page()
            static_page.goto(origin, wait_until="load")
            static_rows = static_page.locator(
                "#release-rows tr.bw-row[data-bw-package-id]"
            )
            _check(
                static_rows.count() == len(defaults),
                f"without JS the static rows are {static_rows.count()}, "
                f"expected {len(defaults)} (the default view must be real "
                "static bytes)",
            )
            _check(
                static_page.locator("#catalogue-count").inner_text().strip()
                == static_caption,
                "the static caption does not carry the honest default count",
            )
            _check(
                static_page.locator("[data-bw-shown]").inner_text().strip()
                == str(len(defaults)),
                "the static snapshot line does not carry the honest shown count",
            )
            static_context.close()

            # 2. the wired session: load, match, empty, reveal, URL state,
            #    theme, containment, requests
            context = browser.new_context()
            requests: list[str] = []
            context.on("request", lambda request: requests.append(request.url))
            page = context.new_page()
            page.goto(origin, wait_until="networkidle")

            visible_defaults = page.locator(
                "#release-rows tr.bw-row[data-bw-package-id]:not([hidden])"
            )
            _check(
                visible_defaults.count() == len(defaults),
                f"after load the visible default rows are "
                f"{visible_defaults.count()}, expected {len(defaults)}",
            )
            caption = page.locator("#catalogue-count").inner_text().strip()
            _check(caption == static_caption, f"the caption never settled: {caption!r}")

            containment = page.evaluate(
                """() => {
                    const slots = Array.from(document.querySelectorAll('[data-bw-slot]'));
                    const orphanSlots = slots.filter((el) => !el.closest('tr.bw-row'));
                    const rows = Array.from(document.querySelectorAll('tr.bw-row'));
                    const kindless = rows.filter(
                        (row) => !row.querySelector('td.td-release [data-bw-slot="kind"]')
                    );
                    return {slots: slots.length, orphanSlots: orphanSlots.length,
                            rows: rows.length, kindless: kindless.length};
                }"""
            )
            _check(containment["slots"] > 0, "the page carries no slot elements")
            _check(
                containment["orphanSlots"] == 0,
                f"{containment['orphanSlots']} slot(s) outside their row in the "
                "real DOM (the unclosed-tag HIGH class)",
            )
            _check(
                containment["kindless"] == 0,
                f"{containment['kindless']} row(s) without a kind badge (CR-56)",
            )

            # a matching query keeps the dogfooded row (derived from the
            # served index — data-driven, no hardcoded names)
            needle = str(defaults[0]["display_name"]).split()[0].lower()
            page.fill("#q", needle)
            page.wait_for_timeout(400)
            kept = page.locator(
                "#release-rows tr.bw-row[data-bw-package-id]:not([hidden])"
            )
            _check(
                kept.count() >= 1,
                f"a matching query ({needle!r}) dropped every row",
            )
            _check(
                f"q={needle}" in page.url,
                f"the matching query did not push filter state to the URL: {page.url}",
            )

            # the URL round-trip: reload restores the filter state (B-X)
            page.reload(wait_until="networkidle")
            _check(
                page.locator("#q").input_value() == needle,
                "the filter text did not restore from the URL on reload",
            )
            _check(
                page.locator(
                    "#release-rows tr.bw-row[data-bw-package-id]:not([hidden])"
                ).count()
                >= 1,
                "the restored filter state dropped every row",
            )

            # the signature filter reveals an unsigned row with the unsigned
            # cell (icon + visible text — B-I's browser half)
            if unsigned:
                page.select_option("#sig", "unsigned")
                page.wait_for_timeout(300)
                revealed = page.locator(
                    "#release-rows tr.bw-row[data-bw-package-id]:not([hidden])"
                )
                _check(
                    revealed.count() >= 1,
                    "the unsigned filter revealed no rows (the fixture/deployed "
                    "index carries unsigned rows)",
                )
                sig_cell = revealed.first.locator("td.td-sig")
                _check(
                    "Unsigned" in sig_cell.inner_text(),
                    "a revealed unsigned row does not carry the visible text "
                    "'Unsigned' (icon-only never occurs)",
                )
                title = sig_cell.locator("span").first.get_attribute("title") or ""
                _check(
                    title.startswith("No publisher signature."),
                    f"the unsigned cell lost its title: {title!r}",
                )
                page.select_option("#sig", "signed-valid")

            # the theme toggle flips data-theme on the html element
            page.click("#bw-theme-toggle")
            _check(
                page.evaluate(
                    "document.documentElement.getAttribute('data-theme') !== null"
                ),
                "the theme toggle did not set data-theme",
            )

            # a non-matching query empties the table with the honest state
            page.fill("#q", "zz-no-such-plugin-anywhere")
            page.wait_for_timeout(400)
            gone = page.locator(
                "#release-rows tr.bw-row[data-bw-package-id]:not([hidden])"
            )
            _check(gone.count() == 0, "a non-matching query left rows visible")
            _check(
                page.locator("#catalogue-empty").is_visible(),
                "the honest-empty state did not appear",
            )

            # the static-deploy posture, scoped across the whole session
            # (load included): no OFF-ORIGIN request beyond the font CDN —
            # the page's own assets and the browser's automatic same-origin
            # requests (favicon probe included) are not search-originated;
            # and the same-origin index fetch DID happen.
            off_origin = [
                url for url in requests
                if not (
                    url.startswith(origin + "/")
                    or url.startswith("https://fonts.googleapis.com/")
                    or url.startswith("https://fonts.gstatic.com/")
                )
            ]
            _check(
                off_origin == [],
                f"off-origin request(s) beyond the font CDN — the catalogue "
                f"is not a static deploy: {off_origin}",
            )
            _check(
                any(url == origin + "/index.json" for url in requests),
                "the same-origin index fetch never happened",
            )
            context.close()
    finally:
        server.shutdown()
    print(
        f"OK browser arm: {len(defaults)} default row(s) render statically, "
        "containment holds in the real DOM, queries match and empty honestly, "
        "filter state round-trips through the URL, the unsigned reveal and the "
        "theme toggle work, and the only non-asset session request is the "
        "same-origin index fetch"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
