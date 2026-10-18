"""PostgreSQL database adapter for Neon and cloud PostgreSQL hosting.

Provides transparent dual-database compatibility:
- Normalizes parameter placeholders (? -> %s).
- Implements PostgresRow matching sqlite3.Row behavior (dict-like and tuple-like access).
- Manages connection pooling, SSL enforcement (sslmode=require for Neon), and explicit transactions.
"""
from __future__ import annotations

import logging
from typing import Any, Iterator, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

try:
    import psycopg2
    import psycopg2.extensions
    import psycopg2.pool
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

logger = logging.getLogger("yatra.db.postgres")

_POOL: Optional[Any] = None


def adapt_sql(sql: str) -> str:
    """Converts SQLite '?' parameter placeholders to PostgreSQL '%s'.
    Preserves '?' inside single-quoted and double-quoted string literals.
    """
    out = []
    in_single = False
    in_double = False
    i = 0
    n = len(sql)
    while i < n:
        c = sql[i]
        if c == "'" and not in_double:
            if i + 1 < n and sql[i + 1] == "'":
                out.append("''")
                i += 2
                continue
            in_single = not in_single
            out.append(c)
        elif c == '"' and not in_single:
            in_double = not in_double
            out.append(c)
        elif c == '?' and not in_single and not in_double:
            out.append('%s')
        else:
            out.append(c)
        i += 1
    return "".join(out)


class PostgresRow(dict):
    """Dict-like and tuple-like row wrapper matching sqlite3.Row behavior."""

    def __init__(self, values: Sequence[Any], cols: Sequence[str]):
        super().__init__(zip(cols, values))
        self._values = tuple(values)
        self._cols = tuple(cols)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)

    def get(self, key: Any, default: Any = None) -> Any:
        if isinstance(key, int):
            return self._values[key] if 0 <= key < len(self._values) else default
        return super().get(key, default)

    def keys(self):
        return super().keys()

    def values(self):
        return self._values

    def items(self):
        return super().items()

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)


class PostgresCursorWrapper:
    """Cursor wrapper providing fetchone / fetchall with PostgresRow objects."""

    def __init__(self, raw_cursor: Any):
        self._raw_cursor = raw_cursor
        self._cols: Optional[List[str]] = (
            [d[0] for d in raw_cursor.description] if raw_cursor.description else None
        )

    def fetchone(self) -> Optional[PostgresRow]:
        row = self._raw_cursor.fetchone()
        if row is None:
            return None
        return PostgresRow(row, self._cols or [])

    def fetchall(self) -> List[PostgresRow]:
        rows = self._raw_cursor.fetchall()
        if not rows:
            return []
        cols = self._cols or []
        return [PostgresRow(r, cols) for r in rows]

    def fetchmany(self, size: Optional[int] = None) -> List[PostgresRow]:
        size = size or getattr(self._raw_cursor, "arraysize", 1)
        rows = self._raw_cursor.fetchmany(size)
        if not rows:
            return []
        cols = self._cols or []
        return [PostgresRow(r, cols) for r in rows]

    def __iter__(self) -> Iterator[PostgresRow]:
        while True:
            row = self.fetchone()
            if row is None:
                break
            yield row

    @property
    def rowcount(self) -> int:
        return self._raw_cursor.rowcount

    @property
    def description(self) -> Any:
        return self._raw_cursor.description

    def close(self) -> None:
        try:
            self._raw_cursor.close()
        except Exception:
            pass


class PostgresConnectionWrapper:
    """Connection wrapper providing .execute() and transactional isolation."""

    def __init__(self, raw_conn: Any, pool: Optional[Any] = None):
        self._raw_conn = raw_conn
        self._pool = pool
        self._closed = False

    def execute(self, sql: str, params: Sequence[Any] = ()) -> PostgresCursorWrapper:
        adapted = adapt_sql(sql)
        cur = self._raw_conn.cursor()
        cur.execute(adapted, params)
        return PostgresCursorWrapper(cur)

    def commit(self) -> None:
        try:
            if getattr(self._raw_conn, "autocommit", False):
                return
            self._raw_conn.commit()
        except Exception:
            pass

    def rollback(self) -> None:
        self._raw_conn.rollback()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._pool is not None:
            try:
                self._pool.putconn(self._raw_conn)
            except Exception:
                try:
                    self._raw_conn.close()
                except Exception:
                    pass
        else:
            try:
                self._raw_conn.close()
            except Exception:
                pass

    @property
    def in_transaction(self) -> bool:
        """True if a transaction is currently open on this connection."""
        try:
            return self._raw_conn.status != psycopg2.extensions.STATUS_READY
        except Exception:
            return False

    @property
    def isolation_level(self) -> None:
        """Emulate sqlite3 isolation_level=None (explicit transactions)."""
        return None

    def __enter__(self) -> "PostgresConnectionWrapper":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()


def normalize_neon_url(database_url: str) -> str:
    """Ensures sslmode=require for Neon and remote cloud postgres connections."""
    url = database_url
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "sslmode" not in qs and ("neon.tech" in parsed.netloc or "render.com" in parsed.netloc):
        qs["sslmode"] = ["require"]
    new_query = urlencode(qs, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def get_connection_pool(database_url: str, minconn: int = 1, maxconn: int = 10) -> Any:
    global _POOL
    if not HAS_PSYCOPG2:
        raise RuntimeError("psycopg2 is required for PostgreSQL connections. Install psycopg2-binary.")
    if _POOL is None:
        norm_url = normalize_neon_url(database_url)
        _POOL = psycopg2.pool.SimpleConnectionPool(minconn, maxconn, dsn=norm_url)
        logger.info("[Postgres Pool] Initialized connection pool for %s", parsed_host(norm_url))
    return _POOL


def parsed_host(url: str) -> str:
    try:
        p = urlparse(url)
        return p.hostname or "unknown-host"
    except Exception:
        return "hidden"


def connect_postgres(database_url: str, use_pool: bool = True) -> PostgresConnectionWrapper:
    """Establishes a connection to PostgreSQL (Neon / Cloud) and returns a wrapped connection."""
    if not HAS_PSYCOPG2:
        raise RuntimeError("psycopg2 is required for PostgreSQL. Please install psycopg2-binary.")
    norm_url = normalize_neon_url(database_url)
    if use_pool:
        pool = get_connection_pool(norm_url)
        raw_conn = pool.getconn()
        try:
            raw_conn.autocommit = True
        except Exception:
            pass
        return PostgresConnectionWrapper(raw_conn, pool=pool)
    else:
        raw_conn = psycopg2.connect(norm_url)
        try:
            raw_conn.autocommit = True
        except Exception:
            pass
        return PostgresConnectionWrapper(raw_conn, pool=None)
