"""Explicit transactions for SQLite and PostgreSQL.
Writes use BEGIN IMMEDIATE (SQLite write lock) to avoid races, and BEGIN for PostgreSQL.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator


@contextmanager
def transaction(conn: Any, *, immediate: bool = True) -> Iterator[Any]:
    from src.db.postgres import PostgresConnectionWrapper

    if isinstance(conn, PostgresConnectionWrapper):
        if conn.in_transaction:
            raise RuntimeError("nested transactions are not allowed")
        conn.execute("BEGIN")
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()
    else:
        if conn.isolation_level is not None:
            raise RuntimeError("connection must use isolation_level=None (explicit transactions)")
        if conn.in_transaction:
            raise RuntimeError("nested transactions are not allowed")
        conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield conn
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")
