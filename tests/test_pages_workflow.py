"""The Pages deploy workflow's order guards (fold R3/R9, 2026-10-02).

SHAPE-PIN, NOT AN EXECUTION PROOF: GitHub Actions workflows are not
executable in this repository's own CI, and these arms do not pretend
otherwise — they pin the YAML shapes that make two regressions structurally
absent, and anything that keeps these substrings while breaking semantics
elsewhere is caught by review, not here:

- R3a (critic F1): the deploy job runs ONLY on main — a workflow_dispatch
  on a branch reaches the validity job but must never ship a page;
- R3b (critic F2): a pre-deploy step refuses with the typed prefix
  ``deploy_superseded:`` when the run's GITHUB_SHA is no longer main's tip —
  re-running an old run must not ship a stale page over a newer deployment;
- R9 (critic F8): the Pages and id-token write permissions live on the
  deploy job alone; the validity job runs on the workflow-level
  ``contents: read`` and never needs more.
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "pages.yml"


def _workflow_parts() -> tuple[str, str]:
    """(the workflow-level head before jobs:, the deploy job's block)."""
    text = WORKFLOW.read_text(encoding="utf-8")
    head, sep, deploy = text.partition("\n  deploy:")
    assert sep, "the pages workflow lost its deploy job"
    return head.split("jobs:", 1)[0], deploy


def test_the_deploy_job_runs_only_on_main() -> None:
    _top, deploy = _workflow_parts()
    assert "if: github.ref == 'refs/heads/main'" in deploy, (
        "the deploy job lost its main-only guard (R3a: a dispatch on a "
        "branch must not ship a page)"
    )


def test_a_predeploy_step_refuses_a_superseded_sha() -> None:
    _top, deploy = _workflow_parts()
    assert "deploy_superseded:" in deploy, (
        "the deploy job lost its superseded-sha refusal prefix (R3b: the "
        "re-run of a stale run must not deploy)"
    )
    assert "git fetch origin main" in deploy, "the guard must fetch main's tip"
    assert "rev-parse origin/main" in deploy, "the guard must resolve main's tip"
    assert "GITHUB_SHA" in deploy, "the guard must compare against the run's own sha"


def test_pages_permissions_are_scoped_to_the_deploy_job() -> None:
    top, deploy = _workflow_parts()
    assert "pages: write" not in top, "the workflow-level grant carries pages: write (R9)"
    assert "id-token: write" not in top, (
        "the workflow-level grant carries id-token: write (R9)"
    )
    assert "permissions:" in deploy, "the deploy job lost its own permissions block"
    assert "contents: read" in deploy
    assert "pages: write" in deploy
    assert "id-token: write" in deploy
