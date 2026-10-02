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

// CR-56: every row's rendered kind tag equals the machine kind — the tag
// is the row's identity in any view (never rendered without it).
for (const row of rows) {
  const slots = plugins.rowSlots(row);
  if (slots.kind !== row.kind) {
    failures += 1;
    console.error(`FAIL kind-tag ${row.package_id}: '${slots.kind}' != '${row.kind}'`);
  }
}

// CR-37: known markers render via the display map; an unknown marker id
// renders VERBATIM (forward-honest, never dropped).
const shared = rows.find((row) => row.package_id === 'harborline-systems/harborline-relay16');
const sharedMarkers = plugins.rowSlots(shared).markers.map((entry) => entry.text);
if (!sharedMarkers.includes('conformance evidence self-attested')) {
  failures += 1;
  console.error('FAIL marker-map: known marker did not render via the display map');
}
if (!sharedMarkers.includes('community-shared-not-vetted')) {
  failures += 1;
  console.error('FAIL marker-map: unknown marker id was not rendered verbatim');
}

// CR-20's "or explicitly none" on the clone projection: a row with empty
// evidence carries the explicit-none text in its slot projection.
const noEvidence = rows.find((row) => row.package_id === 'northwind-instruments/northwind-load');
const noEvidenceSlots = plugins.rowSlots(noEvidence);
if (noEvidenceSlots['evidence-none'] !== 'no test evidence' || noEvidenceSlots.evidence.length) {
  failures += 1;
  console.error('FAIL evidence-none: the empty-evidence projection is not explicit-none');
}

if (failures) {
  console.error(`${failures} failure(s) over ${ran} truth-table case(s)`);
  process.exit(1);
}
console.log(`OK ${ran} truth-table case(s) + kind-tag + marker + evidence-none arms`);
