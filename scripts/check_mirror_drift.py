#!/usr/bin/env python3
"""Refuse a registry push that leaves the gateway's catalogue mirror behind.

Issue #224 slice 2 — the registry-side half of "a records change without
regeneration fails CI both sides". Regenerates the index in memory from
``records/`` + ``releases/`` and byte-compares it against the gateway
repository's committed ``website/plugins-index.json`` on its default branch
(raw fetch; CI has network, the site never does). Refuses ``mirror_drift:``
on mismatch or on fetch failure (one retry — a network failure is
indistinguishable from a missing mirror, so fail closed).

Runs on PUSH TO MAIN ONLY (never ``pull_request``): during any records PR's
review the gateway mirror is necessarily behind, so a PR-scoped arm would
be red on every correct submission.

Manual-only sync (owner ruling 2026-10-02): no bot PRs, no cross-repo
token. A human runs the documented sync commands (see README, "Keeping the
gateway catalogue in sync") and opens the gateway PR; this gate keeps
registry main honest until that lands — a red drift gate is the accepted
honest intermediate, and the refusal names the sync.

Usage::

    python scripts/check_mirror_drift.py
    python scripts/check_mirror_drift.py --expected path/to/plugins-index.json
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO = Path(__file__).resolve().parents[1]
GATEWAY_MIRROR_URL = (
    "https://raw.githubusercontent.com/madeinoz67/benchweave/main/website/plugins-index.json"
)


def _fetch(url: str) -> bytes | None:
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(url, timeout=20) as response:  # noqa: S310
                body: bytes = response.read()
                return body
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            if attempt == 2:
                return None
            time.sleep(1)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument(
        "--expected",
        type=Path,
        default=None,
        help="compare against this local file instead of fetching (test seam)",
    )
    parser.add_argument("--gateway-mirror-url", default=GATEWAY_MIRROR_URL)
    args = parser.parse_args()

    from generate_index import generate

    fresh = generate(args.root.resolve())
    if args.expected is not None:
        served = args.expected.read_bytes()
    else:
        served = _fetch(args.gateway_mirror_url)
        if served is None:
            print(
                "mirror_drift: the gateway's website/plugins-index.json could not be "
                "fetched — a network failure is indistinguishable from a missing "
                "mirror, fail closed; run the documented sync from a maintainer "
                "checkout if the mirror is absent",
                file=sys.stderr,
            )
            return 1
    if fresh != served:
        print(
            "mirror_drift: the gateway's committed catalogue mirror differs from a "
            "fresh generation of this repository's records/ + releases/ (a records "
            "change landed without a sync, or the mirror was hand-edited) — run the "
            "documented sync from a maintainer checkout (README, 'Keeping the "
            "gateway catalogue in sync') and open the gateway PR; never hand-edit "
            "the mirror",
            file=sys.stderr,
        )
        return 1
    print(f"gateway catalogue mirror is current ({len(fresh)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
