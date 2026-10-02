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
- the URL round-trip restores filter state on reload (B-X), the 'all'
  sentinels on kind/sig included (fold F2), and reset leaves the canonical
  clean catalogue URL (F2's reset clause);
- the drill-down survives its own pushed URL: a reopen and a second-row
  drill without an intervening reload fetch their record URL cleanly (200),
  and a collapse's URL write targets the catalogue path, never the record
  URL (fold F1);
- a cloned multi-evidence / capability-bearing row stacks its cell badges
  in .cell-stack exactly like a static row (fold F8), wherever the served
  index carries such a row;
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
import re
import socket
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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
            #    theme, containment, requests, the fold's F1/F2/F8 sequences
            context = browser.new_context()
            requests: list[str] = []
            context.on("request", lambda request: requests.append(request.url))
            page = context.new_page()
            page.goto(origin, wait_until="networkidle")
            # F1 (lane B F1, the fold): the catalogue page's own path,
            # captured before any drill push can rebase the document URL.
            catalogue_path = urlsplit(page.url).path
            responses: list[tuple[str, int]] = []
            page.on("response", lambda response: responses.append((response.url, response.status)))

            def _drill_href(anchor: Any) -> str:
                """The anchor's href reduced to its relative record path —
                the stamped bytes are relative; the wiring upgrades them to
                absolute at load (F1) so a pushed record URL cannot rebase
                the next drill."""
                raw = anchor.get_attribute("href") or ""
                return raw if raw.startswith("records/") else urlsplit(raw).path.lstrip("/")

            def _drill_fetches(since: int, url: str) -> list[tuple[str, int]]:
                return [entry for entry in responses[since:] if entry[0].endswith("/" + url)]

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
            # cell (icon + visible text — B-I's browser half). The text filter
            # from the match flow above is cleared first (its needle names a
            # SIGNED row and would AND the reveal away).
            if unsigned:
                page.fill("#q", "")
                page.wait_for_timeout(400)
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

            # the drill-down (B-D): clicking a default row's anchor loads the
            # record page's #release-detail into the row's detail host, pushes
            # the record URL, and back restores the catalogue URL. (htmx's
            # back-restore swaps the DOM from its own snapshot cache, so the
            # collapse clause runs on a fresh reload below.)
            page.click("#bw-clear-filters")
            page.wait_for_timeout(400)
            first_anchor = page.locator(
                "#release-rows tr.bw-row[data-bw-package-id]:not([hidden]) "
                "a.release-name"
            ).first
            record_url = _drill_href(first_anchor)
            _check(record_url.startswith("records/"), f"unexpected drill href: {record_url}")
            fetches_before = sum(1 for url in requests if url == origin + "/" + record_url)
            first_anchor.click()
            page.wait_for_timeout(500)
            _check(
                page.locator("tr.bw-detail-row:not([hidden])").count() >= 1,
                "the drill-down opened no detail row",
            )
            _check(
                page.locator(
                    "tr.bw-detail-row:not([hidden]) .bw-detail-host #release-detail"
                ).count()
                == 1,
                "the record page's #release-detail did not load into the detail host",
            )
            _check(
                page.url.endswith(record_url),
                f"the drill did not push the record URL: {page.url}",
            )
            fetches_after = sum(1 for url in requests if url == origin + "/" + record_url)
            _check(
                fetches_after == fetches_before + 1,
                f"the drill fetched {fetches_after - fetches_before} time(s), expected 1",
            )
            page.go_back()
            page.wait_for_timeout(500)
            _check(
                not page.url.endswith(record_url),
                f"go-back did not restore the catalogue URL: {page.url}",
            )

            # collapse without re-fetch, on a fresh reload (fetch-once-per-row)
            page.reload(wait_until="networkidle")
            fresh_anchor = page.locator(
                "#release-rows tr.bw-row[data-bw-package-id]:not([hidden]) "
                "a.release-name"
            ).first
            fresh_url = _drill_href(fresh_anchor)
            _check(fresh_url == record_url, "the drill anchor moved between reloads")
            fresh_anchor.click()
            page.wait_for_timeout(500)
            _check(
                page.locator("tr.bw-detail-row:not([hidden])").count() >= 1,
                "the fresh drill-down opened no detail row",
            )
            fresh_anchor.click()  # collapse without re-fetch
            page.wait_for_timeout(300)
            _check(
                page.locator("tr.bw-detail-row:not([hidden])").count() == 0,
                "the second click did not collapse the detail row",
            )
            fetches_final = sum(1 for url in requests if url == origin + "/" + record_url)
            _check(
                fetches_final == fetches_after + 1,
                f"the collapse-cycle fetched {fetches_final - fetches_after} time(s) "
                "beyond the single open fetch (fetch-once-per-row broken)",
            )

            # F1c (lane B F1, the 2026-10-02 fold): the collapse's URL write
            # targets the CATALOGUE path — pre-fold it wrote the filter
            # params onto the pushed RECORD URL (location.pathname), so the
            # address bar claimed a record page that was never served and
            # every later relative URL rebased under it.
            _check(
                urlsplit(page.url).path == catalogue_path,
                f"the collapse left the URL off the catalogue path: {page.url} "
                f"(catalogue path is {catalogue_path})",
            )

            # F1a: REOPEN without an intervening reload. The URL is the
            # catalogue path again (F1c) but the history entry was a drill
            # push; pre-fold the reopen's relative hx-get resolved against
            # the pushed record URL and 404'd (records/<row>/records/<row>/…).
            reopen_anchor = page.locator(
                "#release-rows tr.bw-row[data-bw-package-id]:not([hidden]) "
                "a.release-name"
            ).first
            reopen_url = _drill_href(reopen_anchor)
            reopen_since = len(responses)
            reopen_anchor.click()
            page.wait_for_timeout(500)
            reopen_fetches = _drill_fetches(reopen_since, reopen_url)
            _check(
                any(status == 200 for _url, status in reopen_fetches),
                f"the reopen without reload did not fetch its record URL cleanly "
                f"(got {reopen_fetches} for {reopen_url})",
            )
            _check(
                page.locator(
                    "tr.bw-detail-row:not([hidden]) .bw-detail-host #release-detail"
                ).count()
                == 1,
                "the reopen did not re-open the detail row (the fetch 404'd?)",
            )

            # F1b: a SECOND row drills without an intervening reload — the
            # pushed URL of the first drill must not rebase the second's
            # fetch. Fires wherever the served index carries 2+ default
            # rows (the battery's synthetic site; a 1-row deploy skips).
            if len(defaults) >= 2:
                second_anchor = page.locator(
                    "#release-rows tr.bw-row[data-bw-package-id]:not([hidden]) "
                    "a.release-name"
                ).nth(1)
                second_url = _drill_href(second_anchor)
                second_row = defaults[1]
                second_host = "bw-detail-" + re.sub(
                    r"[^A-Za-z0-9-]", "-",
                    f"{second_row['package_id']}@{second_row['version']}",
                )
                second_since = len(responses)
                second_anchor.click()
                page.wait_for_timeout(500)
                second_fetches = _drill_fetches(second_since, second_url)
                _check(
                    any(status == 200 for _url, status in second_fetches),
                    f"the second-row drill without reload did not fetch its record "
                    f"URL cleanly (got {second_fetches} for {second_url})",
                )
                _check(
                    page.locator(
                        f"tr.bw-detail-row:not([hidden]) #{second_host} #release-detail"
                    ).count()
                    == 1,
                    f"the second drill did not open ITS detail row (host "
                    f"#{second_host}; the first row's detail may also be open "
                    "from the reopen — that is the design)",
                )
                _check(
                    page.url.endswith(second_url),
                    f"the second drill did not push its record URL: {page.url}",
                )

            # without JS the anchor navigates to a page that serves 200 from
            # the artifact (B-D's no-JS leg)
            nojs = browser.new_context(java_script_enabled=False)
            nojs_page = nojs.new_page()
            response = nojs_page.goto(origin + "/" + record_url, wait_until="load")
            _check(
                response is not None and response.status == 200,
                f"the record page did not serve 200 without JS: {record_url}",
            )
            _check(
                nojs_page.locator("main#release-detail").count() == 1,
                "the standalone record page lost its #release-detail region",
            )
            nojs.close()

            # F2 (lane B F2, the fold): the FULL filter set round-trips
            # through the URL. Pre-fold the 'all' sentinel elided from
            # kind/sig — a user who chose "All kinds"/"Any" reloaded back
            # to the CR-22 defaults and unsigned rows silently vanished.
            # The two sentinels now serialize explicitly; the arm also
            # carries evidence, maintenance, advisories, one capability,
            # and text with '&', '#' and non-ASCII.
            page.goto(origin, wait_until="networkidle")
            roundtrip_text = "rack & cab#le ü"
            page.select_option("#kind", "all")
            page.select_option("#sig", "all")
            page.select_option("#ev", "hardware")
            page.select_option("#maint", "unmaintained")
            page.select_option("#adv", "none")
            page.check('input[name="cap"][value="network_egress"]')
            page.fill("#q", roundtrip_text)
            page.wait_for_timeout(500)
            page.reload(wait_until="networkidle")
            _check(
                page.locator("#kind").input_value() == "all",
                "kind=All kinds did not survive the URL round-trip (the sentinel "
                "elided and the reload narrowed back to the CR-22 default)",
            )
            _check(
                page.locator("#sig").input_value() == "all",
                "sig=Any did not survive the URL round-trip",
            )
            _check(page.locator("#ev").input_value() == "hardware", "ev did not round-trip")
            _check(
                page.locator("#maint").input_value() == "unmaintained",
                "maint did not round-trip",
            )
            _check(page.locator("#adv").input_value() == "none", "adv did not round-trip")
            _check(
                page.locator("#q").input_value() == roundtrip_text,
                f"the text filter did not round-trip: {page.locator('#q').input_value()!r}",
            )
            _check(
                page.evaluate(
                    "document.querySelector('input[name=cap][value=network_egress]')"
                    ".checked === true"
                ),
                "the capability checkbox did not round-trip",
            )

            # F2's reset clause (the reviewer NIT folded here): reset writes
            # the canonical clean catalogue URL — pre-fold it left a
            # param-laden default URL (?kind=…&sig=…) behind.
            page.click("#bw-clear-filters")
            page.wait_for_timeout(400)
            _check(
                urlsplit(page.url).path == catalogue_path and not urlsplit(page.url).query,
                f"reset left a param-laden or off-path URL: {page.url}",
            )

            # F8 (reviewer R2, the fold): a CLONED row stacks like a static
            # row — multi-entry evidence and multi-line capability cells
            # render inside the .cell-stack flex column (the generator's
            # cell shape), not as an inline run. Fires wherever the served
            # index carries a non-default row with 2+ evidence entries (the
            # battery's synthetic site plants one; a 1-row deploy skips).
            stacked = next(
                (
                    row
                    for row in rows
                    if (row.get("kind"), row.get("signature_state"))
                    != ("admitted-release", "signed-valid")
                    and len(row.get("evidence") or []) >= 2
                ),
                None,
            )
            if stacked is not None:
                page.select_option("#kind", "all")
                page.select_option("#sig", "all")
                page.wait_for_timeout(300)
                pid = str(stacked["package_id"])
                stack = page.locator(f'tr[data-bw-package-id="{pid}"] td.td-evidence .cell-stack')
                _check(
                    stack.count() == 1,
                    f"a cloned {len(stacked.get('evidence') or [])}-evidence row does not "
                    "stack in .cell-stack (inline run — F8)",
                )
                _check(
                    stack.locator(".badge").count() == len(stacked.get("evidence") or []),
                    "the cloned evidence stack lost badges",
                )
            capped = next(
                (
                    row
                    for row in rows
                    if (row.get("kind"), row.get("signature_state"))
                    != ("admitted-release", "signed-valid")
                    and any((row.get("capabilities") or {}).values())
                ),
                None,
            )
            if capped is not None:
                page.select_option("#kind", "all")
                page.select_option("#sig", "all")
                page.wait_for_timeout(300)
                pid = str(capped["package_id"])
                wanted = sum(1 for value in (capped.get("capabilities") or {}).values() if value)
                cap_stack = page.locator(f'tr[data-bw-package-id="{pid}"] td.td-caps .cell-stack')
                _check(
                    cap_stack.count() == 1,
                    "a cloned capability-bearing row does not stack in .cell-stack (F8)",
                )
                _check(
                    cap_stack.locator(".cap-line").count() == wanted,
                    "the cloned capability stack lost lines",
                )
            page.click("#bw-clear-filters")
            page.wait_for_timeout(400)

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
        "filter state round-trips through the URL (sentinels included), reset "
        "writes the clean catalogue URL, the drill survives its own pushed URL "
        "(reopen and second-row), cloned rows stack, the unsigned reveal and "
        "the theme toggle work, and the only non-asset session request is the "
        "same-origin index fetch"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
