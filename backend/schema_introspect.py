"""Builds a live description of the current database schema, used both to
prompt the LLM (so it never guesses table/column names) and to validate
generated SQL against a whitelist of real tables/columns. All functions are
tenant-scoped - each tenant has its own SQLite file and its own cached
engine, so data/schema never leaks across tenants."""
import threading
from urllib.parse import quote_plus

import sqlglot
from sqlglot import exp
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool

from backend.config import (
    DB_BACKEND,
    DEFAULT_TENANT,
    MYSQL_DB,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
    MYSQL_SSL_CA,
    MYSQL_USER,
    tenant_db_path,
)
from backend.logging_config import get_logger

log = get_logger(__name__)

_engine_cache: dict[str, Engine] = {}
_engine_lock = threading.Lock()

# Connection pool settings - tuned for larger datasets
POOL_SIZE = 10              # More concurrent connections
MAX_OVERFLOW = 20           # Burst capacity for concurrent queries
POOL_TIMEOUT = 60           # Longer timeout for large queries
POOL_RECYCLE = 1800         # Recycle connections after 30 minutes


def get_engine(tenant_id: str = DEFAULT_TENANT) -> Engine:
    """Get or create a SQLAlchemy engine with connection pooling for the tenant."""
    with _engine_lock:
        engine = _engine_cache.get(tenant_id)
        if engine is None:
            if DB_BACKEND == "mysql":
                user = quote_plus(MYSQL_USER)
                password = quote_plus(MYSQL_PASSWORD)
                url = f"mysql+pymysql://{user}:{password}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}"
                connect_args = {"ssl": {"ca": MYSQL_SSL_CA}} if MYSQL_SSL_CA else {}
                engine = create_engine(
                    url,
                    poolclass=QueuePool,
                    pool_size=POOL_SIZE,
                    max_overflow=MAX_OVERFLOW,
                    pool_timeout=POOL_TIMEOUT,
                    pool_recycle=POOL_RECYCLE,
                    connect_args=connect_args,
                )
            else:
                db_path = tenant_db_path(tenant_id)
                engine = create_engine(
                    f"sqlite:///{db_path}",
                    poolclass=QueuePool,
                    pool_size=POOL_SIZE,
                    max_overflow=MAX_OVERFLOW,
                    pool_timeout=POOL_TIMEOUT,
                    pool_recycle=POOL_RECYCLE,
                    connect_args={"check_same_thread": False},
                    execution_options={
                        "sqlite_pragma": [
                            ("journal_mode", "wal"),
                            ("synchronous", "normal"),
                            ("cache_size", "10000"),
                            ("temp_store", "memory"),
                        ]
                    }
                )
            _engine_cache[tenant_id] = engine
            log.info("engine_created tenant_id=%s pool_size=%d", tenant_id, POOL_SIZE)
        return engine


def invalidate_engine(tenant_id: str) -> None:
    """Disposes and drops the cached engine for a tenant. Must be called
    after rebuilding that tenant's database file so pooled connections
    don't point at a deleted/replaced SQLite file."""
    with _engine_lock:
        engine = _engine_cache.pop(tenant_id, None)
    if engine is not None:
        engine.dispose()


def get_schema_map(tenant_id: str = DEFAULT_TENANT) -> dict[str, list[str]]:
    """Returns {table_name: [column_name, ...]} for every table in the
    given tenant's database."""
    engine = get_engine(tenant_id)
    inspector = inspect(engine)
    return {
        table: [c["name"] for c in inspector.get_columns(table)]
        for table in inspector.get_table_names()
    }



def get_schema_prompt(tenant_id: str = DEFAULT_TENANT, sample_rows: int = 2) -> str:
    """A compact, human-readable schema + sample-data description to inject
    into LLM prompts."""
    schema = get_schema_map(tenant_id)
    if not schema:
        return "No tables available. The database is empty."

    engine = get_engine(tenant_id)
    lines = []
    with engine.connect() as conn:
        for table, columns in schema.items():
            lines.append(f"TABLE {table}({', '.join(columns)})")
            try:
                quoted_table = engine.dialect.identifier_preparer.quote(table)
                rows = conn.execute(
                    text(f"SELECT * FROM {quoted_table} LIMIT :n"), {"n": sample_rows}
                ).fetchall()
                for row in rows:
                    lines.append(f"  sample: {dict(zip(columns, row))}")
            except Exception:  # noqa: BLE001 - best-effort sampling only
                pass
    return "\n".join(lines)


_FORBIDDEN_NODE_TYPES = (
    exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Alter, exp.Create,
    exp.Command, exp.Pragma, exp.Merge,
)


def is_query_safe(sql: str, tenant_id: str = DEFAULT_TENANT) -> tuple[bool, str]:
    """AST-level validation (not string matching): only a single read-only
    SELECT statement over known tables is allowed. Parses the query with
    sqlglot and rejects any DML/DDL/PRAGMA/attach/command node anywhere in
    the tree - including inside subqueries and CTEs - which a naive keyword
    blacklist can miss."""
    try:
        statements = [s for s in sqlglot.parse(sql, read=DB_BACKEND) if s is not None]
    except Exception as exc:  # noqa: BLE001
        return False, f"Query could not be parsed: {exc}"

    if len(statements) != 1:
        return False, "Only a single SQL statement is permitted."

    root = statements[0]
    if not isinstance(root, exp.Select):
        return False, "Only SELECT queries are permitted."

    for node in root.walk():
        node_expr = node[0] if isinstance(node, tuple) else node
        if isinstance(node_expr, _FORBIDDEN_NODE_TYPES):
            return False, f"Query contains a disallowed operation: {type(node_expr).__name__}."

    schema = get_schema_map(tenant_id)
    known_tables = set(schema.keys())
    referenced_tables = {t.name for t in root.find_all(exp.Table)}
    if not referenced_tables:
        return False, "Query does not reference any known table."
    unknown = referenced_tables - known_tables
    if unknown:
        return False, f"Query references unknown table(s): {', '.join(sorted(unknown))}."

    return True, ""
