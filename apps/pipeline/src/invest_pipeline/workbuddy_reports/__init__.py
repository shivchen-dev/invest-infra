"""M0/M1 WorkBuddy daily-report governance surface.

Exposes the validator entry point
:func:`invest_pipeline.workbuddy_reports.validator.validate_triplet` and the
M1 immutable-archive entry point
:func:`invest_pipeline.workbuddy_reports.archive.archive_run`.  The CLI is
implemented in :mod:`invest_pipeline.workbuddy_reports.__main__`.

Path-safety helpers (:func:`is_safe_workflow_run_id`,
:func:`is_valid_trade_date`) are deliberately **not** part of the public
package surface.  Same-package callers (notably
:mod:`invest_pipeline.workbuddy_reports.archive`) import them directly
from the validator submodule as internal helpers.
"""

from __future__ import annotations

from invest_pipeline.workbuddy_reports.archive import (
    SCHEMA_VERSION,
    ImportOutcome,
    archive_run,
)
from invest_pipeline.workbuddy_reports.validator import (
    SUPPORTED_RULES_VERSION,
    TOLERANCE,
    discover_triplet,
    validate_triplet,
)

__all__ = [
    "ImportOutcome",
    "SCHEMA_VERSION",
    "SUPPORTED_RULES_VERSION",
    "TOLERANCE",
    "archive_run",
    "discover_triplet",
    "validate_triplet",
]