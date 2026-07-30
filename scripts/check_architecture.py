from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RULES = {
    ROOT / "packages" / "domain" / "src": {
        "fastapi",
        "sqlalchemy",
        "dagster",
        "akshare",
        "pandas",
        "polars",
        "vectorbt",
        "backtrader",
    },
    ROOT / "apps" / "api" / "src": {
        "dagster",
        "akshare",
        "vectorbt",
        "backtrader",
        "jupyter",
    },
}


def imported_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def main() -> int:
    violations: list[str] = []
    for base, forbidden in RULES.items():
        for path in base.rglob("*.py"):
            bad = imported_roots(path) & forbidden
            if bad:
                violations.append(f"{path.relative_to(ROOT)}: forbidden imports {sorted(bad)}")

    if violations:
        print("Architecture violations:")
        for item in violations:
            print(f"- {item}")
        return 1

    print("Architecture boundaries OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
