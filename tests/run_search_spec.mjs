// The search truth-table proof (issue #224 slice 2, B1) — lane 1.
//
// Runs the PURE filterRows predicate from catalogue/assets/plugins.js against
// the hand-derived truth table and the 10-row fixture. No framework, no npm:
// node requires the CommonJS-guard export of the same file the page serves.
// Driven by tests/test_catalogue_search.py; on any mismatch
// this prints the expected-vs-got pair and exits non-zero. Dimension breadth
// is this lane's job — the wiring proof on the assembled artifact is the
// docs workflow's browser arm.
//
// Also pins the CR-56 kind-tag projection (a row never renders without its
// kind tag) and the CR-37 marker display twin behaviour on rowSlots.
//
// Issue #227 slice 5 adds the shared-listing arms (E2, E3, E5): a kind badge
// on every row of every view, the default view free of community-shared rows,
// and the shared unverified marker structural in the row projection.

import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const plugins = require(join(here, '..', 'catalogue', 'assets', 'plugins.js'));
const fixture = JSON.parse(
  readFileSync(join(here, 'fixtures', 'plugins-index.fixture.json'), 'utf8'),
);
const table = JSON.parse(
  readFileSync(join(here, 'fixtures', 'plugins-search.truth-table.json'), 'utf8'),
);

const rows = fixture.rows;
const packageIds = (matched) => matched.map((row) => row.package_id).sort();
let failures = 0;
let ran = 0;

for (const testCase of table.cases) {
  ran += 1;
  const got = packageIds(plugins.filterRows(rows, testCase.query));
  const expect = [...testCase.expect].sort();
  if (JSON.stringify(got) !== JSON.stringify(expect)) {
    failures += 1;
    console.error(`FAIL ${testCase.id}`);
    console.error(`  expect: ${JSON.stringify(expect)}`);
    console.error(`  got:    ${JSON.stringify(got)}`);
  }
}

// CR-56: every row's rendered kind badge equals the DISPLAY MAP's rendering
// of the machine kind (the map is the single translation; a row never
// renders without its badge).
for (const row of rows) {
  const slots = plugins.rowSlots(row);
  if (slots.kind !== plugins.KIND_DISPLAY[row.kind]) {
    failures += 1;
    console.error(
      `FAIL kind-tag ${row.package_id}: '${slots.kind}' != '${plugins.KIND_DISPLAY[row.kind]}'`,
    );
  }
}

// CR-37: known markers render via the display map; an unknown marker id
// renders VERBATIM (forward-honest, never dropped). Issue #227 slice 5 moved
// the known-marker arm to an admitted row (the fixture's shared rows now carry
// only the shared marker, exactly as the generator emits them) and made the
// unknown-id arm synthetic (the fixture carries no unmapped id any more).
const admitted = rows.find((row) => row.package_id === 'northwind-instruments/northwind-psu');
const admittedMarkers = plugins.rowSlots(admitted).markers;
for (const known of ['conformance evidence self-attested', 'review is process, not proof']) {
  if (!admittedMarkers.includes(known)) {
    failures += 1;
    console.error(`FAIL marker-map: known marker '${known}' did not render via the display map`);
  }
}
const unmapped = plugins.rowSlots({ ...admitted, unverified_markers: ['future-marker-unmapped'] });
if (!unmapped.markers.includes('future-marker-unmapped')) {
  failures += 1;
  console.error('FAIL marker-map: unknown marker id was not rendered verbatim');
}

// E3 (CR-58): no mixed view without the tag showing. Every row of EVERY
// truth-table view carries its kind badge — the display map's rendering of
// its own machine kind, never empty and never another kind's.
let untagged = 0;
for (const testCase of table.cases) {
  for (const row of plugins.filterRows(rows, testCase.query)) {
    const badge = plugins.rowSlots(row).kind;
    if (badge !== plugins.KIND_DISPLAY[row.kind]) untagged += 1;
  }
}
if (untagged) {
  failures += 1;
  console.error(`FAIL kind-in-every-view: ${untagged} row rendering(s) carry no kind badge`);
}

// E2 (CR-22/CR-57): the UI's own default view holds no community-shared row,
// and it is exactly the truth table's default arm.
const sharedRows = rows.filter((row) => row.kind === 'community-shared');
const defaultCase = table.cases.find(
  (testCase) => testCase.id === 'default-view-admitted-and-signed',
);
const viaDefault = packageIds(plugins.filterRows(rows, plugins.DEFAULT_QUERY));
if (sharedRows.some((row) => viaDefault.includes(row.package_id))) {
  failures += 1;
  console.error('FAIL default-view: a community-shared row is in the default available listing');
}
if (JSON.stringify(viaDefault) !== JSON.stringify([...defaultCase.expect].sort())) {
  failures += 1;
  console.error('FAIL default-view: DEFAULT_QUERY is not the truth table default arm');
}

// E2/E5 (CR-57): a community-shared row's marker is STRUCTURAL in the row
// projection — it renders even when the index row's own marker list is empty
// or foreign, so no shared row can clone without it.
const SHARED_MARKER_DISPLAY = 'shared by the author, not reviewed';
if (sharedRows.length !== 2) {
  failures += 1;
  console.error(`FAIL shared-set: expected 2 community-shared rows, found ${sharedRows.length}`);
}
for (const shared of sharedRows) {
  for (const planted of [[], ['future-marker-unmapped'], ['review-is-process-not-proof']]) {
    const markers = plugins.rowSlots({ ...shared, unverified_markers: planted }).markers;
    if (!markers.includes(SHARED_MARKER_DISPLAY)) {
      failures += 1;
      console.error(
        `FAIL shared-marker: ${shared.package_id} with markers ${JSON.stringify(planted)} renders no shared marker`,
      );
    }
  }
  if (plugins.rowSlots(shared).signature !== 'unsigned') {
    failures += 1;
    console.error(`FAIL shared-marker: ${shared.package_id} does not project the unsigned cell`);
  }
}

// The records table renders no badge for empty evidence (the record page
// carries the explicit-none) — the projection must carry an empty list.
const noEvidence = rows.find((row) => row.package_id === 'northwind-instruments/northwind-load');
if (plugins.rowSlots(noEvidence).evidence.length) {
  failures += 1;
  console.error('FAIL evidence-empty: the empty-evidence projection is not empty');
}

if (failures) {
  console.error(`${failures} failure(s) over ${ran} truth-table case(s)`);
  process.exit(1);
}
console.log(
  `OK ${ran} truth-table case(s) + kind-tag + kind-in-every-view + default-view + ` +
    'shared-marker + marker-map + evidence-empty arms',
);
