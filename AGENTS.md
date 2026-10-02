# AGENTS.md — the registry repository's agent constitution

This file governs how AI agents work in `benchweave-registry`: what the
repository *is*, the conventions that bind every change, and where things
live. The family template comes from the SDK repo (the canonical first-class
sibling); the deltas are named below.

## 1. What this repository is

The **repository of record for the BenchWeave contributor publishing lane**:
review records, lifecycle records, vetted publishers, lane rules, the versioned
review checklist, the public trust root, and the published, signed releases
themselves — plus the catalogue index generated from them. Git-native by
design: a submission is a pull request, there is no service, and a clean clone
alone verifies every record, signature and digest.

The design authority: `docs/implementation-planning/10-contributor-publishing-design.md`
in the **gateway** repository (issue #209's record; slice 1 is issue #223).
The signing half (`scripts/registry/sign_release.py`) and the contributor
tooling (`benchweave-sdk package` / `submit`) live in the sibling repos.

## 2. The generated index is a format contract (forward compatibility)

`index.json` is THE one generated JSON index serving catalogue, search and
verification (PRD §9 Q7/CR-26). Its format is pinned by
`records/index.schema.json` and produced by `scripts/generate_index.py`;
it is never hand-edited (CR-21) — `generate_index.py --check` refuses drift in
CI. **A later slice that adds the website/catalogue UI CONSUMES this index and
renders it; it never reshapes the records schema or the index format.** The
row fields are forward-complete for that rendering (kind, publisher, unverified
markers, maintenance state — see §6).

## 3. Tracker and labels (single issue stream)

All issues for every repo in the family file on the **gateway tracker**
(`madeinoz67/benchweave/issues`); this repository has no tracker of its own.
The tracker uses a three-label repo taxonomy — `registry`, `sdk`, `gateway` —
and every issue is labeled by its primary surface. **Registry work carries the
`registry` label** (applied to #209 and #223–#228; the publishing lane's
cross-repo work is registry-surfaced). PRs in this repository reference a
gateway-tracker issue in their body; no PR merges without one.

## 4. Web surface uses the MAIN repo's styleguide (hard convention)

The catalogue/search website a later slice renders from the index uses the
**main BenchWeave repository's public-site styleguide** —
`docs/internal/public-site-styleguide.html` in `madeinoz67/benchweave`
("BenchWeave — Public Site Style Guide": Space Grotesk / IBM Plex Sans /
IBM Plex Mono, the family's public design language). One design language
across the family; **no second component library, no new design system**
(the PRD-11 rule). Console-shaped surfaces follow the main repo's
`docs/internal/ui-styleguide.md`. The reference is pinned to those files; do
not guess or fork a styleguide here.

## 5. Agent working rules (the family posture)

- **Gortex mandate.** This repository is gortex-tracked; prefer graph queries
  over file reads (`mcp__gortex__read`, `search`, `relations`), and route
  edits per the routing card: tracked file in the primary checkout →
  `mcp__gortex__edit`; branch-new/untracked files → native Write; linked
  worktrees → the overlay caveat row. Subagents do not go through this
  session's hook — brief them with the mandate.
- **Worktree discipline.** Parallel-lane worktrees live UNDER the repo root at
  `.wt/<lane>-<nonce>/` (gitignored), never `/tmp`; the lane's session CWD is
  the worktree (gortex discovers it as an overlay). `git worktree list`
  before any remove; remove only your own. The stash stack is shared across
  the family's worktrees — never a blind `git stash pop`.
- **Memory protocol.** Durable findings go through
  `.claude/hooks/memory-propose.mjs` (tags required, ≥1 besides the identity
  tag). Proposals from THIS repository carry the **`registry` tag**
  (validator-enforced); the drain moves them into the `benchweave` vault on
  PreCompact / SessionEnd / Stop. See `.claude/memory-protocol.md` for the
  bar and the do-not-propose list.
- **Keys and secrets.** The registry VALIDATES + PUBLISHES + LABELS, never
  signs (owner ruling 2026-10-02): there is no registry signing key. Publishers
  sign at package time; `records/publishers.json` records their PUBLIC keys
  and validity windows — what signatures verify against. A present signature
  that does not verify is rejected; an unsigned release publishes labeled
  `unsigned`. Secret scanning with push protection is on; a PEM-shaped
  fixture push is refused.
- **Records discipline.** Records are canonical JSON, schema-validated, and
  append-only in spirit: nothing rewrites a published release or its history
  (CR-32; git history is the floor). The validity gate
  (`scripts/validate_records.py`) and the admission replay
  (`scripts/replay_admission.py`, at the committed `gateway-ref` pin) run in
  CI on every PR.

## 6. Public-repo hygiene

This repository is public. The records and the index carry submission content:
invented names in every fixture, no real bench/corpus/device/client
identifiers, no local-machine artifacts, no credentials. A measurement corpus
is "a real bench" — keep the numbers, drop the name. Publisher identities are
GitHub identities plus a publisher name (NFR-7); nothing more is collected.
Honesty rules bind every surface: structural validity never establishes
trust, a clean scan never renders as "verified", and the index's unverified
markers stay on every self-attested surface (CR-37/NFR-S1).

## 7. Verification (the real gates)

From the repository root, with `UV_PROJECT_ENVIRONMENT=venv`:

```
uv run ruff check .
uv run mypy        # fresh cache: rm -rf .mypy_cache
uv run pytest -q
uv run python scripts/validate_records.py
uv run python scripts/generate_index.py --check
```

The registry STATES AND ADVERTISES (owner ruling, issue #223 rework): each
publish record carries the `gateway_ref` it targets and the index advertises
it; admission is NOT enforced at publish time — the client enforces at import
(`scripts/replay_admission.py` verifies on demand against a gateway checkout
at the recorded pin; the repo-level `gateway-ref` file advertises the lane's
current default and the CI drift notice warns when gateway main passes it).
