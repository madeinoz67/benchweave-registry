# Publishing review checklist — version 1

The versioned owner checklist for reviewing plugin submissions (CR-8). Records
cite rows by id; the records-validity CI checks citations. The base rows R-01
to R-08 extend `docs/device-developer-guide.md` §12 ("Human review and
acceptance", eight verification bullets) in the gateway repository — that
section stays the integration-review authority; this checklist adds the
publishing rows on top and cites the machine evidence (CR-60) alongside each.

Checklist id: `review-checklist` · version: `1` · rows: 15.

## Base rows (integration, from the gateway §12 checklist)

| Row | Requirement |
|-----|-------------|
| R-01 | Every claimed capability and model limit traces to the stated device/firmware evidence. |
| R-02 | Descriptor, implementation, profiles, permissions, hashes and package metadata agree. |
| R-03 | Required actions work; unsupported features are absent or explicitly blocked, with no success placeholders. |
| R-04 | Invalid inputs stop before I/O; post-dispatch uncertainty, cancellation and reconnect cannot silently replay physical work. |
| R-05 | Returned data has correct units, quality, timing, configuration/acquisition identity and assurance. |
| R-06 | Tests include applicable negative paths, run reproducibly, and are included in CI. |
| R-07 | Documentation explains installation/admission prerequisites, limitations, maintenance ownership and the exact evidence level. |
| R-08 | Hardware and unattended claims have separate bench-specific qualification evidence. |

## Publishing rows

| Row | Requirement | Source |
|-----|-------------|--------|
| P-01 | The submission's source linkage is an immutable commit digest (40- or 64-hex), not a moving branch or tag name. | CR-36 |
| P-02 | No dependency in the closure resolves through a dev-unsigned origin (dev-prefixed registry id); the published tree contains zero dev-prefixed registry ids. | CR-35 |
| P-03 | The closure diff versus the prior release of the same package is present, and the sign-off names the closure digest actually published. | CR-38 |
| P-04 | The capability declaration is present and displayed in the approval decision input (network egress / subprocess or native-library use / filesystem writes beyond evidence retention; all-false is an explicit none). | CR-45 |
| P-05 | A descriptor declaring a transport provider publishes its admitted contract triples; the scoped_transport tier rule is applied as pre-committed in `lane-rules.json`. | CR-49, Q15 |
| P-06 | Any bundled firmware carries vendor-signed provenance pinned against a vendor manifest — not the publisher's own signature alone. | CR-50 |
| P-07 | The platform findings consulted at the pinned revision (code scanning, dependency review, secret scanning) are recorded as machine evidence; the identified-reviewer requirement is unchanged and findings are advisory. | CR-60, Q6 |

## Disclosures carried on every accepted review record

These ride the review record schema as required fields, so an approval cannot
be recorded without them:

- **Execution model (CR-52).** In-process execution with full gateway
  authority; no Python sandbox. The approver was told what the approval grants.
- **Publisher-repo protections (Q21).** Declared-not-verified: the lane makes
  no enforcement claim over repositories it cannot read.
- **Measurement truth (CR-51).** Run evidence is integrity-pinned but
  content-unverified against a lying adapter; cross-validation against a second
  qualified instrument is the named detection lane, not a built one.

## What this checklist does not establish

Structural validity never establishes trust. Digest verification does not
establish measurement truth, a clean scan does not mark a release verified, and
a correctly-signed release carries no technical backstop against malicious
intent — publish-time review owns that residual (PRD §5(l.6), NFR-S1).
