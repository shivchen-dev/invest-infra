from invest_storage import StockPriceLimitRow


def test_stock_price_limits_model_matches_migration_contract() -> None:
    table = StockPriceLimitRow.__table__
    assert (table.schema, table.name) == ("core", "stock_price_limits")
    assert table.c.id.primary_key
    assert not table.c.instrument_id.nullable
    assert not table.c.trade_date.nullable
    assert table.c.limit_up_price.nullable
    assert table.c.limit_down_price.nullable
    assert table.c.source_batch_id.nullable
    assert {str(fk.target_fullname) for fk in table.foreign_keys} == {
        "core.instruments.id",
        "raw.provider_batches.id",
    }
    assert {constraint.name for constraint in table.constraints} >= {
        "uq_stock_price_limits_instrument_trade_date_revision_row_hash",
        "ck_stock_price_limits_revision_positive",
        "ck_stock_price_limits_row_hash_len64",
    }
    assert {index.name for index in table.indexes} == {
        "ix_stock_price_limits_instrument_trade_date",
        "ix_stock_price_limits_trade_date",
    }
