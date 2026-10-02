"""The mirror-drift refusal (issue #224 slice 2, B2's registry half).

``scripts/check_mirror_drift.py`` regenerates the index in memory and
byte-compares it against the gateway repository's committed catalogue
mirror — the arm that catches a records change without a sync and a
coherent gateway-local hand-edit of mirror + panel together. CI runs the
fetch path on push to main only; these arms run offline (``--expected``)
and through an unreachable URL (``--gateway-mirror-url``) — no test
requires the network.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHECKER = REPO / "scripts" / "check_mirror_drift.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_committed_index_is_the_fresh_generation() -> None:
    """Green pin (offline): the committed index IS a fresh generation, so an
    in-sync gateway mirror passes."""
    result = _run("--expected", str(REPO / "index.json"))
    assert result.returncode == 0, result.stderr
    assert "mirror is current" in result.stdout


def test_stale_or_hand_edited_mirror_refuses(tmp_path: Path) -> None:
    """B2's registry arm: a gateway mirror that differs from a fresh
    generation — a records change without a sync, or a hand-edit — refuses
    mirror_drift:. The planted file is a sandbox copy."""
    planted = tmp_path / "plugins-index.json"
    document = json.loads((REPO / "index.json").read_text(encoding="utf-8"))
    document["rows"][0]["summary"] = "hand-edited on the gateway side"
    planted.write_text(
        json.dumps(document, sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )
    result = _run("--expected", str(planted))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "mirror_drift:" in result.stderr
    assert "never hand-edit" in result.stderr


def test_a_row_dropped_by_the_yank_arm_refuses_until_synced(tmp_path: Path) -> None:
    """The yank arm's cross-repo consequence: once a release is yanked the
    registry's fresh generation drops its row, so a gateway mirror still
    carrying it is drift — the honest red window until the sync lands."""
    stale = tmp_path / "plugins-index.json"
    shutil.copy2(REPO / "index.json", stale)
    result = _run("--expected", str(stale))
    assert result.returncode == 0, "precondition: the committed tree is in sync"
    root = tmp_path / "registry"
    root.mkdir()
    release = root / "releases" / "benchweave-registry" / "madeinoz67" / "dps150" / "0.1.0"
    release.mkdir(parents=True)
    dogfood = (
        REPO / "releases" / "benchweave-registry" / "madeinoz67" / "dps150" / "0.1.0"
    )
    shutil.copy2(dogfood / "manifest.json", release / "manifest.json")
    (release / "status.json").write_text(json.dumps({"lifecycle": "yanked"}), encoding="utf-8")
    result = _run("--root", str(root), "--expected", str(stale))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "mirror_drift:" in result.stderr


def test_fetch_failure_fails_closed() -> None:
    result = _run("--gateway-mirror-url", "http://127.0.0.1:1/plugins-index.json")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "mirror_drift:" in result.stderr
