# benchweave-registry

The repository of record for the BenchWeave contributor publishing lane: review
records, lifecycle records, vetted publishers, lane rules, and the published,
signed releases themselves. Git-native by design — a submission is a pull
request, there is no service, and a clean clone of this repository alone is
sufficient to validate every record and verify every published release's
digests and signatures (CR-34).

Layout:

| Path | What it is |
|------|------------|
| `records/records.schema.json` | The lane-owned schema over canonical-JSON records (CR-9/CR-10/CR-56/CR-60). |
| `records/submissions/…` | Committed review records (CR-8/CR-9; PR threads stay discussion-only, Q4). |
| `records/lifecycle/…` | Publish / yank / advisory / unlist / takedown / transfer records (CR-28). |
| `records/publishers.json` | Vetted publisher identities and namespace assignments (CR-15/CR-39). |
| `lane-rules.json` | Reserved namespaces, the similarity rule with committed vectors (CR-39), the pre-committed `scoped_transport` tier rule (Q15/CR-49), the capability enumeration (CR-45). |
| `review-checklist.md` | The versioned owner checklist with machine-citable row ids (CR-8), extending the gateway's device-developer-guide §12. |
| `releases/<registry-id>/<publisher>/<plugin>/<version>/` | The served release tree (`manifest.json`, `manifest.sig`, `status.json`, `status.sig`, `payload.zip`) — layout satisfies the gateway's `LocalDirectorySource` contract, so a clone is a resolvable origin. |
| `keys/main.pub.pem` | The public trust root. The private half is maintainer-custodied and never enters this repository or any CI (CR-12). |
| `gateway-ref` | The pinned gateway commit the admission replay runs at (Q10, F5). |
| `scripts/validate_records.py` | The records-validity gate (CI job `validity`). |
| `scripts/replay_admission.py` | The authoritative admission replay through unmodified gateway admission (CI job `replay`). |
| `scripts/verify.py` | Whole-clone verification: records + signatures + digests + the accountability chain (CR-54). |

## Verifying a release (two commands, nothing else)

```
git clone https://github.com/madeinoz67/benchweave-registry.git
cd benchweave-registry && uv run python scripts/verify.py
```

That prints the accountability chain for every published release — publisher,
reviewer, outcome, closure digest, capability declaration — from this clone
alone: no gateway repository, no PR thread, no running service (S3/A3).

## Publishing path (summary)

1. Package a finished plugin with `benchweave-sdk package` (the SDK CLI;
   deterministic, keyless, entry-gated — dev-lineage, mutable source refs,
   missing capability declarations, firmware without vendor attestation,
   transport declarations without triples, and publish records without a
   closure diff all refuse at packaging time with stable prefixes).
2. Open the submission with `benchweave-sdk submit` — a branch in a working
   copy of this repository plus a PR (or a printed compare URL when `gh` is
   absent). No service is required at any point (CR-6).
3. The maintainer reviews against `review-checklist.md` plus the machine
   evidence (platform findings at the pinned revision, CR-60), records the
   outcome under `records/submissions/`, and signs the accepted release with
   the maintainer-custodied key (`scripts/registry/sign_release.py` in the
   gateway repository). The review block rides inside the signed manifest
   (registry standard 0.1.2; Q2) — one signature attests release and review
   together.
4. CI replays admission through unmodified gateway admission at the pinned
   `gateway-ref` before anything merges.

## What this repository is not

There is no registry service (a later, explicitly-scoped effort), and nothing
here authorizes control on any gateway: publication is discovery and
provenance, commissioning stays local (REG-3). Digest verification establishes
byte integrity — never measurement truth, never intent (CR-51/NFR-S1).

## Branch protection (CR-61)

The `main` branch enforces required approvals, the records-validity and
admission-replay checks as required status checks, linear history, no force
pushes and no direct pushes — configured as a repository ruleset (see
`.github/rulesets.md` for the recorded shape; the platform owns enforcement).
