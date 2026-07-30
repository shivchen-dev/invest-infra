"""Mock-based unit tests for :class:`SqlAlchemyUnitOfWork`.

These tests use :class:`unittest.mock.MagicMock` to stand in for the
SQLAlchemy ``Session`` and the ``SessionProvider`` so the UnitOfWork's
transaction-boundary behaviour can be verified without booting
Testcontainers or speaking to a real database.

The behaviour being verified mirrors the contract documented in
``packages/storage/src/invest_storage/unit_of_work.py``:

- ``commit()`` and ``rollback()`` delegate to the underlying session.
- ``__exit__`` commits on clean exit and rolls back on exception.
- ``__exit__`` closes the session regardless of the outcome.
- ``uow.instruments`` and ``uow.provider_batches`` return cached
  repository instances for the lifetime of the UoW.
- Accessing repositories after the UoW closed should not be done in
  production, but the current implementation explicitly clears them on
  exit; this test pins that behaviour so a future refactor cannot
  silently regress it.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from invest_storage.repositories import (
    SqlAlchemyInstrumentRepository,
    SqlAlchemyProviderBatchRepository,
)
from invest_storage.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy.orm import Session


class SqlAlchemyUnitOfWorkMockTests(unittest.TestCase):
    """Mock tests covering the transactional / lifecycle contract of the UoW."""

    def setUp(self) -> None:
        # Each test gets a fresh session mock and a session-provider callable
        # that hands that exact mock out.
        self._session = MagicMock(name="Session", spec=Session)
        self._session_factory = MagicMock(name="SessionProvider", return_value=self._session)
        self._uow = SqlAlchemyUnitOfWork(self._session_factory)

    def _enter(self) -> SqlAlchemyUnitOfWork:
        """Enter the UoW context manager and assert session provisioning."""

        result = self._uow.__enter__()
        self.assertIs(result, self._uow)
        self._session_factory.assert_called_once_with()
        # `commit` / `rollback` etc have not been called yet at this point
        self._session.commit.assert_not_called()
        self._session.rollback.assert_not_called()
        self._session.close.assert_not_called()
        self.assertFalse(self._uow.closed)
        return result

    def _exit_with_exception(self) -> None:
        """Drive ``__exit__`` through the exception branch (rollback, no commit)."""

        self._uow.__exit__(RuntimeError, RuntimeError("simulated"), None)

    def _exit_clean(self) -> None:
        """Drive ``__exit__`` through the clean-exit branch (auto-commit)."""

        self._uow.__exit__(None, None, None)

    # ------------------------------------------------------------------
    # commit / rollback delegation
    # ------------------------------------------------------------------

    def test_uow_commit_calls_session_commit(self) -> None:
        # Drive the UoW through an exception-exit so __exit__ rolls back
        # instead of double-committing. That isolates the explicit
        # ``commit()`` call from the implicit one in ``__exit__``.
        self._enter()
        try:
            self._uow.commit()
        finally:
            self._exit_with_exception()

        self._session.commit.assert_called_once_with()
        self._session.rollback.assert_called_once_with()
        self._session.close.assert_called_once_with()

    def test_uow_rollback_calls_session_rollback(self) -> None:
        # Clean exit will commit AFTER our explicit rollback; the test
        # verifies that ``rollback()`` is what we wanted: it reaches the
        # session and ``session.commit`` is NOT called from inside the
        # user-supplied code path (only from ``__exit__``).
        self._enter()
        try:
            self._uow.rollback()
        finally:
            self._exit_clean()

        self._session.rollback.assert_called_once_with()
        self._session.close.assert_called_once_with()

    # ------------------------------------------------------------------
    # context manager lifecycle
    # ------------------------------------------------------------------

    def test_uow_context_manager_closes_session_on_clean_exit(self) -> None:
        with self._uow as uow:
            self.assertIs(uow, self._uow)
            self.assertFalse(self._uow.closed)
            # clean exit path commits automatically
            self._session.commit.assert_not_called()

        # clean exit triggered exactly one commit + one close
        self._session.commit.assert_called_once_with()
        self._session.rollback.assert_not_called()
        self._session.close.assert_called_once_with()
        self.assertTrue(self._uow.closed)

    def test_uow_context_manager_rolls_back_on_exception(self) -> None:
        with self.assertRaises(ValueError), self._uow:
            self._session.commit.assert_not_called()
            self._session.rollback.assert_not_called()
            raise ValueError("boom from inside the with-block")

        # exception path rolled back, did NOT commit, and still closed
        self._session.rollback.assert_called_once_with()
        self._session.commit.assert_not_called()
        self._session.close.assert_called_once_with()
        self.assertTrue(self._uow.closed)

    def test_uow_context_manager_rolls_back_when_commit_raises(self) -> None:
        # make Session.commit raise to verify the inner `try/except`
        # in __exit__ rolls back and re-raises.
        self._session.commit.side_effect = RuntimeError("commit failed")

        with self.assertRaises(RuntimeError), self._uow:
            pass

        self._session.commit.assert_called_once_with()
        # the inner except branch rolled back once
        self._session.rollback.assert_called_once_with()
        self._session.close.assert_called_once_with()
        self.assertTrue(self._uow.closed)

    # ------------------------------------------------------------------
    # repository properties
    # ------------------------------------------------------------------

    def test_uow_instruments_property_returns_repository(self) -> None:
        with self._uow as uow:
            instruments = uow.instruments
            self.assertIsInstance(instruments, SqlAlchemyInstrumentRepository)
            # the same session the factory handed out is wired into the repo
            self.assertIs(instruments._session, self._session)

    def test_uow_provider_batches_property_returns_repository(self) -> None:
        with self._uow as uow:
            batches = uow.provider_batches
            self.assertIsInstance(batches, SqlAlchemyProviderBatchRepository)
            self.assertIs(batches._session, self._session)

    def test_uow_repository_properties_are_cached_per_uow(self) -> None:
        # The UoW promises the same repository instance is reused for the
        # lifetime of the UoW so SQLAlchemy's identity map behaves as expected.
        with self._uow as uow:
            first_instruments = uow.instruments
            first_batches = uow.provider_batches
            self.assertIs(uow.instruments, first_instruments)
            self.assertIs(uow.provider_batches, first_batches)

        # After exit the internal refs are cleared, and re-entering the UoW
        # produces fresh repository instances.
        with self._uow as uow:
            self.assertIsNot(uow.instruments, first_instruments)
            self.assertIsNot(uow.provider_batches, first_batches)

    # ------------------------------------------------------------------
    # post-exit safety
    # ------------------------------------------------------------------

    def test_uow_session_property_raises_outside_context_manager(self) -> None:
        # Brand-new UoW: the session is None until __enter__
        with self.assertRaises(RuntimeError):
            _ = self._uow.session

    def test_uow_commit_after_rollback_raises_or_is_noop(self) -> None:
        """Calling :meth:`commit` after the UoW has closed must not silently succeed.

        ``SqlAlchemyUnitOfWork.__exit__`` clears ``self._session`` on exit.
        Any subsequent call to ``commit`` therefore hits the guard in the
        ``session`` property and raises :class:`RuntimeError`. This test
        pins that contract so a future refactor cannot regress to a silent
        no-op (or worse, a NullPointerError).
        """

        self._enter()
        self._exit_with_exception()

        # The UoW has now closed and self._session has been cleared.
        self.assertIsNone(self._uow._session)  # noqa: SLF001 - intentional introspection
        self.assertTrue(self._uow.closed)
        # exit-with-exception rolled back (no commit, no double-commits)
        self._session.commit.assert_not_called()
        self._session.rollback.assert_called_once_with()
        self._session.close.assert_called_once_with()

        with self.assertRaises(RuntimeError):
            self._uow.commit()

        with self.assertRaises(RuntimeError):
            self._uow.rollback()

        # Neither post-exit call should have reached the released session mock.
        self._session.commit.assert_not_called()
        self._session.rollback.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
