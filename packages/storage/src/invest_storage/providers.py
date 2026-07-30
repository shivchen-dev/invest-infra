"""Session-provider abstraction for the storage layer.

This module is the canonical entry point for callers (Repositories, UnitOfWork)
that need a SQLAlchemy ``sessionmaker``. It re-exports the connection-level
primitives from :mod:`invest_storage.database` so repositories can depend on a
single, stable import path even if the underlying engine construction moves.

Two responsibilities live here:

1. Re-export :func:`session_factory`, :func:`build_engine` and
   :func:`session_scope` from :mod:`invest_storage.database` so callers do not
   import the database module directly. This keeps the layering explicit:

   - ``database.py`` - low-level engine construction and session lifecycle.
   - ``providers.py`` - the abstract "give me a Session" surface used by the
     repository / UoW layer.
   - ``repositories.py`` / ``unit_of_work.py`` - depend only on
     ``providers.py`` (and the SQLAlchemy ``Session`` type).

2. Expose the :class:`SessionProvider` protocol so the UnitOfWork can be wired
   against any object that hands out ``Session`` instances - the default
   ``sessionmaker`` binding in production, an in-memory SQLite ``Session`` for
   tests, or a fake in unit tests of UoW behavior.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from invest_storage.database import build_engine, session_factory, session_scope

__all__ = [
    "Engine",
    "Session",
    "SessionProvider",
    "build_engine",
    "session_factory",
    "session_scope",
]


@runtime_checkable
class SessionProvider(Protocol):
    """Anything that can hand out a SQLAlchemy ``Session``.

    The default implementation is the ``sessionmaker`` returned by
    :func:`invest_storage.database.session_factory`. The protocol lets the
    UnitOfWork be constructed against a fake provider in unit tests of the
    UoW itself, without spinning up a real database.
    """

    def __call__(self) -> Session:
        ...


def session_provider_from_engine(engine: Engine) -> sessionmaker[Session]:
    """Build a :class:`SessionProvider` from an existing :class:`Engine`.

    Thin convenience wrapper kept here (not in ``database.py``) so the
    ``database`` module can stay focused on engine construction and session
    lifecycle primitives.
    """

    return session_factory(engine)


def session_scope_from_provider(
    provider: SessionProvider,
) -> Iterator[Session]:
    """Context manager wrapper around a :class:`SessionProvider`.

    Calls ``provider()`` to obtain a session, yields it, then commits on
    clean exit and rolls back on exception. Mirrors the behaviour of
    :func:`invest_storage.database.session_scope` but accepts any
    :class:`SessionProvider`, not just a ``sessionmaker``.
    """

    session = provider()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()