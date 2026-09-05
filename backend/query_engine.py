"""Executes validated, read-only SQL against the auto-built database and
returns results as plain Python data - the only place where numbers are
actually computed.

Optimizations:
- Connection pooling via SQLAlchemy QueuePool
- Query result caching with TTL
- Pagination support for large result sets
- Query timeout protection
"""
import pandas as pd
from sqlalchemy import text

from backend.config import DEFAULT_TENANT
from backend.logging_config import get_logger
from backend.query_cache import get_query_cache
from backend.schema_introspect import get_engine, is_query_safe

log = get_logger(__name__)

# Default pagination settings
DEFAULT_PAGE_SIZE = 1000
MAX_PAGE_SIZE = 10000


class QueryError(Exception):
    pass


def run_query(
    sql: str, 
    tenant_id: str = DEFAULT_TENANT,
    use_cache: bool = True,
    page: int = 1,
    page_size: int | None = None,
) -> pd.DataFrame:
    """Execute a validated SQL query with optional caching and pagination.
    
    Args:
        sql: The SQL query to execute
        tenant_id: The tenant database to query
        use_cache: Whether to use query result caching
        page: Page number (1-indexed) for pagination
        page_size: Number of rows per page. When omitted, returns all rows.
        
    Returns:
        DataFrame with query results
    """
    # Validate query safety
    safe, reason = is_query_safe(sql, tenant_id)
    if not safe:
        raise QueryError(reason)
    
    # Check cache first for complete, non-paginated queries.
    cache = get_query_cache()
    if use_cache and page == 1 and page_size is None:
        cached = cache.get(sql, tenant_id)
        if cached is not None:
            return pd.DataFrame(cached["rows"])

    # Pagination is opt-in. Agent SQL controls LIMIT when the user asks for it.
    if page_size is None:
        paginated_sql = sql
    else:
        page_size = min(max(page_size, 1), MAX_PAGE_SIZE)
        offset = (page - 1) * page_size
        paginated_sql = f"{sql} LIMIT {page_size} OFFSET {offset}"

    engine = get_engine(tenant_id)
    try:
        with engine.connect() as conn:
            # Set query timeout (SQLite pragma)
            conn.execute(text("PRAGMA busy_timeout = 30000"))  # 30 seconds
            
            df = pd.read_sql(text(paginated_sql), conn)
            
            log.debug(
                "query_executed tenant_id=%s rows=%d page=%d page_size=%s",
                tenant_id, len(df), page, page_size or "all"
            )
            
            # Cache complete result sets only.
            if use_cache and page == 1 and page_size is None:
                cache_data = {
                    "rows": df.to_dict("records"),
                    "_tenant_id": tenant_id,
                }
                cache.set(sql, tenant_id, cache_data)
                
    except Exception as exc:  # noqa: BLE001
        log.error("query_failed tenant_id=%s error=%r", tenant_id, exc)
        raise QueryError(f"Query execution failed: {exc}") from exc
    
    return df


def get_query_stats() -> dict:
    """Get query execution statistics."""
    cache = get_query_cache()
    return {
        "cache": cache.get_stats(),
    }


def clear_query_cache(tenant_id: str | None = None) -> None:
    """Clear query cache for a tenant or all tenants."""
    cache = get_query_cache()
    if tenant_id:
        cache.invalidate_tenant(tenant_id)
    else:
        cache.clear()
