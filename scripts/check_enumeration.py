"""A2 three-way enumeration equality: docs == tool == schema.

The publishing docs' artefact list, the SDK packaging tool's
REQUIRED_COMPONENTS, and the records schema's review.components enum must
enumerate the same ten components (design section 4 slice 1, acceptance A2).
Any drift direction refuses: docs naming what the tool ignores, the tool
demanding what the schema does not confirm, or the schema admitting a
component neither surface carries.

    uv run python scripts/check_enumeration.py \
        --docs <gateway>/docs/publishing-guide.md \
        --sdk-module <gateway>/packages/sdk/src/benchweave_sdk/publishing.py
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def docs_block(docs_path: Path) -> list[str]:
    """The artefact list between ```text fences under 'Required artefacts'."""
    text = docs_path.read_text(encoding="utf-8")
    match = re.search(r"## Required artefacts.*?```text\n(.*?)```", text, re.DOTALL)
    if match is None:
        raise SystemExit(f"check_enumeration: no artefact block in {docs_path}")
    return sorted(line.strip() for line in match.group(1).splitlines() if line.strip())


def tool_components(module_path: Path) -> list[str]:
    """REQUIRED_COMPONENTS from the SDK publishing module, by AST (no import)."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        assignments: list[tuple[ast.expr, ast.expr | None]] = []
        if isinstance(node, ast.Assign):
            assignments = [(target, node.value) for target in node.targets]
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            assignments = [(node.target, node.value)]
        for target, value in assignments:
            if (
                isinstance(target, ast.Name)
                and target.id == "REQUIRED_COMPONENTS"
                and isinstance(value, (ast.Tuple, ast.List))
            ):
                return sorted(
                    element.value
                    for element in value.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                )
    raise SystemExit(f"check_enumeration: REQUIRED_COMPONENTS not found in {module_path}")


def schema_components(schema_path: Path) -> list[str]:
    schema = json.loads(schema_path.read_bytes())
    items = schema["properties"]["review"]["properties"]["components"]["items"]
    return sorted(items["enum"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs", type=Path, required=True)
    parser.add_argument("--sdk-module", type=Path, required=True)
    parser.add_argument(
        "--schema", type=Path, default=REPO / "records" / "records.schema.json"
    )
    args = parser.parse_args()
    docs = docs_block(args.docs)
    tool = tool_components(args.sdk_module)
    schema = schema_components(args.schema)
    ok = True
    if docs != tool:
        print(
            f"check_enumeration: docs != tool: docs-only={set(docs) - set(tool)} "
            f"tool-only={set(tool) - set(docs)}",
            file=sys.stderr,
        )
        ok = False
    if tool != schema:
        print(
            f"check_enumeration: tool != schema: tool-only={set(tool) - set(schema)} "
            f"schema-only={set(schema) - set(tool)}",
            file=sys.stderr,
        )
        ok = False
    if not ok:
        return 1
    print(f"check_enumeration: {len(docs)} components equal across docs, tool and schema")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
