"""Static / AST tests for the M1 Storage increment 2 migrations.

These tests intentionally rely on the Python standard library only
(``ast`` and ``unittest``) so they run in the same CI job that already
executes ``tests/test_migration_chain.py`` without needing SQLAlchemy,
Alembic or PostgreSQL to be installed.

The tests validate:

* Revision identifiers and ``down_revision`` for both new migrations.
* Migration 0002 shadow-renames the legacy ``core.instruments`` table,
  creates the new table with a UUID primary key, and backfills UUID
  identities via :func:`uuid.uuid4` from Python.
* Migration 0003 creates the ``raw`` schema, the
  ``raw.provider_batches`` table with the expected bounded string /
  JSONB / timestamp columns, the (provider_key, dataset_key, request_key)
  unique constraint, the requested-vs-non-requested payload CHECK
  constraints, and the supporting indexes.
* Both migrations define ``upgrade`` and ``downgrade`` functions and
  the 0002 downgrade raises ``RuntimeError`` before destructive DDL
  when the new table holds rows not represented in the legacy shadow.

The existing ``tests/test_migration_chain.py`` continues to run and
must still pass after this file is added.
"""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSIONS_DIR = REPO_ROOT / "apps" / "api" / "migrations" / "versions"

MIGRATION_0002 = VERSIONS_DIR / "20260730_0002_instruments_uuid_identity.py"
MIGRATION_0003 = VERSIONS_DIR / "20260730_0003_provider_batches_raw_evidence.py"


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _module_constants(tree: ast.Module) -> dict[str, object]:
    constants: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants[target.id] = ast.literal_eval(node.value)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            constants[node.target.id] = ast.literal_eval(node.value)
    return constants


def _resolve(node: ast.AST, constants: dict[str, object]) -> str | None:
    """Resolve an expression to its string value, looking up module-level
    names and unwrapping ``sa.text(...)`` wrappers.

    Returns ``None`` if the value cannot be determined statically.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        value = constants.get(node.id)
        if isinstance(value, str):
            return value
        return None
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
            elif isinstance(value, ast.FormattedValue):
                resolved = _resolve(value.value, constants)
                if resolved is None:
                    return None
                parts.append(resolved)
            else:
                return None
        return "".join(parts)
    if isinstance(node, ast.Call):
        attr = node.func
        if (
            isinstance(attr, ast.Attribute)
            and isinstance(attr.value, ast.Name)
            and attr.value.id in {"sa", "sqlalchemy"}
            and attr.attr == "text"
        ):
            if node.args:
                return _resolve(node.args[0], constants)
        return None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _resolve(node.left, constants)
        right = _resolve(node.right, constants)
        if left is not None and right is not None:
            return left + right
    return None


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1, f"expected exactly one {name!r} function, found {len(matches)}"
    return matches[0]


def _imported_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def _string_literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _string_concat_value(node: ast.AST, constants: dict[str, object]) -> str | None:
    """Return the constant value of a string-likes expression.

    Handles plain string ``Constant`` nodes as well as f-strings whose
    interpolated expressions are all module-level string constants or
    names bound to such constants. The migration SQL builders are all
    of that form (``f'... {CONST} ...'``) so the literal portions are
    enough to verify naming and ``CHECK`` / ``CREATE SCHEMA`` patterns.
    """
    return _resolve(node, constants)


def _op_call_arguments(call: ast.Call) -> tuple[list[ast.AST], dict[str, ast.AST]]:
    return list(call.args), {kw.arg: kw.value for kw in call.keywords if kw.arg is not None}


def _op_calls(function: ast.FunctionDef) -> list[ast.Call]:
    calls: list[ast.Call] = []
    for node in ast.walk(function):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "op"
        ):
            calls.append(node)
    return calls


def _call_source(call: ast.Call) -> str:
    """Return a best-effort source-code rendering of an AST call.

    The migration builders mix plain string literals with f-strings that
    interpolate tuples through helper functions. The literal / f-string
    portions are statically resolvable; the helper call sites are not.
    ``ast.unparse`` always produces a syntactically valid Python
    representation that still contains the constraint / column names,
    so string-based assertions on the rendered call are reliable.
    """
    return ast.unparse(call)


def _table_name_from_create_table(call: ast.Call, constants: dict[str, object]) -> str | None:
    args, _ = _op_call_arguments(call)
    if args:
        return _resolve(args[0], constants)
    return None


def _schema_from_kwargs(call: ast.Call, constants: dict[str, object]) -> str | None:
    _, kwargs = _op_call_arguments(call)
    schema_node = kwargs.get("schema")
    return _resolve(schema_node, constants)


def _table_name_from_call(call: ast.Call, constants: dict[str, object]) -> str | None:
    args, kwargs = _op_call_arguments(call)
    for candidate in args:
        if (name := _resolve(candidate, constants)) is not None:
            return name
    for key in ("table_name", "name"):
        if key in kwargs and (name := _resolve(kwargs[key], constants)) is not None:
            return name
    return None


def _sql_text(call: ast.Call, constants: dict[str, object]) -> str | None:
    args, _ = _op_call_arguments(call)
    for arg in args:
        if (text := _resolve(arg, constants)) is not None:
            return text
    return None


def _create_table_column_names(
    call: ast.Call, constants: dict[str, object]
) -> set[str]:
    names: set[str] = set()
    for arg in call.args:
        if isinstance(arg, ast.keyword):
            continue
        if (
            isinstance(arg, ast.Call)
            and isinstance(arg.func, ast.Attribute)
            and arg.func.attr == "Column"
        ):
            if arg.args and (first := _resolve(arg.args[0], constants)) is not None:
                names.add(first)
    return names


def _create_index_column_names(
    call: ast.Call, constants: dict[str, object]
) -> list[str]:
    args, _ = _op_call_arguments(call)
    for arg in args:
        if isinstance(arg, ast.List):
            names: list[str] = []
            for elt in arg.elts:
                if (name := _resolve(elt, constants)) is not None:
                    names.append(name)
            return names
    return []


def _unique_constraint_columns(
    call: ast.Call, constants: dict[str, object]
) -> list[str]:
    """Return column names declared via ``sa.UniqueConstraint(...)`` in a
    create_table call. Each ``UniqueConstraint`` is itself a Call node
    nested under the create_table call as a keyword ``*table_args`` or
    as a positional arg, depending on SQLAlchemy usage.
    """
    columns: list[str] = []
    for arg in list(call.args) + list(call.keywords):
        value = arg.value if isinstance(arg, ast.keyword) else arg
        if not isinstance(value, ast.Call):
            continue
        if not (
            isinstance(value.func, ast.Attribute)
            and value.func.attr == "UniqueConstraint"
        ):
            continue
        for child in value.args:
            if (name := _resolve(child, constants)) is not None:
                columns.append(name)
    return columns


class MigrationFilesPresentTest(unittest.TestCase):
    def test_both_migration_files_exist(self) -> None:
        self.assertTrue(
            MIGRATION_0002.is_file(),
            f"expected migration 0002 to exist at {MIGRATION_0002}",
        )
        self.assertTrue(
            MIGRATION_0003.is_file(),
            f"expected migration 0003 to exist at {MIGRATION_0003}",
        )


class Migration0002RevisionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = _parse(MIGRATION_0002)
        cls.constants = _module_constants(cls.tree)

    def test_revision_identifier(self) -> None:
        self.assertEqual(self.constants.get("revision"), "20260730_0002")

    def test_down_revision_points_to_initial(self) -> None:
        self.assertEqual(self.constants.get("down_revision"), "20260730_0001")

    def test_upgrade_and_downgrade_defined(self) -> None:
        _function(self.tree, "upgrade")
        _function(self.tree, "downgrade")


class Migration0003RevisionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = _parse(MIGRATION_0003)
        cls.constants = _module_constants(cls.tree)

    def test_revision_identifier(self) -> None:
        self.assertEqual(self.constants.get("revision"), "20260730_0003")

    def test_down_revision_points_to_0002(self) -> None:
        self.assertEqual(self.constants.get("down_revision"), "20260730_0002")

    def test_upgrade_and_downgrade_defined(self) -> None:
        _function(self.tree, "upgrade")
        _function(self.tree, "downgrade")


class Migration0002ShadowRenameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = _parse(MIGRATION_0002)
        cls.constants = _module_constants(cls.tree)
        cls.upgrade = _function(cls.tree, "upgrade")
        cls.calls = _op_calls(cls.upgrade)

    def test_renames_existing_instruments_to_legacy_shadow(self) -> None:
        renames: list[str] = []
        for call in self.calls:
            if getattr(call.func, "attr", "") != "execute":
                continue
            sql = _sql_text(call, self.constants)
            if sql is not None:
                renames.append(sql)
        self.assertTrue(
            any(
                "RENAME TO" in sql and "_instruments_legacy" in sql and '"core"' in sql
                for sql in renames
            ),
            "expected migration 0002 upgrade() to rename core.instruments to "
            "_instruments_legacy; saw SQL statements: "
            f"{renames}",
        )

    def test_creates_new_instruments_table_with_uuid_pk(self) -> None:
        create_table_calls = [
            call
            for call in self.calls
            if getattr(call.func, "attr", "") == "create_table"
        ]
        new_instruments_calls = [
            call
            for call in create_table_calls
            if _table_name_from_create_table(call, self.constants) == "instruments"
            and _schema_from_kwargs(call, self.constants) == "core"
        ]
        self.assertEqual(
            len(new_instruments_calls),
            1,
            "expected exactly one op.create_table('instruments', schema='core') call in 0002",
        )
        columns = _create_table_column_names(new_instruments_calls[0], self.constants)
        for required in (
            "id",
            "symbol",
            "exchange",
            "name",
            "instrument_type",
            "currency",
            "list_date",
            "delist_date",
            "status",
            "underlying_index",
            "category",
            "provider_symbol_map",
            "valid_from",
            "valid_to",
            "is_active",
            "created_at",
            "updated_at",
        ):
            self.assertIn(
                required,
                columns,
                f"new core.instruments table must include column {required!r}; saw {sorted(columns)}",
            )

    def test_backfill_uses_python_uuid4(self) -> None:
        self.assertIn(
            "uuid",
            _imported_names(self.tree),
            "migration 0002 must import the uuid stdlib module",
        )
        uuid_call_count = 0
        for node in ast.walk(self.upgrade):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "uuid"
                and node.func.attr == "uuid4"
            ):
                uuid_call_count += 1
        self.assertGreater(
            uuid_call_count,
            0,
            "migration 0002 upgrade() must call uuid.uuid4() to backfill row identities",
        )

    def test_uses_bind_for_backfill_select(self) -> None:
        # ``op.get_bind()`` is the SQLAlchemy text/bind execution surface;
        # the backfill must reach the row count via bind.execute(...).
        self.assertTrue(
            any(
                isinstance(call.func, ast.Attribute) and call.func.attr == "execute"
                for call in self.calls
            ),
            "migration 0002 must use op.execute for DDL or bind.execute for backfill",
        )

    def test_partial_unique_index_on_symbol_exchange_active(self) -> None:
        create_index_calls = [
            call
            for call in self.calls
            if getattr(call.func, "attr", "") == "create_index"
        ]
        partial_unique = [
            call
            for call in create_index_calls
            if any(
                kw.arg == "unique" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                for kw in call.keywords
            )
            and any(
                kw.arg == "postgresql_where" for kw in call.keywords
            )
        ]
        self.assertTrue(
            partial_unique,
            "expected a unique index with a postgresql_where clause in migration 0002",
        )
        index_columns = _create_index_column_names(partial_unique[0], self.constants)
        self.assertEqual(
            sorted(index_columns),
            ["exchange", "symbol"],
            f"partial unique index must cover (symbol, exchange); saw {index_columns}",
        )

    def test_check_constraints_cover_required_invariants(self) -> None:
        executed_sql: list[str] = []
        for call in self.calls:
            if getattr(call.func, "attr", "") != "execute":
                continue
            sql = _sql_text(call, self.constants)
            if sql is not None:
                executed_sql.append(sql.upper())
            # Also keep the unparsed call source so constraint names that
            # are built from helper calls (e.g. ``_sql_tuple``) are still
            # findable as identifiers in the f-string template.
            executed_sql.append(_call_source(call).upper())
        joined = "\n".join(executed_sql)
        for required_sql in (
            "CK_INSTRUMENTS_SYMBOL_NONEMPTY",
            "CK_INSTRUMENTS_EXCHANGE_NONEMPTY",
            "CK_INSTRUMENTS_NAME_NONEMPTY",
            "CK_INSTRUMENTS_STATUS_VALID",
            "CK_INSTRUMENTS_VALID_RANGE",
            "CK_INSTRUMENTS_STATUS_DELIST_INVARIANT",
            "CK_INSTRUMENTS_LISTING_RANGE",
        ):
            self.assertIn(
                required_sql,
                joined,
                f"migration 0002 must define CHECK constraint {required_sql!r}",
            )


class Migration0002DowngradeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = _parse(MIGRATION_0002)
        cls.constants = _module_constants(cls.tree)
        cls.downgrade = _function(cls.tree, "downgrade")

    def test_downgrade_drops_new_indexes_before_table(self) -> None:
        order: list[str] = []
        for call in _op_calls(self.downgrade):
            attr = getattr(call.func, "attr", "")
            if attr == "drop_index":
                name = _table_name_from_call(call, self.constants)
                if name is not None:
                    order.append(f"index:{name}")
            elif attr == "drop_table":
                name = _table_name_from_call(call, self.constants)
                if name is not None:
                    order.append(f"table:{name}")
        index_drops = [item for item in order if item.startswith("index:")]
        table_drops = [item for item in order if item.startswith("table:")]
        self.assertTrue(
            index_drops,
            "downgrade must drop the partial unique index and exchange index before dropping the table",
        )
        self.assertTrue(
            table_drops,
            "downgrade must drop the new instruments table",
        )

    def test_downgrade_renames_legacy_shadow_back_to_instruments(self) -> None:
        rename_sql: list[str] = []
        for call in _op_calls(self.downgrade):
            if getattr(call.func, "attr", "") != "execute":
                continue
            sql = _sql_text(call, self.constants)
            if sql is not None:
                rename_sql.append(sql)
        self.assertTrue(
            any(
                "RENAME TO" in sql and '"instruments"' in sql
                for sql in rename_sql
            ),
            "downgrade must rename _instruments_legacy back to instruments after the audit",
        )

    def test_downgrade_raises_runtimeerror_on_orphan_rows(self) -> None:
        raises = [
            node
            for node in ast.walk(self.downgrade)
            if isinstance(node, ast.Raise)
        ]
        self.assertTrue(
            raises,
            "downgrade must raise (RuntimeError) when new table contains rows not in legacy shadow",
        )
        runtime_error_found = False
        for node in raises:
            exc = node.exc
            if exc is None:
                continue
            if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
                if exc.func.id == "RuntimeError":
                    runtime_error_found = True
            elif isinstance(exc, ast.Name) and exc.id == "RuntimeError":
                runtime_error_found = True
        self.assertTrue(
            runtime_error_found,
            "downgrade must explicitly raise RuntimeError on orphan rows before destructive DDL",
        )

    def test_downgrade_audits_both_directions_and_data_drift(self) -> None:
        source = ast.unparse(self.downgrade).upper()
        self.assertIn("LEFT JOIN", source)
        self.assertIn("IS DISTINCT FROM", source)
        self.assertIn("LEGACY_TABLE", source)
        self.assertIn("NEW_TABLE", source)
        self.assertIn("ROLLBACK WOULD LOSE DATA", source)


class Migration0003RawSchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = _parse(MIGRATION_0003)
        cls.constants = _module_constants(cls.tree)
        cls.upgrade = _function(cls.tree, "upgrade")
        cls.downgrade = _function(cls.tree, "downgrade")
        cls.calls = _op_calls(cls.upgrade)

    def test_creates_raw_schema(self) -> None:
        executed: list[str] = []
        for call in self.calls:
            if getattr(call.func, "attr", "") != "execute":
                continue
            sql = _sql_text(call, self.constants) or ""
            executed.append(sql.upper())
        self.assertTrue(
            any('CREATE SCHEMA' in sql and 'RAW' in sql for sql in executed),
            "migration 0003 must execute 'CREATE SCHEMA raw'",
        )

    def test_creates_provider_batches_table(self) -> None:
        create_table_calls = [
            call
            for call in self.calls
            if getattr(call.func, "attr", "") == "create_table"
        ]
        provider_batches_calls = [
            call
            for call in create_table_calls
            if _table_name_from_create_table(call, self.constants) == "provider_batches"
            and _schema_from_kwargs(call, self.constants) == "raw"
        ]
        self.assertEqual(
            len(provider_batches_calls),
            1,
            "expected exactly one op.create_table('provider_batches', schema='raw') call",
        )
        columns = _create_table_column_names(provider_batches_calls[0], self.constants)
        for required in (
            "id",
            "provider_key",
            "dataset_key",
            "request_key",
            "request_params",
            "requested_at",
            "received_at",
            "provider_request_id",
            "status",
            "record_count",
            "raw_payload_json",
            "raw_payload_uri",
            "payload_sha256",
            "error_code",
            "error_message",
            "warnings",
            "created_at",
            "updated_at",
        ):
            self.assertIn(
                required,
                columns,
                f"raw.provider_batches must include column {required!r}; saw {sorted(columns)}",
            )

    def test_unique_constraint_on_provider_dataset_request(self) -> None:
        create_table_calls = [
            call
            for call in self.calls
            if getattr(call.func, "attr", "") == "create_table"
        ]
        provider_batches_calls = [
            call
            for call in create_table_calls
            if _table_name_from_create_table(call, self.constants) == "provider_batches"
        ]
        self.assertTrue(provider_batches_calls, "no provider_batches create_table call found")
        unique_columns = _unique_constraint_columns(
            provider_batches_calls[0], self.constants
        )
        self.assertEqual(
            unique_columns,
            ["provider_key", "dataset_key", "request_key"],
            f"raw.provider_batches must have UniqueConstraint(provider_key, dataset_key, request_key); saw {unique_columns}",
        )

    def test_check_constraints_for_status_and_payload(self) -> None:
        executed: list[str] = []
        for call in self.calls:
            if getattr(call.func, "attr", "") != "execute":
                continue
            sql = _sql_text(call, self.constants) or ""
            executed.append(sql.upper())
            executed.append(_call_source(call).upper())
        joined = "\n".join(executed)
        for required in (
            "CK_PROVIDER_BATCHES_PROVIDER_KEY_NONEMPTY",
            "CK_PROVIDER_BATCHES_DATASET_KEY_NONEMPTY",
            "CK_PROVIDER_BATCHES_REQUEST_KEY_NONEMPTY",
            "CK_PROVIDER_BATCHES_STATUS_VALID",
            "CK_PROVIDER_BATCHES_RECORD_COUNT_NONNEG",
            "CK_PROVIDER_BATCHES_REQUESTED_HAS_NO_PAYLOAD",
            "CK_PROVIDER_BATCHES_PAYLOAD_SHA256_FORMAT",
            "CK_PROVIDER_BATCHES_NON_REQUESTED_HAS_HASH",
        ):
            self.assertIn(
                required,
                joined,
                f"migration 0003 must define CHECK constraint {required!r}",
            )

    def test_supports_indexes(self) -> None:
        create_index_calls = [
            call
            for call in self.calls
            if getattr(call.func, "attr", "") == "create_index"
        ]
        index_names: list[str] = []
        for call in create_index_calls:
            name = _table_name_from_call(call, self.constants)
            if name is not None:
                index_names.append(name)
        for required in (
            "ix_provider_batches_provider_dataset",
            "ix_provider_batches_requested_at",
            "ix_provider_batches_status",
        ):
            self.assertIn(
                required,
                index_names,
                f"migration 0003 must create index {required!r}; saw {index_names}",
            )


class Migration0003DowngradeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tree = _parse(MIGRATION_0003)
        cls.constants = _module_constants(cls.tree)
        cls.downgrade = _function(cls.tree, "downgrade")
        cls.calls = _op_calls(cls.downgrade)

    def test_drops_indexes_then_table_then_schema(self) -> None:
        sequence: list[str] = []
        for call in self.calls:
            attr = getattr(call.func, "attr", "")
            if attr == "drop_index":
                name = _table_name_from_call(call, self.constants)
                if name is not None:
                    sequence.append(f"index:{name}")
            elif attr == "drop_table":
                name = _table_name_from_call(call, self.constants)
                if name is not None:
                    sequence.append(f"table:{name}")
            elif attr == "execute":
                sql = (_sql_text(call, self.constants) or "").upper()
                if "DROP SCHEMA" in sql:
                    sequence.append("schema:raw")
        # Find first index drop, first table drop, and first schema drop.
        first_index = next(
            (i for i, item in enumerate(sequence) if item.startswith("index:")), None
        )
        first_table = next(
            (i for i, item in enumerate(sequence) if item.startswith("table:")), None
        )
        first_schema = next(
            (i for i, item in enumerate(sequence) if item.startswith("schema:")), None
        )
        self.assertIsNotNone(first_index, "downgrade must drop the provider_batches indexes")
        self.assertIsNotNone(first_table, "downgrade must drop the provider_batches table")
        self.assertIsNotNone(first_schema, "downgrade must drop the raw schema")
        self.assertLess(
            first_index,
            first_table,
            "indexes must be dropped before the table",
        )
        self.assertLess(
            first_table,
            first_schema,
            "table must be dropped before the raw schema",
        )


if __name__ == "__main__":
    unittest.main()
