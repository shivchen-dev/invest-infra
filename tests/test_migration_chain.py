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
        versions_directory = repository_root / "apps" / "migrations" / "migrations" / "versions"
        revision_files = sorted(versions_directory.glob("*.py"))

        self.assertGreaterEqual(
            len(revision_files),
            1,
            "expected at least one Alembic revision file in "
            f"{versions_directory}, found {revision_files}",
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
            down_revision for _, down_revision in revisions.values() if down_revision is not None
        }
        all_revision_ids = {revision for revision, _ in revisions.values()}
        head_ids = all_revision_ids - referenced_down_revisions

        self.assertEqual(
            len(head_ids),
            1,
            "expected exactly one current head across the migration chain, "
            f"found {len(head_ids)}: {sorted(head_ids)}",
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
            "expected exactly one revision file declaring revision='20260731_0001', "
            f"found {len(initial_files)}: {initial_files}",
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
                f"{initial_revision_file} upgrade() must call op.execute() with a "
                f"statement that creates the {schema!r} schema",
            )
        self.assertIn(
            "instruments",
            create_table_names,
            f"{initial_revision_file} upgrade() must call op.create_table() with an "
            "'instruments' table name",
        )
        self.assertIn(
            "provider_batches",
            create_table_names,
            f"{initial_revision_file} upgrade() must call op.create_table() with a "
            "'provider_batches' table name",
        )
        self.assertIn(
            "pipeline_runs",
            create_table_names,
            f"{initial_revision_file} upgrade() must call op.create_table() with a "
            "'pipeline_runs' table name",
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
            "sa.UniqueConstraint(\n"
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
        versions_directory = repository_root / "apps" / "migrations" / "migrations" / "versions"

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
            down_revision for _, down_revision in revisions.values() if down_revision is not None
        }
        head_ids = all_revision_ids - referenced_down_revisions
        self.assertEqual(
            head_ids,
            {"20260812_0017"},
            f"expected exactly one unreferenced chain head, got {sorted(head_ids)}",
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
        self.assertIn('name="fk_etf_profiles_instrument_id_core_instruments"', source)
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
        versions_directory = repository_root / "apps" / "migrations" / "migrations" / "versions"

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
            down_revision for _, down_revision in revisions.values() if down_revision is not None
        }
        head_ids = all_revision_ids - referenced_down_revisions
        self.assertEqual(
            head_ids,
            {"20260812_0017"},
            f"expected exactly one unreferenced chain head, got {sorted(head_ids)}",
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

    def test_research_context_packs_migration_is_current_head(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        versions_directory = repository_root / "apps" / "migrations" / "migrations" / "versions"
        revisions: dict[Path, tuple[str, object]] = {}
        for revision_file in sorted(versions_directory.glob("*.py")):
            tree = ast.parse(revision_file.read_text(encoding="utf-8"))
            assignments: dict[str, object] = {}
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    value = _try_literal_eval(node.value)
                    if value is not _NOT_LITERAL:
                        for target in node.targets:
                            if isinstance(target, ast.Name):
                                assignments[target.id] = value
                elif isinstance(node, ast.AnnAssign) and node.value is not None:
                    value = _try_literal_eval(node.value)
                    if value is not _NOT_LITERAL and isinstance(node.target, ast.Name):
                        assignments[node.target.id] = value
            revisions[revision_file] = (assignments["revision"], assignments["down_revision"])
        heads = {revision for revision, _ in revisions.values()} - {
            down_revision for _, down_revision in revisions.values() if down_revision is not None
        }
        self.assertEqual(heads, {"20260812_0017"})
        source = (versions_directory / "20260805_0010_research_context_packs.py").read_text()
        self.assertIn('revision: str = "20260805_0010"', source)
        self.assertIn('down_revision: str | None = "20260805_0009"', source)
        for table_name in ("research_context_packs", "research_context_items"):
            self.assertIn(f'"{table_name}"', source)
        for token in (
            "uq_research_context_packs_content_hash",
            "uq_research_context_items_pack_item_hash",
            "value_type IN ('text', 'decimal', 'date', 'json')",
            "JSONB",
            "missing_reason",
            "source_provider",
            "evidence_refs",
        ):
            self.assertIn(token, source)

    def test_dc3_exposure_migration_schema_contract(self) -> None:
        repository_root = Path(__file__).resolve().parents[1]
        versions_directory = repository_root / "apps" / "migrations" / "migrations" / "versions"
        source = (versions_directory / "20260806_0011_dc3_exposure.py").read_text()
        self.assertIn('revision: str = "20260806_0011"', source)
        self.assertIn('down_revision: str | None = "20260805_0010"', source)
        for table_name in (
            "indexes",
            "index_profiles",
            "index_constituent_snapshots",
            "index_constituents",
            "etf_index_mappings",
            "etf_holding_snapshots",
            "etf_holdings",
        ):
            self.assertIn(f'"{table_name}"', source)
        for token in (
            'name="fk_etf_holding_snapshots_etf_id_core_instruments"',
            'name="fk_etf_holdings_snapshot_id_core_etf_holding_snapshots"',
            'name="uq_etf_holding_snapshots_natural_key"',
            'name="uq_etf_holdings_snapshot_stock_code"',
            "length(content_hash) = 64",
            "weight >= 0 AND weight <= 1",
        ):
            self.assertIn(token, source)
        explicit_names = [
            node.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith(("fk_", "uq_", "ck_", "ix_", "pk_"))
        ]
        self.assertTrue(all(len(name) <= 63 for name in explicit_names))

    def test_research_cases_migration(self) -> None:
        source = (
            Path(__file__).resolve().parents[1]
            / "apps"
            / "migrations"
            / "migrations"
            / "versions"
            / "20260807_0012_research_cases.py"
        ).read_text(encoding="utf-8")
        self.assertIn('revision: str = "20260807_0012"', source)
        self.assertIn('down_revision: str | None = "20260806_0011"', source)
        self.assertIn('"research_cases"', source)
        self.assertIn('schema="analytics"', source)
        self.assertIn("btrim(question) <> ''", source)
        self.assertIn("btrim(horizon) <> ''", source)
        self.assertIn("ck_research_cases_terminal_iff_closed_at_set", source)
        for name in (
            "fk_research_cases_instrument_id_core_instruments",
            "fk_research_cases_cpool_run_id_analytics_cpool_runs",
            "ix_research_cases_instrument_as_of_date",
            "ix_research_cases_status",
        ):
            self.assertIn(name, source)

    def test_research_evidence_packs_case_fk_migration(self) -> None:
        """The 0013 migration wires ``research_evidence_packs.research_case_id``.

        Pins the ``20260807_0013`` contract via direct source
        assertions; the 0013 chain-head property is already pinned by
        the older ``*_is_current_head`` tests above.
        """
        source = (
            Path(__file__).resolve().parents[1]
            / "apps/migrations/migrations/versions/20260807_0013_research_evidence_packs_case_fk.py"
        ).read_text(encoding="utf-8")
        self.assertIn('revision: str = "20260807_0013"', source)
        self.assertIn('down_revision: str | None = "20260807_0012"', source)
        for token in (
            "research_case_id",
            "fk_research_evidence_packs_research_case_id_research_cases",
            "ix_research_evidence_packs_research_case_id",
            "uq_research_evidence_packs_content_hash",
            '"research_evidence_packs"',
            '"research_cases"',
            'source_schema="analytics"',
            'referent_schema="analytics"',
        ):
            self.assertIn(token, source)

    def test_research_runs_migration_is_current_head(self) -> None:
        """PR-5.5 Slice 1 introduces the ``research_runs`` / ``research_results`` schema.

        Pins the ``20260807_0014`` contract: the new migration chains
        on top of ``20260807_0013``, becomes the sole chain head, and
        defines both ``analytics.research_runs`` and
        ``analytics.research_results`` with the FK / check / uniqueness
        surface required by the persistence plan.
        """

        repository_root = Path(__file__).resolve().parents[1]
        versions_directory = repository_root / "apps" / "migrations" / "migrations" / "versions"

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
            down_revision for _, down_revision in revisions.values() if down_revision is not None
        }
        head_ids = all_revision_ids - referenced_down_revisions
        self.assertEqual(
            head_ids,
            {"20260812_0017"},
            f"expected exactly one unreferenced chain head, got {sorted(head_ids)}",
        )

        new_migration_file = (
            repository_root
            / "apps"
            / "migrations"
            / "migrations"
            / "versions"
            / "20260807_0014_research_runs.py"
        )
        self.assertTrue(
            new_migration_file.exists(),
            f"expected new migration file {new_migration_file} to exist",
        )
        source = new_migration_file.read_text(encoding="utf-8")

        self.assertIn('revision: str = "20260807_0014"', source)
        self.assertIn('down_revision: str | None = "20260807_0013"', source)

        for token in (
            '"research_runs"',
            '"research_results"',
            'schema="analytics"',
            'sa.PrimaryKeyConstraint("run_id"',
            'name="pk_research_runs"',
            'sa.PrimaryKeyConstraint("result_id"',
            'name="pk_research_results"',
        ):
            self.assertIn(token, source)

        for foreign_key_name in (
            "fk_research_runs_case_id_research_cases",
            "fk_research_runs_evidence_pack_id_research_evidence_packs",
            "fk_research_results_run_id_research_runs",
            "fk_research_results_evidence_pack_id_research_evidence_packs",
        ):
            self.assertIn(f'name="{foreign_key_name}"', source)

        for check_constraint_name in (
            "ck_research_runs_status_valid",
            "ck_research_runs_runner_key_nonempty",
            "ck_research_runs_playbook_key_nonempty",
            "ck_research_runs_attempt_positive",
            "ck_research_runs_external_request_id_nonempty",
            "ck_research_runs_external_session_id_nonempty",
            "ck_research_runs_finished_after_started",
            "ck_research_results_evidence_ids_nonempty",
            "ck_research_results_risks_array",
            "ck_research_results_evidence_ids_array",
        ):
            self.assertIn(check_constraint_name, source)

        for status_token in (
            "'queued'",
            "'running'",
            "'succeeded'",
            "'failed'",
            "'cancelled'",
        ):
            self.assertIn(status_token, source)
        self.assertIn("status IN (", source)
        self.assertIn(
            'name="ck_research_runs_status_valid"',
            source,
        )
        self.assertIn("attempt >= 1", source)
        self.assertIn(
            "started_at IS NULL OR finished_at IS NULL OR finished_at >= started_at",
            source,
        )
        self.assertIn("external_request_id", source)
        self.assertIn("external_session_id", source)

        self.assertIn(
            "uq_research_runs_external_session_id",
            source,
        )
        self.assertIn(
            "uq_research_results_run_id",
            source,
        )

        for index_name in (
            "ix_research_runs_status",
            "ix_research_runs_case_id",
            "ix_research_runs_external_request_id",
            "ix_research_results_run_id",
            "ix_research_results_evidence_pack_id",
        ):
            self.assertIn(index_name, source)

        self.assertIn("jsonb_typeof(risks) = 'array'", source)
        self.assertIn("jsonb_typeof(evidence_ids) = 'array'", source)
        self.assertIn("jsonb_array_length(evidence_ids) >= 1", source)

        explicit_names = [
            node.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith(("fk_", "uq_", "ck_", "ix_", "pk_"))
        ]
        self.assertTrue(all(len(name) <= 63 for name in explicit_names))

    def test_research_run_row_models_are_wired(self) -> None:
        """PR-5.5 Slice 1 ships :class:`ResearchRunRow` and :class:`ResearchResultRow`.

        Both rows must be importable from
        ``invest_storage.models`` / ``invest_storage``, set the right
        ``__tablename__``, declare the FK chain expected by the
        migration, and configure the unique constraints that
        guarantee ``(a)`` one immutable result per run and
        ``(b)`` external-session uniqueness.

        The model constraint / index names are matched by exact equality
        against the names explicitly written in
        ``20260807_0014_research_runs`` so a future regression in the
        ``Base`` naming-convention prefix logic (e.g. accidentally
        double-prefixing a ``CheckConstraint`` ``name=`` argument) is
        caught as a focused failure rather than a silent schema drift.
        Every new constraint / index name is also asserted to be at or
        under PostgreSQL's 63-character identifier limit so a runaway
        suffix cannot sneak past the test suite.
        """

        import sqlalchemy as sa  # noqa: F401 - import the package to ensure availability
        from invest_storage.models import (
            ResearchResultRow,
            ResearchRunRow,
        )

        self.assertEqual(ResearchRunRow.__tablename__, "research_runs")
        self.assertEqual(ResearchResultRow.__tablename__, "research_results")

        run_table = ResearchRunRow.__table__
        result_table = ResearchResultRow.__table__
        self.assertEqual(run_table.schema, "analytics")
        self.assertEqual(result_table.schema, "analytics")

        run_pk_columns = {column.name for column in run_table.primary_key.columns}
        result_pk_columns = {column.name for column in result_table.primary_key.columns}
        self.assertEqual(run_pk_columns, {"run_id"})
        self.assertEqual(result_pk_columns, {"result_id"})

        run_foreign_key_names = {
            constraint.name for constraint in run_table.foreign_key_constraints
        }
        result_foreign_key_names = {
            constraint.name for constraint in result_table.foreign_key_constraints
        }
        self.assertEqual(
            run_foreign_key_names,
            {
                "fk_research_runs_case_id_research_cases",
                "fk_research_runs_evidence_pack_id_research_evidence_packs",
                "fk_research_runs_evidence_bundle_id_research_evidence_bundles",
            },
        )
        self.assertEqual(
            result_foreign_key_names,
            {
                "fk_research_results_run_id_research_runs",
                "fk_research_results_evidence_pack_id_research_evidence_packs",
                "fk_research_results_evidence_bundle_id_bundles",
            },
        )

        run_check_names = {
            constraint.name
            for constraint in run_table.constraints
            if isinstance(constraint, sa.CheckConstraint)
        }
        result_check_names = {
            constraint.name
            for constraint in result_table.constraints
            if isinstance(constraint, sa.CheckConstraint)
        }
        self.assertEqual(
            run_check_names,
            {
                "ck_research_runs_status_valid",
                "ck_research_runs_runner_key_nonempty",
                "ck_research_runs_playbook_key_nonempty",
                "ck_research_runs_attempt_positive",
                "ck_research_runs_external_request_id_nonempty",
                "ck_research_runs_external_session_id_nonempty",
                "ck_research_runs_finished_after_started",
            },
        )
        self.assertEqual(
            result_check_names,
            {
                "ck_research_results_conclusion_nonblank",
                "ck_research_results_report_markdown_nonblank",
                "ck_research_results_model_key_nonblank",
                "ck_research_results_model_version_nonblank",
                "ck_research_results_playbook_version_nonblank",
                "ck_research_results_adapter_version_nonblank",
                "ck_research_results_risks_array",
                "ck_research_results_evidence_ids_array",
                "ck_research_results_evidence_ids_nonempty",
            },
        )

        run_unique_names = {
            constraint.name
            for constraint in run_table.constraints
            if isinstance(constraint, sa.UniqueConstraint)
        }
        result_unique_names = {
            constraint.name
            for constraint in result_table.constraints
            if isinstance(constraint, sa.UniqueConstraint)
        }
        self.assertEqual(run_unique_names, set())
        self.assertEqual(
            result_unique_names,
            {"uq_research_results_run_id"},
        )

        run_index_names = {index.name for index in run_table.indexes}
        result_index_names = {index.name for index in result_table.indexes}
        self.assertEqual(
            run_index_names,
            {
                "ix_research_runs_status",
                "ix_research_runs_case_id",
                "ix_research_runs_external_request_id",
                "ix_research_runs_evidence_bundle_id",
                "uq_research_runs_external_session_id",
            },
        )
        self.assertEqual(
            result_index_names,
            {
                "ix_research_results_run_id",
                "ix_research_results_evidence_pack_id",
                "ix_research_results_evidence_bundle_id",
            },
        )

        all_new_names: set[str] = (
            run_check_names
            | result_check_names
            | run_unique_names
            | result_unique_names
            | run_foreign_key_names
            | result_foreign_key_names
            | run_index_names
            | result_index_names
        )
        too_long = sorted(name for name in all_new_names if len(name) > 63)
        self.assertEqual(
            too_long,
            [],
            f"new constraint / index names exceed PostgreSQL's 63-character "
            f"identifier limit: {too_long}",
        )

        repository_root = Path(__file__).resolve().parents[1]
        migrations_dir = (
            repository_root / "apps" / "migrations" / "migrations" / "versions"
        )
        primary_migration = migrations_dir / "20260807_0014_research_runs.py"
        bundle_migration = migrations_dir / "20260811_0016_research_evidence_bundles.py"
        result_bundle_migration = (
            migrations_dir / "20260812_0017_research_result_evidence_bundle_fk.py"
        )
        migration_tree = ast.parse(
            primary_migration.read_text(encoding="utf-8"),
            filename=str(primary_migration),
        )
        bundle_tree = ast.parse(
            bundle_migration.read_text(encoding="utf-8"),
            filename=str(bundle_migration),
        )
        result_bundle_tree = ast.parse(
            result_bundle_migration.read_text(encoding="utf-8"),
            filename=str(result_bundle_migration),
        )

        new_table_prefixes = (
            "ck_research_runs_",
            "ck_research_results_",
            "ix_research_runs_",
            "ix_research_results_",
            "uq_research_runs_",
            "uq_research_results_",
            "fk_research_runs_",
            "fk_research_results_",
            "pk_research_runs",
            "pk_research_results",
        )

        def _matches_new_tables(name: str) -> bool:
            return name.startswith(new_table_prefixes)

        migration_explicit_names: set[str] = set()
        for tree in (migration_tree, bundle_tree, result_bundle_tree):
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.keyword)
                    and node.arg == "name"
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    value = node.value.value
                    if _matches_new_tables(value):
                        migration_explicit_names.add(value)
                elif (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "op"
                    and node.func.attr in {"create_index", "create_foreign_key"}
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                    and _matches_new_tables(node.args[0].value)
                ):
                    migration_explicit_names.add(node.args[0].value)

        self.assertEqual(
            all_new_names | {"pk_research_runs", "pk_research_results"},
            migration_explicit_names,
            "model metadata names must exactly match the constraint / index "
            "names explicitly written in migrations 20260807_0014 + 20260811_0016 + 20260812_0017; "
            f"model={sorted(all_new_names | {'pk_research_runs', 'pk_research_results'})}, "
            f"migration={sorted(migration_explicit_names)}",
        )

        from invest_storage import ResearchResultRow as ExportedResultRow
        from invest_storage import ResearchRunRow as ExportedRunRow

        self.assertIs(ExportedRunRow, ResearchRunRow)
        self.assertIs(ExportedResultRow, ResearchResultRow)

    def test_research_evidence_bundles_migration_is_current_head(self) -> None:
        """Stage 4B Phase 3 ships the ``research_evidence_bundles`` schema.

        Pins the ``20260811_0016`` contract: the new migration chains
        on top of the market observation head
        (``20260810_0015``), becomes the sole chain head, and adds:

        - ``analytics.research_evidence_bundles`` for the new bundle
          identity record;
        - a nullable ``evidence_bundle_id`` column on
          ``analytics.research_runs`` so the existing PR-7 ResearchRun
          row can be retrofitted to a bundle without invalidating
          legacy runs.
        """

        repository_root = Path(__file__).resolve().parents[1]
        versions_directory = (
            repository_root
            / "apps"
            / "migrations"
            / "migrations"
            / "versions"
        )

        revisions: dict[Path, tuple[str, object]] = {}
        for revision_file in sorted(versions_directory.glob("*.py")):
            source = revision_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
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
            {"20260812_0017"},
            f"expected exactly one unreferenced chain head, got {sorted(head_ids)}",
        )

        new_migration_file = (
            versions_directory / "20260811_0016_research_evidence_bundles.py"
        )
        self.assertTrue(
            new_migration_file.exists(),
            f"expected new migration file {new_migration_file} to exist",
        )
        source = new_migration_file.read_text(encoding="utf-8")

        self.assertIn('revision: str = "20260811_0016"', source)
        self.assertIn('down_revision: str | None = "20260810_0015"', source)

        for token in (
            '"research_evidence_bundles"',
            'schema="analytics"',
            'name="pk_research_evidence_bundles"',
            "uq_research_evidence_bundles_bundle_hash",
            "ck_research_evidence_bundles_bundle_hash_len64",
            "ck_research_evidence_bundles_evidence_pack_hash_len64",
            "ck_research_evidence_bundles_schema_version_nonempty",
            "ck_research_evidence_bundles_snapshot_ids_array",
            "ck_research_evidence_bundles_snapshot_hashes_array",
            "ck_research_evidence_bundles_snapshot_dates_array",
            "ck_research_evidence_bundles_snapshot_ids_hashes_same_length",
            "ck_research_evidence_bundles_snapshot_ids_dates_same_length",
            "ix_research_evidence_bundles_research_case_id",
            "ix_research_evidence_bundles_evidence_pack_id",
            "fk_research_evidence_bundles_research_case_id_research_cases",
            "fk_research_evidence_bundles_evidence_pack_id_",
            "research_packs",
            "evidence_bundle_id",
            "fk_research_runs_evidence_bundle_id_research_evidence_bundles",
            "ix_research_runs_evidence_bundle_id",
        ):
            self.assertIn(token, source)

        # The plan requires a changed market snapshot set for the same
        # ``(research_case_id, evidence_pack_id)`` pair to create a
        # new bundle identity so the audit history is preserved; the
        # table therefore carries NO ``(research_case_id,
        # evidence_pack_id)`` unique constraint. ``bundle_hash`` is
        # the only idempotency key, enforced by
        # ``uq_research_evidence_bundles_bundle_hash``.
        self.assertNotIn("uq_research_evidence_bundles_case_pack", source)

        # The new column is a NULLABLE backfill so legacy runs survive
        # the upgrade without a backfill migration.
        self.assertIn('"evidence_bundle_id"', source)
        self.assertIn("nullable=True", source)

        explicit_names = [
            node.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith(("fk_", "uq_", "ck_", "ix_", "pk_"))
        ]
        too_long = sorted(name for name in explicit_names if len(name) > 63)
        self.assertEqual(
            too_long,
            [],
            f"new constraint / index names exceed PostgreSQL's 63-character "
            f"identifier limit: {too_long}",
        )

    def test_research_evidence_bundle_row_models_are_wired(self) -> None:
        """Stage 4B Phase 3 ships :class:`ResearchEvidenceBundleRow`.

        The row must be importable from
        ``invest_storage.models`` / ``invest_storage``, set the right
        ``__tablename__``, declare the FK chain expected by the
        migration, and configure the unique / check / index surface
        that guarantees ``(a)`` ``bundle_hash`` is the only
        idempotency key (no ``(research_case_id, evidence_pack_id)``
        uniqueness — plan §4B Phase 3 requires a changed market
        snapshot set to create a new bundle identity and preserve
        history), and ``(b)`` the same-length invariant between
        ``market_snapshot_ids`` / ``market_snapshot_hashes`` /
        ``market_snapshot_dates``.
        """

        import sqlalchemy as sa  # noqa: F401 - import the package to ensure availability
        from invest_storage.models import (
            ResearchEvidenceBundleRow,
            ResearchRunRow,
        )

        self.assertEqual(ResearchEvidenceBundleRow.__tablename__, "research_evidence_bundles")

        bundle_table = ResearchEvidenceBundleRow.__table__
        run_table = ResearchRunRow.__table__
        self.assertEqual(bundle_table.schema, "analytics")

        bundle_pk_columns = {
            column.name for column in bundle_table.primary_key.columns
        }
        self.assertEqual(bundle_pk_columns, {"bundle_id"})

        bundle_foreign_key_names = {
            constraint.name for constraint in bundle_table.foreign_key_constraints
        }
        self.assertEqual(
            bundle_foreign_key_names,
            {
                "fk_research_evidence_bundles_research_case_id_research_cases",
                "fk_research_evidence_bundles_evidence_pack_id_research_packs",
            },
        )

        bundle_check_names = {
            constraint.name
            for constraint in bundle_table.constraints
            if isinstance(constraint, sa.CheckConstraint)
        }
        self.assertEqual(
            bundle_check_names,
            {
                "ck_research_evidence_bundles_bundle_hash_len64",
                "ck_research_evidence_bundles_evidence_pack_hash_len64",
                "ck_research_evidence_bundles_schema_version_nonempty",
                "ck_research_evidence_bundles_snapshot_ids_array",
                "ck_research_evidence_bundles_snapshot_hashes_array",
                "ck_research_evidence_bundles_snapshot_dates_array",
                "ck_research_evidence_bundles_snapshot_ids_hashes_same_length",
                "ck_research_evidence_bundles_snapshot_ids_dates_same_length",
            },
        )

        bundle_unique_names = {
            constraint.name
            for constraint in bundle_table.constraints
            if isinstance(constraint, sa.UniqueConstraint)
        }
        # ``bundle_hash`` is the only idempotency key — a changed
        # market snapshot set for the same ``(research_case_id,
        # evidence_pack_id)`` pair MUST create a new bundle identity
        # so the audit history is preserved.
        self.assertEqual(
            bundle_unique_names,
            {
                "uq_research_evidence_bundles_bundle_hash",
            },
        )
        self.assertNotIn("uq_research_evidence_bundles_case_pack", bundle_unique_names)

        bundle_index_names = {index.name for index in bundle_table.indexes}
        self.assertEqual(
            bundle_index_names,
            {
                "ix_research_evidence_bundles_research_case_id",
                "ix_research_evidence_bundles_evidence_pack_id",
            },
        )

        run_index_names = {index.name for index in run_table.indexes}
        self.assertIn("ix_research_runs_evidence_bundle_id", run_index_names)

        run_fk_names = {constraint.name for constraint in run_table.foreign_key_constraints}
        self.assertIn(
            "fk_research_runs_evidence_bundle_id_research_evidence_bundles",
            run_fk_names,
        )

        from invest_storage import ResearchEvidenceBundleRow as ExportedRow

        self.assertIs(ExportedRow, ResearchEvidenceBundleRow)

    def test_research_result_evidence_bundle_fk_migration_chains(self) -> None:
        """Stage 4B Phase 3 wires ``research_results.evidence_bundle_id``.

        The new migration ``20260812_0017`` must:

        - chain on top of the current head ``20260811_0016`` and
          become the sole chain head;
        - add a nullable ``evidence_bundle_id`` UUID column to
          ``analytics.research_results`` with a FK to
          ``analytics.research_evidence_bundles.bundle_id``;
        - create the supporting
          ``ix_research_results_evidence_bundle_id`` index;
        - keep the column nullable so legacy rows survive the upgrade
          unchanged;
        - expose a reversible ``downgrade()`` that drops the index and
          FK and removes the column.
        """

        repository_root = Path(__file__).resolve().parents[1]
        versions_directory = (
            repository_root
            / "apps"
            / "migrations"
            / "migrations"
            / "versions"
        )
        new_migration_file = (
            versions_directory
            / "20260812_0017_research_result_evidence_bundle_fk.py"
        )
        self.assertTrue(
            new_migration_file.exists(),
            f"expected new migration file {new_migration_file} to exist",
        )
        source = new_migration_file.read_text(encoding="utf-8")

        self.assertIn('revision: str = "20260812_0017"', source)
        self.assertIn('down_revision: str | None = "20260811_0016"', source)

        revisions: dict[Path, tuple[str, object]] = {}
        for revision_file in sorted(versions_directory.glob("*.py")):
            tree = ast.parse(revision_file.read_text(encoding="utf-8"))
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
            self.assertIn("revision", assignments)
            self.assertIn("down_revision", assignments)
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
            {"20260812_0017"},
            f"expected exactly one chain head pointing at 20260812_0017, got {sorted(head_ids)}",
        )

        for token in (
            '"research_results"',
            '"research_evidence_bundles"',
            '"evidence_bundle_id"',
            '"bundle_id"',
            "fk_research_results_evidence_bundle_id_bundles",
            "ix_research_results_evidence_bundle_id",
            "nullable=True",
        ):
            self.assertIn(
                token,
                source,
                f"20260812_0017 migration is missing required token: {token!r}",
            )

        self.assertIn("op.drop_index(", source)
        self.assertIn("op.drop_constraint(", source)
        self.assertIn("op.drop_column(", source)

        explicit_names = [
            node.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith(("fk_", "uq_", "ck_", "ix_", "pk_"))
        ]
        too_long = sorted(name for name in explicit_names if len(name) > 63)
        self.assertEqual(
            too_long,
            [],
            f"new constraint / index names exceed PostgreSQL's 63-character "
            f"identifier limit: {too_long}",
        )

        from invest_storage.models import ResearchResultRow

        result_table = ResearchResultRow.__table__
        result_fk_names = {
            constraint.name for constraint in result_table.foreign_key_constraints
        }
        self.assertIn(
            "fk_research_results_evidence_bundle_id_bundles",
            result_fk_names,
        )
        result_index_names = {index.name for index in result_table.indexes}
        self.assertIn("ix_research_results_evidence_bundle_id", result_index_names)
        result_column = result_table.c["evidence_bundle_id"]
        self.assertTrue(result_column.nullable)


def _first_string_literal(call_node: ast.Call) -> str | None:
    for argument in call_node.args:
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            return argument.value
    for keyword in call_node.keywords:
        if (
            keyword.arg in {"table_name", "name"}
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
        ):
            return keyword.value.value
    return None


if __name__ == "__main__":
    unittest.main()
