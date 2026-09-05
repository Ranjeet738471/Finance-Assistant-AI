"""Tools the agent may call. These are the ONLY way any real data or number
enters the conversation - the agent must never state a figure that didn't
come from a tool's output. Tools are built per-request via a factory so
each tool call is bound to the requesting tenant's database - one tenant's
agent can never read another tenant's data."""
import json

from langchain_core.tools import tool

from backend import confidence
from backend.config import DEFAULT_TENANT
from backend.query_engine import QueryError, run_query
from backend.schema_introspect import get_schema_prompt


def build_tools(tenant_id: str = DEFAULT_TENANT) -> list:
    """Returns fresh tool instances bound (via closure) to one tenant's
    database. Call once per agent invocation."""

    @tool
    def get_schema() -> str:
        """Return the live database schema: real table names, column names,
        and a couple of sample rows per table. Call this first if you are
        unsure which tables/columns exist before writing SQL."""
        return get_schema_prompt(tenant_id)

    @tool
    def run_sql(sql: str) -> str:
        """Execute a single read-only SQL SELECT statement against the
        finance database (SQLite dialect) and return the resulting rows as
        JSON. This is the ONLY source of real numbers - never state a figure
        that did not come from this tool's output. Only SELECT statements
        over tables shown by get_schema are allowed."""
        try:
            df = run_query(sql, tenant_id)
        except QueryError as exc:
            return json.dumps({"error": str(exc)})

        if confidence.is_effectively_empty(df):
            return json.dumps({"row_count": 0, "rows": [], "note": "No matching data found."})

        # Hard limit: Never send more than 1000 raw rows to LLM context
        # For large datasets, SQL should use GROUP BY/aggregations
        MAX_LLM_ROWS = 1000
        total_rows = len(df)
        if total_rows > MAX_LLM_ROWS:
            display_df = df.head(MAX_LLM_ROWS)
            truncation_note = f"Showing first {MAX_LLM_ROWS} of {total_rows} rows. Use GROUP BY for aggregations."
        else:
            display_df = df
            truncation_note = None

        anomalies = confidence.detect_anomalies(df)
        conf = confidence.score_confidence(df)
        result = {
            "row_count": total_rows,
            "rows": display_df.to_dict(orient="records"),
            "confidence": conf,
            "anomalies": anomalies,
        }
        if truncation_note:
            result["note"] = truncation_note
        return json.dumps(result, default=str)

    return [get_schema, run_sql]


def build_cross_tenant_tools(tenant_ids: list[str]) -> list:
    """Returns tool instances that can query across multiple tenants.
    The run_sql tool accepts a tenant_id argument so the agent can target
    a specific tenant or use 'ALL' to query every tenant and get
    per-tenant results stitched together. Admin/director only."""

    valid_ids = set(tenant_ids)

    @tool
    def get_schema(tenant_id: str = "ALL") -> str:
        """Return the live database schema for one tenant, or for ALL
        tenants (with each tenant's tables listed separately). Call this
        first to see which tables/columns exist in each tenant."""
        if tenant_id == "ALL":
            parts = []
            for tid in sorted(valid_ids):
                parts.append(f"=== TENANT: {tid} ===\n{get_schema_prompt(tid)}")
            return "\n\n".join(parts)
        if tenant_id not in valid_ids:
            return json.dumps({"error": f"Unknown tenant '{tenant_id}'. Available: {sorted(valid_ids)}"})
        return get_schema_prompt(tenant_id)

    @tool
    def run_sql(sql: str, tenant_id: str = "ALL") -> str:
        """Execute a single read-only SQL SELECT statement. Set tenant_id
        to a specific tenant name to query just that tenant, or 'ALL' to
        run the same query against every tenant and get per-tenant results.
        This is the ONLY source of real numbers - never state a figure that
        did not come from this tool's output."""
        if tenant_id != "ALL" and tenant_id not in valid_ids:
            return json.dumps({"error": f"Unknown tenant '{tenant_id}'. Available: {sorted(valid_ids)}"})

        targets = sorted(valid_ids) if tenant_id == "ALL" else [tenant_id]
        per_tenant = {}
        for tid in targets:
            try:
                df = run_query(sql, tid)
            except QueryError as exc:
                per_tenant[tid] = {"error": str(exc)}
                continue
            if confidence.is_effectively_empty(df):
                per_tenant[tid] = {"row_count": 0, "rows": [], "note": "No matching data found."}
                continue
            anomalies = confidence.detect_anomalies(df)
            conf = confidence.score_confidence(df)
            per_tenant[tid] = {
                "row_count": len(df),
                "rows": df.to_dict(orient="records"),
                "confidence": conf,
                "anomalies": anomalies,
            }

        if tenant_id == "ALL":
            return json.dumps({"tenant_id": "ALL", "per_tenant": per_tenant}, default=str)
        return json.dumps(per_tenant.get(tenant_id, {}), default=str)

    return [get_schema, run_sql]
