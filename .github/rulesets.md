# Records-branch ruleset (CR-61)

The recorded shape of the `main` branch ruleset on this repository. The
platform owns enforcement; this file is the committed record of what is
configured, so a reader can tell configured intent from platform behavior
(which is disclosed, not claimed).

| Setting | Value |
|---|---|
| Target | `main` |
| Required approvals | 1 (a human reviewer other than the author; the standards-coordinator carve-out follows the gateway GOVERNANCE ruling) |
| Required status checks | `validity / Records validity (CR-9/10/56/60, CR-38, CR-35)`, `validity / Unit tests (validity arms)`, `replay / Admission replay through unmodified gateway admission (CR-13)` |
| Linear history | enforced |
| Force pushes | denied |
| Direct pushes | denied (administrators included) |

Secret scanning (with push protection and the PEM custom pattern) and
dependency-review are configured at the repository level (CR-59); their
detection quality is platform-owned and explicitly not claimed here.
