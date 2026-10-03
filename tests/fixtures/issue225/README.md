# Issue #225 slice-3 fixture set (queue stages, namespace/vetting, PR state)

These fixtures and BOTH truth tables commit FIRST — before any command or
gate code (the design record's ordering law, §5; the PR body proves it with
`git merge-base --is-ancestor`). They are the acceptance contract for both
lanes of the slice: the registry repo's validity-gate arms consume the
namespace/vetting/lifecycle rows; the SDK's `registry queue` consumes the
queue tree, the PR-state fixture and the queue truth table. Invented names
only — `northwind-instruments` / `harborline-systems` (the slice-2 fixture
namespace).

## Layout

| Path | What it is |
|------|------------|
| `queue-records/` | A standalone records tree (`records/publishers.json`, submissions, lifecycle) covering all 7 queue stages across 2 publishers × 4 submissions. Not validated by records CI — it is derivation input, not a served tree. |
| `pr-state.json` | The PR-state fixture every `registry queue --pr-state` run reads: PR entries name their submission explicitly (publisher/plugin/version), review states mirror `gh`'s vocabulary, `carried_files` are repo-relative paths the PR tree adds. The live path derives the same shape from `gh pr list --json`. |
| `queue-truth-table.json` | Hand-derived stage per submission × mode (full / records-only), with `partial_flags` naming the `stage_partial` disclosures records-only mode must print. |
| `namespace-vetting.truth-table.json` | Hand-derived expectations for the namespace arm, the vetting-citation arm, the lifecycle pair checks, the transfer arm and the generator's unlist/boundary cells — the refusal prefixes are the contract. |

## Stage coverage (queue-truth-table)

| Submission | Full mode | Records-only |
|---|---|---|
| northwind-instruments/alpha-tool@1.0.0 | published | published |
| northwind-instruments/beta-tool@1.0.0 | withdrawn | withdrawn |
| northwind-instruments/gamma-tool@1.0.0 | signed | accepted (partial) |
| northwind-instruments/delta-tool@1.0.0 | submitted | absent |
| harborline-systems/anchor-meter@2.0.0 | accepted | accepted |
| harborline-systems/bore-probe@1.0.0 | changes requested | changes requested |
| harborline-systems/cargo-scale@1.0.0 | in review | absent |
| harborline-systems/deck-sensor@1.0.0 | withdrawn | absent |

`withdrawn` is covered twice on purpose: once by a committed withdraw record
(beta-tool) and once by a closed-unmerged PR with no publish record
(deck-sensor) — the two derivation paths design §2.2 names.

## The similarity vectors' comparison sets (disclosed reading)

`lane-rules.json` commits five similarity vectors whose expected labels are
satisfied by a classifier with TWO comparison sets, not one: a candidate
near (or skeleton-containing) a RESERVED namespace is `reserved`; a candidate
near a VETTED namespace is `lookalike`. The vectors do not type their
`existing` value — and `benchweave` sits in `reserved_namespaces` while
vectors 1–2 exercise it as an incumbent vetted namespace — so each vector's
expected label types the set it runs against (`comparison_set` in the truth
table). Both lanes' twin tests pin the same five vectors against this
reading; a flat single-set classifier cannot satisfy all five.

## Fixture publishers

The two fixture publishers carry synthetic Ed25519 public keys (generated
for this fixture, never used to sign anything) and v2-shaped `vetting`
blocks citing all six V-rows of `vetting-checklist.md` v1 — the shape the
publishers schema v2 requires once slice 3 lands.
