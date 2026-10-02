"""The catalogue search contract (issue #224 slice 2, CR-24/CR-25; pivot §2.5).

The 10-row fixture and the hand-derived truth table are committed BEFORE
any search code lands in this repository (the C1 discipline, preserved by
the relocation): these consistency arms validate the TABLE against the
FIXTURE — every expected id exists, every dimension is covered, the
denominator is CR-24's own — without needing the predicate. The predicate
proof (node, over ``catalogue/assets/plugins.js``) and the wiring proof
(the Pages deploy gate's browser arm) are the other two lanes.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
FIXTURE = FIXTURES / "plugins-index.fixture.json"
TRUTH_TABLE = FIXTURES / "plugins-search.truth-table.json"
SEARCH_SPEC = Path(__file__).resolve().parent / "run_search_spec.mjs"
PLUGINS_JS = REPO / "catalogue" / "assets" / "plugins.js"

# The query keys filterRows understands. A case may carry any subset; an
# absent key means no filter on that dimension (the UI's initial state is
# the "default view" case — admitted releases with a valid signature).
QUERY_KEYS = {
    "text",
    "publisher",
    "capabilities",
    "standard_version",
    "signature_state",
    "maintenance",
    "advisories",
    "kind",
    "evidence_level",
}
DIMENSIONS = {
    "name",
    "publisher",
    "capability",
    "standard_version",
    "status",
    "kind",
    "evidence",
    "sentinel",
    "default",
    "negative",
    "combined",
}


def _rows() -> list[dict[str, Any]]:
    return list(json.loads(FIXTURE.read_text(encoding="utf-8"))["rows"])


def _cases() -> list[dict[str, Any]]:
    return list(json.loads(TRUTH_TABLE.read_text(encoding="utf-8"))["cases"])


def test_truth_table_is_internally_consistent() -> None:
    """Every expected id exists in the fixture; cases are well-formed.

    The guard that makes the truth table's own claims falsifiable: a
    hand-derived expected set naming a package the fixture does not carry
    is a derivation error, and must fail here rather than quietly
    under-counting an arm.
    """
    known = {str(row["package_id"]) for row in _rows()}
    cases = _cases()
    assert cases, "the truth table carries no cases"
    seen_ids: set[str] = set()
    for case in cases:
        case_id = str(case["id"])
        assert case_id not in seen_ids, f"duplicate case id: {case_id}"
        seen_ids.add(case_id)
        assert case["dimension"] in DIMENSIONS, f"{case_id}: unknown dimension {case['dimension']}"
        query = dict(case["query"])
        unknown = sorted(set(query) - QUERY_KEYS)
        assert not unknown, f"{case_id}: unknown query key(s) {unknown}"
        expect = list(case["expect"])
        assert expect == sorted(set(expect)), f"{case_id}: expect must be sorted and unique"
        missing = sorted(set(expect) - known)
        assert not missing, f"{case_id}: expect names id(s) absent from the fixture: {missing}"


def test_truth_table_covers_every_dimension() -> None:
    """CR-24's dimensions are all exercised, plus the sentinel, negative and
    combined arms the pivot's B1' adds (§5: text:'all' expects the EMPTY
    set — the sentinel-leak kill — and the two-capability AND arm pins the
    multi-capability semantics as AND)."""
    covered = {str(case["dimension"]) for case in _cases()}
    for dimension in (
        "name", "publisher", "capability", "standard_version", "status", "kind", "evidence",
    ):
        assert dimension in covered, f"no truth-table case covers dimension: {dimension}"
    assert "sentinel" in covered, "the sentinel arms (B1') are missing"
    assert "negative" in covered, "the nonexistent-query arm is missing"
    assert "combined" in covered, "the combined-query arm is missing"
    negative = [c for c in _cases() if c["dimension"] == "negative"]
    assert all(list(c["expect"]) == [] for c in negative), "a negative arm must expect zero rows"


def test_dropped_selects_stay_predicate_dimensions() -> None:
    """The #224 follow-on dropped the publisher and standard-version SELECTS
    from the shipped UI (the mockup carries neither; publisher stays reachable
    through text search). The PREDICATE keeps both dimensions, so both stay
    truth-table-tested — this arm refuses a future 'clean-up' that deletes the
    dimensions' cases (or the dimension itself) just because no select exposes
    them."""
    covered = {str(case["dimension"]) for case in _cases()}
    assert "publisher" in covered, (
        "the publisher dimension lost its truth-table coverage when the UI "
        "dropped its select — the predicate still filters on it"
    )
    assert "standard_version" in covered, (
        "the standard-version dimension lost its truth-table coverage when the "
        "UI dropped its select — the predicate still filters on it"
    )


def test_sentinel_arm_expects_the_empty_set_not_the_catalogue() -> None:
    """B1's exact kill (pivot §4 row 4): a text query for the literal string
    'all' must expect the empty set — no fixture row's name, id or summary
    contains it. A predicate that treats 'all' as the no-filter sentinel
    returns the full catalogue and reddens the node lane."""
    arm = next(c for c in _cases() if c["id"] == "sentinel-text-all-is-a-literal-query")
    assert list(arm["expect"]) == []
    haystacks = [
        " ".join(
            [str(r.get("display_name") or ""), str(r.get("package_id") or ""),
             str(r.get("summary") or "")]
        ).lower()
        for r in _rows()
    ]
    assert not any("all" in h for h in haystacks), (
        "the fixture grew a row containing 'all' — re-derive the sentinel arm"
    )


def test_the_capability_and_arm_is_derived_from_both_flags() -> None:
    """R1 (pivot §4): multiple capability filters are AND — the arm's
    expected set is re-derived here from the fixture's own booleans, so the
    table cannot drift from the data."""
    arm = next(c for c in _cases() if c["id"] == "capability-and-two-capabilities")
    assert arm["query"]["capabilities"] == ["network_egress", "subprocess_or_native_library"]
    derived = sorted(
        str(r["package_id"])
        for r in _rows()
        if r["capabilities"]["network_egress"] and r["capabilities"]["subprocess_or_native_library"]
    )
    assert list(arm["expect"]) == derived


def test_fixture_carries_cr24s_denominator() -> None:
    """The 11-row fixture represents every dimension value the arms need.

    CR-24's own denominator (10 rows, all dimensions represented) grown by the
    #224 follow-on with ONE hardware-evidence row: 3 publishers; kinds
    admitted-release x8, community-shared x2, in-tree-fixture x1; signature
    signed x8 / unsigned x3; all four maintenance values; stg_versions
    {1.4, 1.5} and otdp_versions {0.2.1, 0.2.2}; all eight capability boolean
    combinations; advisories on at least two rows; evidence levels
    {hardware, simulated, structural} represented (the follow-on's evidence
    facet — the slice-2 ten rows carried no hardware row); and one
    publisher/name-prefix pair sharing a disambiguation boundary.
    """
    rows = _rows()
    assert len(rows) == 11, f"the fixture is 11 rows, got {len(rows)}"
    assert len({row["publisher"] for row in rows}) == 3
    kinds = [row["kind"] for row in rows]
    assert kinds.count("admitted-release") == 8
    assert kinds.count("community-shared") == 2
    assert kinds.count("in-tree-fixture") == 1
    signatures = [row["signature_state"] for row in rows]
    assert signatures.count("signed-valid") == 8
    assert signatures.count("unsigned") == 3
    assert {row["maintenance"] for row in rows} == {
        "maintained", "maintenance_only", "unmaintained", "unknown",
    }
    stg = {v for row in rows for v in row["compatibility"]["stg_versions"]}
    otdp = {v for row in rows for v in row["compatibility"]["otdp_versions"]}
    assert stg == {"1.4", "1.5"}, stg
    assert otdp == {"0.2.1", "0.2.2"}, otdp
    combos = {
        (
            row["capabilities"]["network_egress"],
            row["capabilities"]["subprocess_or_native_library"],
            row["capabilities"]["filesystem_writes_beyond_evidence_retention"],
        )
        for row in rows
    }
    assert len(combos) == 8, f"all eight capability combinations required, got {len(combos)}"
    assert sum(1 for row in rows if row["advisories"]) >= 2
    levels = {e["level"] for row in rows for e in row["evidence"]}
    assert levels == {"hardware", "simulated", "structural"}, levels
    # the hardware row is OUTSIDE the default view (unsigned) — the static
    # default stays the CR-22 set; the facet reaches it by explicit filter
    hardware_rows = [
        row for row in rows
        if any(e["level"] == "hardware" for e in row["evidence"])
    ]
    assert len(hardware_rows) == 1, "exactly one hardware-evidence row"
    assert hardware_rows[0]["signature_state"] == "unsigned"
    # the disambiguation pair: one publisher, one name prefix, two rows
    prefixes = [(row["publisher"], str(row["package_id"]).split("/")[1][:10]) for row in rows]
    assert len(set(prefixes)) < len(prefixes), "no publisher/name-prefix pair to disambiguate"


def test_fixture_names_are_invented() -> None:
    """Public-repo hygiene: the fixture carries invented names only — three
    synthetic publishers, nothing real."""
    assert {row["publisher"] for row in _rows()} == {
        "copperleaf-labs",
        "harborline-systems",
        "northwind-instruments",
    }


# ── lane 1: the predicate proof (node over the same file the page serves) ────


def test_node_is_present() -> None:
    """Fail loudly when node is absent — a skip would be a silent hole.

    The predicate proof runs on node (preinstalled on the GitHub-hosted
    ubuntu runner; the standing no-self-hosted-runners posture keeps that
    true); this test is the harness gate, and B1's underpowered-
    discrimination clause says a harness failure is neither pass nor kill —
    it blocks.
    """
    found = shutil.which("node")
    assert found is not None, (
        "node is required for the search truth-table lane "
        "(tests/run_search_spec.mjs) and is missing from PATH — the harness "
        "is broken, not the predicate"
    )
    result = subprocess.run([found, "--version"], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_search_truth_table() -> None:
    """B1'/B1's search-truth arm, evaluated by the node spec over filterRows.

    Every dimension arm must return the exactly-correct filtered set for
    all 10 rows (the truth table is the authority, hand-derived before any
    search code — C1). KILL: any wrong row in any dimension arm, including
    the sentinel arm (text 'all' = the empty set, never the full
    catalogue). On failure the node spec's own expected-vs-got lines are
    the evidence surface.
    """
    node = shutil.which("node")
    assert node is not None, "node missing — see test_node_is_present"
    result = subprocess.run(
        [node, str(SEARCH_SPEC)], capture_output=True, text=True, check=False, cwd=REPO
    )
    assert result.returncode == 0, (
        "search truth-table mismatch (node spec output follows)\n" + result.stdout + result.stderr
    )
    assert "OK" in result.stdout, result.stdout


def test_pure_predicates_stay_dom_free() -> None:
    """The CommonJS guard export shape: requiring the file from node must not
    need a DOM and must expose the pure half. The wiring half is
    browser-only and silent under node (the typeof document guard)."""
    node = shutil.which("node")
    assert node is not None, "node missing — see test_node_is_present"
    script = (
        "const m = require(process.argv[1]);"
        "if (typeof m.filterRows !== 'function' || typeof m.rowSlots !== 'function') "
        "{ console.error('missing pure exports'); process.exit(1); }"
        "const rows = [{package_id: 'a/b', display_name: 'x', summary: '',"
        " kind: 'admitted-release', signature_state: 'signed-valid', publisher: 'p',"
        " maintenance: 'unknown', advisories: [],"
        " capabilities: {network_egress: false, subprocess_or_native_library: false,"
        " filesystem_writes_beyond_evidence_retention: false},"
        " compatibility: {stg_versions: [], otdp_versions: [], adapter_api_versions: []}}];"
        "const got = m.filterRows(rows, {text: 'nope'});"
        "if (!Array.isArray(got) || got.length !== 0) "
        "{ console.error('predicate needs a DOM'); process.exit(1); }"
        "const slots = m.rowSlots(rows[0]);"
        "if (slots.kind !== m.KIND_DISPLAY['admitted-release']) "
        "{ console.error('rowSlots kind projection broken'); process.exit(1); }"
        "console.log('OK');"
    )
    result = subprocess.run(
        [node, "-e", script, str(PLUGINS_JS)],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_yanked_release_is_unreachable_by_search() -> None:
    """B1's yank arm, search half: a row the registry generator dropped from
    the index is not in the index the page fetches, so no query can reach
    it — search reflects the records of record (CR-25). The generator-side
    drop is tests/test_generate_index.py's matrix."""
    index_path = REPO / "index.json"
    rows = json.loads(index_path.read_text(encoding="utf-8"))["rows"]
    assert rows, "the dogfooded release must seed the index"
    pid = str(rows[0]["package_id"])
    node = shutil.which("node")
    assert node is not None, "node missing — see test_node_is_present"
    script = (
        "const m = require(process.argv[1]);"
        "const fs = require('fs');"
        "const rows = JSON.parse(fs.readFileSync(process.argv[2], 'utf8')).rows;"
        "const before = m.filterRows(rows, {text: process.argv[3]});"
        "if (before.length === 0) "
        "{ console.error('precondition: the query reaches the row today'); process.exit(1); }"
        "const after = rows.filter((row) => row.package_id !== process.argv[3]);"
        "const got = m.filterRows(after, {text: process.argv[3]});"
        "if (got.length !== 0) "
        "{ console.error('a dropped row is still reachable'); process.exit(1); }"
        "console.log('OK');"
    )
    result = subprocess.run(
        [node, "-e", script, str(PLUGINS_JS), str(index_path), pid],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout
