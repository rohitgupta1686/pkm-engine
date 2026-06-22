"""Tests for _ResilientConnection — Turso/Hrana idle-connection drop recovery.

Regression cover for the concept-synthesis bug: a slow LLM call lets Turso close
the idle Hrana connection, so the next write raised
"Hrana: http error: connection closed before message completed" and the CLI
exited 1. The wrapper must reconnect-and-retry that statement — but only for
Turso connections, and only outside an explicit transaction.
"""
import pytest

from pkm.config import Settings
from pkm.store import registry
from pkm.store.registry import _ResilientConnection

DROP_MSG = "Hrana: http error: connection closed before message completed"


class FakeConn:
    """Minimal libsql-like connection that can be told to drop on next execute."""

    def __init__(self, tag):
        self.tag = tag
        self.executed = []
        self.drop_next = False
        self.closed = False

    def execute(self, sql, *args, **kwargs):
        if self.drop_next:
            self.drop_next = False
            raise Exception(DROP_MSG)
        self.executed.append(sql)
        return f"cursor:{self.tag}"

    def commit(self):
        self.executed.append("COMMIT()")

    def rollback(self):
        self.executed.append("ROLLBACK()")

    def close(self):
        self.closed = True


@pytest.fixture
def fake_opener(monkeypatch):
    """Patch _open_raw to hand out a sequence of FakeConns, newest tagged by index."""
    conns = []

    def _open(settings):
        c = FakeConn(len(conns))
        conns.append(c)
        return c

    monkeypatch.setattr(registry, "_open_raw", _open)
    return conns


def _turso_settings():
    return Settings(openai_api_key="k", turso_url="libsql://x.turso.io", turso_token="t")


def _local_settings():
    return Settings(openai_api_key="k", db_path="pkm.db")  # no turso_url


def test_reconnects_and_retries_on_drop_outside_txn(fake_opener):
    rc = _ResilientConnection(_turso_settings())
    assert len(fake_opener) == 1
    fake_opener[0].drop_next = True

    cur = rc.execute("INSERT INTO concepts VALUES (1)")

    # A second connection was opened and the statement ran on it.
    assert len(fake_opener) == 2
    assert cur == "cursor:1"
    assert fake_opener[0].closed is True
    assert fake_opener[1].executed == ["INSERT INTO concepts VALUES (1)"]


def test_does_not_retry_inside_transaction(fake_opener):
    rc = _ResilientConnection(_turso_settings())
    rc.execute("BEGIN")
    fake_opener[0].drop_next = True

    with pytest.raises(Exception, match="connection closed"):
        rc.execute("INSERT INTO claims VALUES (1)")

    # No reconnect: an in-transaction drop must surface so rollback can run.
    assert len(fake_opener) == 1


def test_commit_clears_transaction_state(fake_opener):
    rc = _ResilientConnection(_turso_settings())
    rc.execute("BEGIN")
    rc.commit()  # back outside a txn
    fake_opener[0].drop_next = True

    rc.execute("SELECT 1")  # now eligible for retry again
    assert len(fake_opener) == 2


def test_local_connection_never_reconnects(fake_opener):
    rc = _ResilientConnection(_local_settings())
    fake_opener[0].drop_next = True

    # A dropped local/in-memory handle must never be silently replaced.
    with pytest.raises(Exception, match="connection closed"):
        rc.execute("SELECT 1")
    assert len(fake_opener) == 1


def test_non_drop_errors_propagate(fake_opener):
    rc = _ResilientConnection(_turso_settings())

    def boom(*a, **k):
        raise Exception("UNIQUE constraint failed")

    fake_opener[0].execute = boom
    with pytest.raises(Exception, match="UNIQUE constraint"):
        rc.execute("INSERT INTO x VALUES (1)")
    assert len(fake_opener) == 1  # not a drop → no reconnect
