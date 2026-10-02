"""The htmx vendor (issue #224 follow-on design record §2.5).

The catalogue's only enhancement library is vendored and digest-pinned —
no CDN, no runtime fetch: ``vendored/htmx/htmx.min.js`` is byte-identical to
the pinned upstream artifact and ``vendored/htmx/htmx.pin.json`` records the
exact source URL, version, sha256 and license. The page serves it same-origin
from ``assets/htmx.min.js`` (the generator copies it at deploy time; B-S).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HTMX = REPO / "vendored" / "htmx" / "htmx.min.js"
PIN = REPO / "vendored" / "htmx" / "htmx.pin.json"

#: The single upstream artifact this vendor was fetched from (2026-10-02).
SOURCE = "https://unpkg.com/htmx.org@2.0.11/dist/htmx.min.js"
VERSION = "2.0.11"
SHA256 = "d6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717"
SIZE = 52182


def test_the_vendored_htmx_bytes_match_the_pin() -> None:
    raw = HTMX.read_bytes()
    assert len(raw) == SIZE, f"the vendored htmx is {len(raw)} bytes, pinned {SIZE}"
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == SHA256, (
        f"the vendored htmx drifted from its pin (on-disk {digest}, pinned "
        f"{SHA256}) — re-vendor deliberately or restore"
    )


def test_the_pin_records_source_version_and_license() -> None:
    pin = json.loads(PIN.read_text(encoding="utf-8"))
    assert pin["source"] == SOURCE, pin["source"]
    assert pin["version"] == VERSION, pin["version"]
    assert pin["sha256"] == SHA256, pin["sha256"]
    license_text = pin["license"]
    assert "Zero-Clause BSD" in license_text, (
        "the license text must be the artifact's own (htmx 2.0.11 ships 0BSD; "
        "the design record's 'BSD-2-Clause' label predates verification — the "
        "fetched package's LICENSE file is the authority)"
    )
    assert "Permission to use, copy, modify, and/or distribute this software" in license_text
