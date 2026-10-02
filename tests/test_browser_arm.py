"""The deploy-gate browser arm as a battery test (the #224 follow-on fold).

``scripts/verify_catalogue_browser.py`` runs in the Pages workflow against
the real generated artifact (1 default row today). Its fold sequences —
F1 (the drill survives its own pushed URL), F2 (sentinel round-trip + the
clean reset URL) and F8 (cloned rows stack) — need a MULTI-row index to
fire in full, so this arm builds a synthetic site (fresh ed25519 keys; two
signed default rows plus an unsigned 2-evidence capability-bearing row)
and runs the SAME script against it, provisioning playwright exactly the
way the workflow does (``uv run --with playwright`` — a CI-transient dep,
never a project dependency).

Marked ``browser``: the fast validity lane runs ``-m "not browser"``; the
workflow's browser job provisions chromium and runs this arm.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_catalogue_record import SHA, _run, _write_release

REPO = Path(__file__).resolve().parents[1]
BROWSER_SCRIPT = REPO / "scripts" / "verify_catalogue_browser.py"


def _browser_site(root: Path, private: Ed25519PrivateKey) -> None:
    """A synthetic multi-row site: two SIGNED default rows (the second-row
    drill, F1b) and one UNSIGNED row carrying two evidence entries and a
    full capability declaration (the cloned-stack arms, F8)."""
    pem = private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    publishers = {
        "publishers_version": 1,
        "publishers": [
            {
                "publisher_id": "quarrystone-labs",
                "github": "quarrystone-labs",
                "namespace": "quarrystone-labs",
                "ed25519_public_key_pem": pem,
                "vetted_at": "2026-10-01T00:00:00Z",
                "key_validity": {
                    "not_before": "2026-01-01T00:00:00Z",
                    "not_after": "2030-01-01T00:00:00Z",
                },
            }
        ],
    }
    (root / "records").mkdir(parents=True)
    (root / "records" / "publishers.json").write_text(
        json.dumps(publishers, sort_keys=True, separators=(",", ":"))
    )
    _write_release(
        root, publisher="quarrystone-labs", plugin="alpha-meter", version="1.0.0",
        private_key=private,
    )
    _write_release(
        root, publisher="quarrystone-labs", plugin="gamma-sensor", version="2.0.0",
        private_key=private,
    )
    _write_release(
        root, publisher="quarrystone-labs", plugin="beta-probe", version="0.3.0",
        private_key=None,
        evidence=[
            {"level": "hardware", "report_path": "evidence/hw.md", "result": "passed"},
            {"level": "simulated", "report_path": "evidence/sim.md", "result": "partial"},
        ],
    )
    # the unsigned row's capability declaration rides a review record (the
    # index generator's join); a minimal record is enough — the records
    # tree of a synthetic page-generation site never runs the validity gate
    review_dir = root / "records" / "submissions" / "quarrystone-labs" / "beta-probe" / "0.3.0"
    review_dir.mkdir(parents=True)
    (review_dir / "review-1.json").write_text(
        json.dumps(
            {
                "record_type": "review",
                "kind": "admitted-release",
                "review": {
                    "publisher": "quarrystone-labs",
                    "plugin": "beta-probe",
                    "version": "0.3.0",
                    "capability_declaration": {
                        "network_egress": True,
                        "subprocess_or_native_library": True,
                        "filesystem_writes_beyond_evidence_retention": True,
                    },
                },
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )


@pytest.mark.browser
def test_the_browser_arm_passes_on_a_multi_row_site(tmp_path: Path) -> None:
    """The deploy gate's own script, end to end, on a site whose index makes
    every fold sequence fire: 2 default rows (F1b's second-row drill), an
    unsigned row (the reveal), a 2-evidence caps row (F8's stacks), the full
    sentinel round-trip (F2) and the reopen drill (F1a)."""
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copytree(REPO / "catalogue", root / "catalogue")
    shutil.copytree(REPO / "vendored", root / "vendored")
    private = Ed25519PrivateKey.generate()
    _browser_site(root, private)
    index = _run([sys.executable, str(REPO / "scripts" / "generate_index.py"),
                  "--root", str(root)])
    assert index.returncode == 0, index.stderr
    dest = tmp_path / "site"
    generated = _run(
        [sys.executable, str(REPO / "scripts" / "generate_catalogue_page.py"),
         "--root", str(root), "--dest", str(dest), "--sha", SHA]
    )
    assert generated.returncode == 0, generated.stderr
    rows: list[dict[str, Any]] = json.loads((dest / "index.json").read_text())["rows"]
    assert len([row for row in rows if row["signature_state"] == "signed-valid"]) == 2, (
        "precondition: the synthetic site must carry two default rows"
    )
    uv = shutil.which("uv")
    assert uv is not None, "uv is required to provision playwright for the browser arm"
    result = subprocess.run(
        [uv, "run", "--with", "playwright", "python", str(BROWSER_SCRIPT),
         "--dest", str(dest)],
        capture_output=True, text=True, check=False, cwd=REPO,
        env={**os.environ, "UV_PROJECT_ENVIRONMENT": "venv"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK browser arm" in result.stdout, result.stdout + result.stderr
