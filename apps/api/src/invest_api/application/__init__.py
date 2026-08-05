"""Application services for the ``invest-api`` HTTP layer.

Each module here owns one bounded slice of read-side use cases. The
services depend on the storage repositories through narrow
:class:`typing.Protocol` interfaces declared alongside the service so
the HTTP layer never imports the storage package directly; the
dependency factories in :mod:`invest_api.dependencies` wire the
concrete repositories into the services.
"""

from __future__ import annotations

__all__ = ["pipeline_runs"]