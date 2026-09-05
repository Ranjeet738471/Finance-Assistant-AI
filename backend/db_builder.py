"""Auto-detects CSV/Excel files in a tenant's data directory and (re)builds
a fresh SQLite database from them. Column names/types are inferred
automatically by pandas - no hardcoded schema. Whenever a tenant's source
files change (added, removed, or modified), that tenant's old database is
discarded and rebuilt from scratch - stale data is never mixed with new
data, and tenants never share a database file.
"""
import json
import re
import time
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, inspect

from backend.config import (
    DB_BACKEND,
    DEFAULT_TENANT,
    SUPPORTED_EXTENSIONS,
    tenant_data_dir,
    tenant_db_path,
    tenant_manifest_path,
)
from backend.schema_introspect import invalidate_engine

# Columns commonly used in WHERE, JOIN, and GROUP BY clauses
# These indexes improve query performance for typical analytics queries
INDEXED_COLUMNS = [
    "date",
    "vendor_id",
    "status",
    "transaction_id",
    "amount",
    "payout_date",
    "reconciliation_status",
    "payment_method",
    "account_id",
    "entity_id",
    "transaction_date",
    "transaction_type",
]

# Composite indexes for common multi-column query patterns
# Format: (index_name_suffix, [column1, column2, ...])
COMPOSITE_INDEXES = [
    ("date_status", ["date", "status"]),
    ("vendor_date", ["vendor_id", "date"]),
    ("status_amount", ["status", "amount"]),
]


def _sanitize_identifier(name: str) -> str:
    """Turn an arbitrary column/file name into a safe SQL identifier."""
    name = str(name).strip().lower()
    name = re.sub(r"[^0-9a-z_]+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    if not name:
        name = "col"
    if name[0].isdigit():
        name = f"c_{name}"
    return name


def _dedupe_columns(columns: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result = []
    for col in columns:
        if col not in seen:
            seen[col] = 0
            result.append(col)
        else:
            seen[col] += 1
            result.append(f"{col}_{seen[col]}")
    return result


def discover_files(tenant_id: str = DEFAULT_TENANT) -> list[Path]:
    data_dir = tenant_data_dir(tenant_id)
    return [
        p for p in sorted(data_dir.glob("**/*"))
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]


def _file_fingerprint(path: Path) -> dict:
    stat = path.stat()
    return {"size": stat.st_size, "mtime": stat.st_mtime}


def _compute_manifest(tenant_id: str, files: list[Path]) -> dict:
    data_dir = tenant_data_dir(tenant_id)
    return {str(f.relative_to(data_dir)): _file_fingerprint(f) for f in files}


def needs_rebuild(tenant_id: str = DEFAULT_TENANT) -> bool:
    files = discover_files(tenant_id)
    current = _compute_manifest(tenant_id, files)
    db_path = tenant_db_path(tenant_id)
    manifest_path = tenant_manifest_path(tenant_id)
    if not db_path.exists() or not manifest_path.exists():
        return True
    try:
        previous = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        return True
    return current != previous


def _read_any(path: Path) -> dict[str, pd.DataFrame]:
    """Read a CSV or Excel file. Excel files may contain multiple sheets,
    each becomes its own table. Uses chunked reading for large CSV files."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        # For large files, read in chunks to estimate memory usage
        file_size = path.stat().st_size
        # If file > 100MB, use chunked reading
        if file_size > 100 * 1024 * 1024:
            chunks = []
            for chunk in pd.read_csv(path, chunksize=50000):
                chunks.append(chunk)
            return {path.stem: pd.concat(chunks, ignore_index=True)}
        return {path.stem: pd.read_csv(path)}
    # .xlsx / .xls -> one DataFrame per sheet
    sheets = pd.read_excel(path, sheet_name=None)
    if len(sheets) == 1:
        only_name = next(iter(sheets))
        return {path.stem: sheets[only_name]}
    return {f"{path.stem}_{sheet}": df for sheet, df in sheets.items()}


def build_database(tenant_id: str = DEFAULT_TENANT, force: bool = False) -> dict:
    """Rebuild a tenant's SQLite database from whatever CSV/Excel files are
    currently in that tenant's data directory. The old database file is
    dropped first so no stale data lingers after the source files change."""
    if DB_BACKEND == "mysql":
        return {"rebuilt": False, "tenant_id": tenant_id, "backend": "mysql"}

    if not force and not needs_rebuild(tenant_id):
        return {"rebuilt": False, "tenant_id": tenant_id, "tables": list_tables(tenant_id)}

    files = discover_files(tenant_id)
    db_path = tenant_db_path(tenant_id)

    invalidate_engine(tenant_id)
    # On Windows, a just-disposed pooled SQLite connection can hold the file
    # handle open for a brief moment (especially with WAL mode), so an
    # immediate unlink() can raise PermissionError. Retry briefly instead of
    # failing the whole rebuild.
    for attempt in range(5):
        if not db_path.exists():
            break
        try:
            db_path.unlink()
            break
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2)

    engine = create_engine(f"sqlite:///{db_path}")
    table_summaries = []

    try:
        used_table_names: set[str] = set()
        for file_path in files:
            try:
                frames = _read_any(file_path)
            except Exception as exc:  # noqa: BLE001 - surface any parse error per file
                table_summaries.append({
                    "source_file": file_path.name,
                    "error": str(exc),
                })
                continue

            for raw_table_name, df in frames.items():
                table_name = _sanitize_identifier(raw_table_name)
                base_name = table_name
                suffix = 1
                while table_name in used_table_names:
                    table_name = f"{base_name}_{suffix}"
                    suffix += 1
                used_table_names.add(table_name)

                df.columns = _dedupe_columns([_sanitize_identifier(c) for c in df.columns])
                df.to_sql(table_name, engine, if_exists="replace", index=False)

                # Create indexes on commonly filtered columns for better query performance
                _create_indexes_for_table(engine, table_name, df.columns)

                table_summaries.append({
                    "source_file": file_path.name,
                    "table_name": table_name,
                    "rows": len(df),
                    "columns": list(df.columns),
                })
    finally:
        # Release the pooled connection/file handle now, not just on the
        # *next* rebuild - otherwise a second rebuild in the same process
        # can fail with PermissionError on Windows when it tries to unlink
        # this file.
        engine.dispose()

    tenant_manifest_path(tenant_id).write_text(json.dumps(_compute_manifest(tenant_id, files), indent=2))
    return {"rebuilt": True, "tenant_id": tenant_id, "tables": table_summaries}


def _create_indexes_for_table(engine, table_name: str, columns: list[str]) -> None:
    """Create indexes on commonly filtered columns for a table.
    
    Indexes dramatically improve query performance for WHERE, JOIN, and
    GROUP BY operations on these columns, especially as data scales.
    """
    from sqlalchemy import text
    
    column_set = {c.lower() for c in columns}
    
    with engine.connect() as conn:
        # Create single-column indexes
        for col in columns:
            if col.lower() in INDEXED_COLUMNS:
                index_name = f"idx_{table_name}_{col}"
                sql = text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({col})")
                try:
                    conn.execute(sql)
                except Exception:
                    pass
        
        # Create composite indexes if all columns exist in this table
        for suffix, idx_cols in COMPOSITE_INDEXES:
            if all(c.lower() in column_set for c in idx_cols):
                index_name = f"idx_{table_name}_{suffix}"
                cols_str = ", ".join(idx_cols)
                sql = text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name} ({cols_str})")
                try:
                    conn.execute(sql)
                except Exception:
                    pass
        
        conn.commit()


def list_tables(tenant_id: str = DEFAULT_TENANT) -> list[dict]:
    db_path = tenant_db_path(tenant_id)
    if not db_path.exists():
        return []
    engine = create_engine(f"sqlite:///{db_path}")
    try:
        inspector = inspect(engine)
        summaries = []
        for table_name in inspector.get_table_names():
            columns = [c["name"] for c in inspector.get_columns(table_name)]
            summaries.append({"table_name": table_name, "columns": columns})
        return summaries
    finally:
        engine.dispose()


if __name__ == "__main__":
    result = build_database(force=True)
    print(json.dumps(result, indent=2, default=str))
