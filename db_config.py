"""
Database configuration and connection helpers for Postgres/PostGIS.

Usage:
1. Set environment variables: PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD
   Example (Windows PowerShell):
     $env:PGHOST = 'localhost'; $env:PGPORT = '5432'; $env:PGDATABASE = 'gisdb'; $env:PGUSER='user'; $env:PGPASSWORD='pass'

2. Import and use the `get_conn()` context manager or `run_query()` helper:
     from db_config import get_conn, run_query
     with get_conn() as conn:
         with conn.cursor() as cur:
             cur.execute("SELECT 1")

This module uses psycopg2's ThreadedConnectionPool for efficient reuse.
"""

from contextlib import contextmanager
import os
import logging
from typing import Optional

try:
    import psycopg2
    from psycopg2.pool import ThreadedConnectionPool
    from psycopg2.extras import RealDictCursor
except Exception as e:
    raise RuntimeError("psycopg2 is required. Activate your virtualenv and install psycopg2-binary") from e

logger = logging.getLogger(__name__)

# Read configuration from environment variables with sensible defaults
PGHOST = os.environ.get("PGHOST", "localhost")
PGPORT = int(os.environ.get("PGPORT", 5432))
PGDATABASE = os.environ.get("PGDATABASE", "postgres")
PGUSER = os.environ.get("PGUSER", "postgres")
PGPASSWORD = os.environ.get("PGPASSWORD", "")

# Connection pool (initialized lazily)
_pool: Optional[ThreadedConnectionPool] = None


def _init_pool(minconn: int = 1, maxconn: int = 10):
    """Initialize a ThreadedConnectionPool if not already created."""
    global _pool
    if _pool is None:
        dsn = {
            'host': PGHOST,
            'port': PGPORT,
            'database': PGDATABASE,
            'user': PGUSER,
            'password': PGPASSWORD,
        }
        logger.info("Initializing DB pool to %s@%s:%s/%s", PGUSER, PGHOST, PGPORT, PGDATABASE)
        _pool = ThreadedConnectionPool(minconn, maxconn, **dsn)
    return _pool


@contextmanager
def get_conn(minconn: int = 1, maxconn: int = 10):
    """Context manager that yields a connection from the pool and returns it when done.

    Example:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(...)
    """
    pool = _init_pool(minconn, maxconn)
    conn = None
    try:
        conn = pool.getconn()
        # use autocommit = False by default; caller controls transactions
        conn.autocommit = False
        yield conn
        # caller may commit; if still open and not committed, do nothing here
    except Exception:
        # on exception, ensure rollback so connection is clean for next reuse
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        raise
    finally:
        if conn is not None:
            try:
                pool.putconn(conn)
            except Exception:
                logger.exception("Failed to return connection to pool")


def close_pool():
    """Close all connections in the pool. Call on application shutdown."""
    global _pool
    if _pool:
        try:
            _pool.closeall()
        finally:
            _pool = None


def run_query(sql: str, params: tuple = (), fetch: Optional[str] = None):
    """Convenience helper to run a query.

    Args:
        sql: SQL string with placeholders (%s)
        params: tuple of parameters
        fetch: None | 'one' | 'all' | 'dict'
            - None: don't fetch
            - 'one': fetchone
            - 'all': fetchall
            - 'dict': fetchall with RealDictCursor

    Returns:
        rows or None
    """
    if fetch == 'dict':
        with get_conn() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                conn.commit()
                return rows
    else:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                if fetch == 'one':
                    row = cur.fetchone()
                    conn.commit()
                    return row
                if fetch == 'all':
                    rows = cur.fetchall()
                    conn.commit()
                    return rows
                # no fetch -> commit and return None
                conn.commit()
                return None


if __name__ == "__main__":
    # quick smoke test when run directly (requires env vars to be set)
    logging.basicConfig(level=logging.INFO)
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT version()')
                print(cur.fetchone())
    except Exception as e:
        print('DB smoke test failed:', e)