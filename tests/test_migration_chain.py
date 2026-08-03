from __future__ import annotations

import ast
import unittest
from pathlib import Path


_NOT_LITERAL = object()


def _try_literal_eval(node: ast.AST) -> object:
    try:
        return ast.literal_eval(node)
    except (SyntaxError, TypeError, ValueError):
        return _NOT_LITERAL


class MigrationChainTest(unittest.TestCase):
    def test_initial_migration_chain(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        versions_directory = (
            repository_root / "apps" / "migrations" / "migrations" / "versions"
        )
        revision_files = sorted(versions_directory.glob("*.py"))

        self.assertGreaterEqual(
            len(revision_files),
            1,
            f"expected at least one Alembic revision file in {versions_directory}, found {revision_files}",
        )

        revisions: dict[Path, tuple[str, object]] = {}

        for revision_file in revision_files:
            source = revision_file.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(revision_file))

            assignments: dict[str, object] = {}
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    literal_value = _try_literal_eval(node.value)
                    if literal_value is _NOT_LITERAL:
                        continue
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            assignments[target.id] = literal_value
                elif (
                    isinstance(node, ast.AnnAssign)
                    and isinstance(node.target, ast.Name)
                    and node.value is not None
                ):
                    literal_value = _try_literal_eval(node.value)
                    if literal_value is not _NOT_LITERAL:
                        assignments[node.target.id] = literal_value

            self.assertIn(
                "revision",
                assignments,
                f"{revision_file} must define a module-level revision constant",
            )
            self.assertIn(
                "down_revision",
                assignments,
                f"{revision_file} must define a module-level down_revision constant",
            )
            revisions[revision_file] = (
                assignments["revision"],
                assignments["down_revision"],
            )

        referenced_down_revisions = {
            down_revision
            for _, down_revision in revisions.values()
            if down_revision is not None
        }
        all_revision_ids = {revision for revision, _ in revisions.values()}
        head_ids = all_revision_ids - referenced_down_revisions

        self.assertEqual(
            len(head_ids),
            1,
            f"expected exactly one current head across the migration chain, found {len(head_ids)}: {sorted(head_ids)}",
        )

        self.assertIn(
            "20260731_0001",
            all_revision_ids,
            "the initial revision '20260731_0001' must exist in the migration chain",
        )

        initial_files = [
            revision_file
            for revision_file, (revision, _) in revisions.items()
            if revision == "20260731_0001"
        ]
        self.assertEqual(
            len(initial_files),
            1,
            f"expected exactly one revision file declaring revision='20260731_0001', found {len(initial_files)}: {initial_files}",
        )
        initial_revision_file = initial_files[0]
        self.assertIsNone(
            revisions[initial_revision_file][1],
            f"{initial_revision_file} (revision '20260731_0001') must set down_revision to None",
        )

        initial_source = initial_revision_file.read_text(encoding="utf-8")
        initial_tree = ast.parse(initial_source, filename=str(initial_revision_file))
        upgrade_functions = [
            node
            for node in initial_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "upgrade"
        ]
        self.assertEqual(
            len(upgrade_functions),
            1,
            f"{initial_revision_file} must define exactly one upgrade function",
        )
        upgrade_function = upgrade_functions[0]

        execute_sql_statements: list[str] = []
        create_table_names: list[str] = []
        for child in ast.walk(upgrade_function):
            if (
                not isinstance(child, ast.Call)
                or not isinstance(child.func, ast.Attribute)
                or not isinstance(child.func.value, ast.Name)
            ):
                continue
            call_target = f"{child.func.value.id}.{child.func.attr}"
            if call_target == "op.execute":
                sql_literal = _first_string_literal(child)
                if sql_literal is not None:
                    execute_sql_statements.append(sql_literal.upper())
            elif call_target == "op.create_table":
                table_literal = _first_string_literal(child)
                if table_literal is not None:
                    create_table_names.append(table_literal)

        for schema in ("raw", "core", "analytics", "ops"):
            self.assertTrue(
                any(
                    "CREATE SCHEMA" in sql and schema.upper() in sql
                    for sql in execute_sql_statements
                ),
                f"{initial_revision_file} upgrade() must call op.execute() with a statement that creates the {schema!r} schema",
            )
        self.assertIn(
            "instruments",
            create_table_names,
            f"{initial_revision_file} upgrade() must call op.create_table() with an 'instruments' table name",
        )
        self.assertIn(
            "provider_batches",
            create_table_names,
            f"{initial_revision_file} upgrade() must call op.create_table() with a 'provider_batches' table name",
        )
        self.assertIn(
            "pipeline_runs",
            create_table_names,
            f"{initial_revision_file} upgrade() must call op.create_table() with a 'pipeline_runs' table name",
        )

    def test_candidate_pool_snapshot_fk_migration(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        migration_file = (
            repository_root
            / "apps"
            / "migrations"
            / "migrations"
            / "versions"
            / "20260731_0006_candidate_pool_snapshot_fk.py"
        )
        source = migration_file.read_text(encoding="utf-8")
        self.assertIn('revision: str = "20260731_0006"', source)
        self.assertIn('down_revision: str | None = "20260731_0005"', source)
        self.assertIn(
            "fk_cpool_runs_snapshot_id",
            source,
        )
        self.assertIn('"candidate_pool_runs"', source)
        self.assertIn('"input_snapshots"', source)


def _first_string_literal(call_node: ast.Call) -> str | None:
    for argument in call_node.args:
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            return argument.value
    for keyword in call_node.keywords:
        if keyword.arg in {"table_name", "name"} and isinstance(
            keyword.value, ast.Constant
        ) and isinstance(keyword.value.value, str):
            return keyword.value.value
    return None


if __name__ == "__main__":
    unittest.main()
