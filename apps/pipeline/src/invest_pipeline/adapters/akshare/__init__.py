"""AkShare adapter package (PR-02, DATA-SOURCE-MIGRATION-MATRIX.md §3 / §5.4).

The package is split into four cooperating modules that mirror the
Cifang adapter layout (``client.py`` / ``mapper.py`` / ``adapter.py``
/ ``config.py``) plus this ``__init__.py`` so the public surface stays
flat and importable from CI / local dev without the optional
``akshare`` dependency.

Boundary rules:

- ``config.py`` never imports the ``akshare`` SDK and never touches
  the network — it is a pure pydantic ``BaseSettings`` object
  (disabled by default per matrix §6, ``adjust`` locked to ``""``
  per ADR-0005 §4).
- ``client.py`` is the only module that may import the ``akshare``
  SDK; the import is performed lazily inside the fetch methods so the
  package stays importable when the optional dependency is absent.
- ``mapper.py`` is httpx-free and :mod:`pandas`-free; it operates on
  the list-of-dicts shape the client produces so unit tests can
  replay deterministic fixtures without booting a dataframe.
- ``adapter.py`` is the only module that constructs the
  three-layer domain evidence bundle
  (:class:`ProviderRequest` / :class:`ProviderAttempt` /
  :class:`ProviderBatch`); it owns the disabled-by-default gate.

The provider carries a distinct role matrix §3 pinned to
``research_only`` until the O-1 user confirmation closes.
"""

from __future__ import annotations

from invest_pipeline.adapters.akshare.adapter import AkshareInstrumentProvider
from invest_pipeline.adapters.akshare.config import AkshareSettings

__all__ = ["AkshareInstrumentProvider", "AkshareSettings"]
