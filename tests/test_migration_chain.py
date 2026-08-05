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

    def test_research_evidence_packs_migration(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        migration_file = (
            repository_root
            / "apps"
            / "migrations"
            / "migrations"
            / "versions"
            / "20260803_0007_research_evidence_packs.py"
        )
        source = migration_file.read_text(encoding="utf-8")

        self.assertIn('revision: str = "20260803_0007"', source)
        self.assertIn('down_revision: str | None = "20260731_0006"', source)
        self.assertIn('"research_evidence_packs"', source)
        self.assertIn("jsonb_typeof(payload) = 'object'", source)
        self.assertIn("ck_research_evidence_packs_payload_object", source)
        self.assertIn("length(content_hash) = 64", source)
        self.assertIn("ck_research_evidence_packs_content_hash_len64", source)
        self.assertIn(
            'sa.UniqueConstraint(\n'
            '            "instrument_id",\n'
            '            "as_of_date",\n'
            '            "schema_version",\n'
            '            "factor_set_version",\n'
            '            "content_hash",\n'
            '            name="uq_research_evidence_packs_natural_key",\n'
            "        )",
            source,
        )
        for foreign_key_name in (
            "fk_research_packs_instrument",
            "fk_research_packs_snapshot",
            "fk_research_packs_candidate_run",
        ):
            self.assertIn(f'name="{foreign_key_name}"', source)
        for foreign_key_target in (
            "core.instruments.id",
            "analytics.input_snapshots.id",
            "analytics.candidate_pool_runs.id",
        ):
            self.assertIn(f'"{foreign_key_target}"', source)

    def test_etf_profiles_migration_is_current_head(self) -> None:
        """The DC-2 ETF profile migration must be the new chain head.

        Pins the contract that ``20260804_0008_etf_profiles`` chains
        on top of ``20260803_0007_research_evidence_packs`` and is the
        sole current head across all revisions. The migration-chain
        uniqueness test below covers the same property generically, but
        this explicit test pins the specific revision id so a future
        branch merge that introduces an unexpected head surfaces as a
        focused failure rather than a generic chain-shape complaint.

        After ``PR-ETF-PROFILE-04`` the chain head is the
        ``etf_profile_fields`` migration; the ``etf_profiles`` revision
        is now an intermediate revision referenced by the new head.
        The structural assertions on the ETF profile migration remain
        unchanged so a regression in the underlying schema is still
        caught.
        """

        repository_root = Path(__file__).resolve().parents[1]
        versions_directory = (
            repository_root / "apps" / "migrations" / "migrations" / "versions"
        )

        revisions: dict[Path, tuple[str, object]] = {}
        for revision_file in sorted(versions_directory.glob("*.py")):
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
            self.assertIn("revision", assignments, f"{revision_file}")
            self.assertIn("down_revision", assignments, f"{revision_file}")
            revisions[revision_file] = (
                assignments["revision"],
                assignments["down_revision"],
            )

        # The chain head is the single revision id that nobody else
        # declares as their ``down_revision`` (mirrors the calculation
        # in ``test_initial_migration_chain``). The initial migration
        # ``20260731_0001`` also carries ``down_revision=None`` but it
        # MUST be referenced by the next revision so it is not a head.
        all_revision_ids = {revision for revision, _ in revisions.values()}
        referenced_down_revisions = {
            down_revision
            for _, down_revision in revisions.values()
            if down_revision is not None
        }
        head_ids = all_revision_ids - referenced_down_revisions
        self.assertEqual(
            head_ids,
            {"20260805_0009"},
            "expected exactly one unreferenced chain head, "
            f"got {sorted(head_ids)}",
        )

        new_migration_file = (
            repository_root
            / "apps"
            / "migrations"
            / "migrations"
            / "versions"
            / "20260804_0008_etf_profiles.py"
        )
        source = new_migration_file.read_text(encoding="utf-8")

        # Revision pinning: the migration declares its identity and
        # chains exactly on top of the existing PR-4A research evidence
        # packs head.
        self.assertIn('revision: str = "20260804_0008"', source)
        self.assertIn('down_revision: str | None = "20260803_0007"', source)

        # Schema-level pins: the table lives in ``core``, the natural
        # key is the 1-1 ``instrument_id`` foreign key to
        # ``core.instruments.id``.
        self.assertIn('"etf_profiles"', source)
        self.assertIn('schema="core"', source)
        self.assertIn('"core.instruments.id"', source)
        self.assertIn(
            'name="fk_etf_profiles_instrument_id_core_instruments"', source
        )
        self.assertIn('sa.PrimaryKeyConstraint("instrument_id"', source)
        self.assertIn('name="pk_etf_profiles"', source)

        # Defensive CHECK constraints mirror the domain contract so a
        # buggy application-service path cannot smuggle an
        # out-of-contract value past the validator.
        for check_constraint_name in (
            "ck_etf_profiles_manager_nonempty",
            "ck_etf_profiles_benchmark_index_nonempty",
            "ck_etf_profiles_category_nonempty",
            "ck_etf_profiles_fund_type_nonempty",
            "ck_etf_profiles_management_fee_range",
            "ck_etf_profiles_custody_fee_range",
            "ck_etf_profiles_aum_positive",
            "ck_etf_profiles_shares_positive",
        ):
            self.assertIn(check_constraint_name, source)

        # The dashboard-filter indexes must be present in the upgrade
        # path; the downgrade path must drop them before the table so
        # ``downgrade()`` is reversible on a clean database.
        for index_name in (
            "ix_etf_profiles_manager",
            "ix_etf_profiles_category",
            "ix_etf_profiles_fund_type",
        ):
            self.assertIn(index_name, source)

    def test_etf_profile_fields_migration_is_current_head(self) -> None:
        """The PR-ETF-PROFILE-04 migration must be the new chain head.

        Pins the contract that ``20260805_0009_etf_profile_fields``
        chains on top of ``20260804_0008_etf_profiles`` and is the
        sole current head across all revisions. The migration-chain
        uniqueness test below covers the same property generically, but
        this explicit test pins the specific revision id so a future
        branch merge that introduces an unexpected head surfaces as a
        focused failure rather than a generic chain-shape complaint.
        """

        repository_root = Path(__file__).resolve().parents[1]
        versions_directory = (
            repository_root / "apps" / "migrations" / "migrations" / "versions"
        )

        revisions: dict[Path, tuple[str, object]] = {}
        for revision_file in sorted(versions_directory.glob("*.py")):
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
            self.assertIn("revision", assignments, f"{revision_file}")
            self.assertIn("down_revision", assignments, f"{revision_file}")
            revisions[revision_file] = (
                assignments["revision"],
                assignments["down_revision"],
            )

        all_revision_ids = {revision for revision, _ in revisions.values()}
        referenced_down_revisions = {
            down_revision
            for _, down_revision in revisions.values()
            if down_revision is not None
        }
        head_ids = all_revision_ids - referenced_down_revisions
        self.assertEqual(
            head_ids,
            {"20260805_0009"},
            "expected exactly one unreferenced chain head, "
            f"got {sorted(head_ids)}",
        )

        new_migration_file = (
            repository_root
            / "apps"
            / "migrations"
            / "migrations"
            / "versions"
            / "20260805_0009_etf_profile_fields.py"
        )
        source = new_migration_file.read_text(encoding="utf-8")

        # Revision pinning: the new migration declares its identity and
        # chains exactly on top of the Stage DC-2 ETF profile head.
        self.assertIn('revision: str = "20260805_0009"', source)
        self.assertIn('down_revision: str | None = "20260804_0008"', source)

        # Schema-level pins: the table lives in ``analytics`` and the
        # value column is type-discriminated via three nullable columns
        # (``field_value_text`` / ``field_value_numeric`` /
        # ``field_value_date``).
        self.assertIn('"etf_profile_fields"', source)
        self.assertIn('schema="analytics"', source)
        self.assertIn(
            'name="fk_etf_profile_fields_instrument_id_core_instruments"',
            source,
        )
        self.assertIn('"core.instruments.id"', source)
        self.assertIn('sa.PrimaryKeyConstraint("id"', source)
        self.assertIn('name="pk_etf_profile_fields"', source)

        # Unique idempotency guard on the deterministic content hash.
        self.assertIn(
            'name="uq_etf_profile_fields_content_hash"',
            source,
        )
        self.assertIn('"content_hash"', source)
        self.assertIn("length(content_hash) = 64", source)
        self.assertIn(
            "ck_etf_profile_fields_content_hash_len64",
            source,
        )

        # Defensive CHECK constraints mirror the domain contract.
        for check_constraint_name in (
            "ck_etf_profile_fields_value_type_valid",
            "ck_etf_profile_fields_field_key_nonempty",
            "ck_etf_profile_fields_source_provider_nonempty",
            "ck_etf_profile_fields_source_dataset_nonempty",
            "ck_etf_profile_fields_source_revision_positive",
            "ck_etf_profile_fields_confidence_score_range",
            "ck_etf_profile_fields_value_columns_match",
        ):
            self.assertIn(check_constraint_name, source)

        # The read-path indexes must be present in the upgrade path;
        # the downgrade path must drop them before the table so
        # ``downgrade()`` is reversible on a clean database.
        for index_name in (
            "ix_etf_profile_fields_instrument_id",
            "ix_etf_profile_fields_instrument_field_key",
            "ix_etf_profile_fields_field_key",
            "ix_etf_profile_fields_source_provider",
        ):
            self.assertIn(index_name, source)


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
