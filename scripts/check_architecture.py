from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RULES = {
    ROOT / "packages" / "domain" / "src": {
        "fastapi",
        "sqlalchemy",
        "dagster",
        "httpx",
        "requests",
        "akshare",
        "pandas",
        "polars",
        "vectorbt",
        "backtrader",
    },
    ROOT / "packages" / "storage" / "src": {
        "fastapi",
        "dagster",
        "akshare",
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
    ROOT / "apps" / "pipeline" / "src" / "invest_pipeline" / "adapters": {
        "sqlalchemy",
    },
    ROOT / "apps" / "pipeline" / "src" / "invest_pipeline" / "assets": {
        "subprocess",
    },
}

FORBIDDEN_PATTERNS = {
    "app_schema": {
        "pattern": "schema=\"app\"",
        "message": "New 'app' Schema is forbidden; use raw/core/analytics/ops",
    },
    "qfq_hfq": {
        "pattern": "qfq|hfq",
        "message": "qfq/hfq adjustment is forbidden in production paths",
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


def check_forbidden_patterns(path: Path) -> list[str]:
    violations: list[str] = []
    content = path.read_text(encoding="utf-8")
    for name, rule in FORBIDDEN_PATTERNS.items():
        if rule["pattern"] in content:
            violations.append(
                f"{path.relative_to(ROOT)}: {rule['message']} (found: {rule['pattern']})"
            )
    return violations


def check_providers_conflict() -> list[str]:
    """Check for providers.py / providers/ same-name conflict."""
    violations: list[str] = []
    pipeline_src = ROOT / "apps" / "pipeline" / "src" / "invest_pipeline"
    providers_py = pipeline_src / "providers.py"
    providers_dir = pipeline_src / "providers"
    if providers_py.exists() and providers_dir.exists():
        violations.append(
            f"providers.py and providers/ directory coexist in {pipeline_src.relative_to(ROOT)}"
        )
    return violations


def main() -> int:
    violations: list[str] = []

    # Check import rules
    for base, forbidden in RULES.items():
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            bad = imported_roots(path) & forbidden
            if bad:
                violations.append(f"{path.relative_to(ROOT)}: forbidden imports {sorted(bad)}")

    # Check forbidden patterns in all Python files
    script_path = Path(__file__).resolve()
    for path in ROOT.rglob("*.py"):
        if ".venv" in str(path) or "__pycache__" in str(path):
            continue
        if path.resolve() == script_path:
            continue
        violations.extend(check_forbidden_patterns(path))

    # Check providers conflict
    violations.extend(check_providers_conflict())

    if violations:
        print("Architecture violations:")
        for item in violations:
            print(f"- {item}")
        return 1

    print("Architecture boundaries OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
