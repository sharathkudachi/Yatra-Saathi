"""Explicit transactions. Writes use BEGIN IMMEDIATE (SQLite write lock) to avoid races."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator


@contextmanager
def transaction(conn: sqlite3.Connection, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
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
