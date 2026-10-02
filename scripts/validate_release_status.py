#!/usr/bin/env python3
"""Validate every releases/**/status.json against the release-status schema.

Issue #224 slice-2 pivot (design record §3.2, the lane-B-2 vacancy repair):
the lifecycle enum that governs a release's catalogue fate is enforced by
its OWN step — this walk — independent of ``generate_index.py``'s
regenerate-and-compare, so a wrongly-read authority cannot be
self-consistent by construction. Both this validator and the generator
read the same digest-pinned vendored copy
(``vendored/gateway/release-status.schema.json``, pinned against the
gateway's ``standards/registry/0.1.1`` origin by
``tests/test_validate_release_status.py``): one authority, two consumers.

A release tree with no ``status.json`` documents is green (today's
dogfood shape — disclosed in the output, not hidden): the step becomes
discriminating the moment the first status document lands, and the
planted-file arms in the test suite are the proof it discriminates.

Usage::

    python scripts/validate_release_status.py [--root REPO]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import jsonschema

REPO = Path(__file__).resolve().parents[1]
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "vendored" / "gateway" / (
    "release-status.schema.json"
)


def _validator() -> jsonschema.Draft202012Validator:
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"validate_release_status: status_schema_unreadable: {SCHEMA_PATH}: {exc}",
              file=sys.stderr)
        raise SystemExit(1) from exc
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO)
    args = parser.parse_args()
    root = args.root.resolve()
    validator = _validator()
    releases = root / "releases"
    documents = sorted(releases.rglob("status.json")) if releases.is_dir() else []
    if not documents:
        print("validate_release_status: no status documents under releases/ (green by vacuity)")
        return 0
    failures = 0
    for path in documents:
        rel = path.relative_to(root)
        try:
            document = json.loads(path.read_bytes())
        except ValueError as exc:
            print(f"validate_release_status: status_invalid: {rel}: unparseable JSON: {exc}")
            failures += 1
            continue
        errors = sorted(validator.iter_errors(document), key=str)
        for error in errors:
            print(
                f"validate_release_status: status_invalid: {rel}: "
                f"{error.json_path}: {error.message}"
            )
        failures += len(errors)
    if failures:
        print(
            f"validate_release_status: {failures} status document error(s) — "
            "status.json must validate against the pinned release-status schema "
            "(the lifecycle enum: published | deprecated | yanked | revoked)",
            file=sys.stderr,
        )
        return 1
    print(f"validate_release_status: {len(documents)} status document(s) valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
