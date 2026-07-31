from __future__ import annotations


def test_definitions_import() -> None:
    from invest_pipeline.definitions import defs

    assert defs is not None