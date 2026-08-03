"""Export the FastAPI OpenAPI schema to ``apps/api/openapi.json``.

PR-02 wires the API contract into the Web workbench so the TypeScript
fetchers stop hand-mirroring Pydantic response shapes. The exporter
imports the real FastAPI ``app`` from :mod:`invest_api.main` (no
HTTP round trip, no separate process) and serialises the result with a
deterministic, diff-friendly layout:

* keys are sorted alphabetically so unrelated re-orderings do not show
  up in code review;
* indentation is two spaces, ASCII only, with ``ensure_ascii=False`` so
  CJK / accented characters stay readable in PR diffs;
* the file always ends with a single trailing newline so editors and
  linters stay quiet.

The script is intentionally importable as a module *and* runnable as a
CLI so the same code path backs ``make openapi-export`` (invoked from
the repository root) and the ``openapi-export`` script declared in
``apps/api/pyproject.toml`` (invoked from inside ``apps/api``).

Output location is always resolved relative to this file so the script
behaves identically regardless of the working directory used to launch
it. A ``--check`` mode is also exposed: it re-derives the spec and
returns a non-zero exit code when the on-disk file is out of date,
which is what the upcoming CI gate will lean on.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUTPUT = REPO_ROOT / "apps" / "api" / "openapi.json"


def _build_spec() -> Mapping[str, Any]:
    from invest_api.main import app

    return app.openapi()


def render_spec(spec: Mapping[str, Any]) -> str:
    """Serialise the OpenAPI spec deterministically with a trailing newline."""

    body = json.dumps(
        spec,
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ": "),
    )
    return body + "\n"


def write_spec(output_path: Path, spec: Mapping[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_spec(spec), encoding="utf-8")


def spec_matches_disk(output_path: Path, spec: Mapping[str, Any]) -> bool:
    if not output_path.exists():
        return False
    return output_path.read_text(encoding="utf-8") == render_spec(spec)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=(
            "Where to write the generated OpenAPI document. "
            "Defaults to apps/api/openapi.json relative to the repo root."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Exit with a non-zero status when the on-disk spec is out of "
            "date instead of rewriting it. Useful for CI gates."
        ),
    )
    args = parser.parse_args(argv)

    spec = _build_spec()

    if args.check:
        if spec_matches_disk(args.output, spec):
            return 0
        sys.stderr.write(
            f"OpenAPI spec at {args.output} is out of date; "
            "regenerate with `make openapi-export`.\n"
        )
        return 1

    write_spec(args.output, spec)
    sys.stdout.write(f"Wrote {args.output}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
