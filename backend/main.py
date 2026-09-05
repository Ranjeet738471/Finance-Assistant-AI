"""FastAPI backend: file ingestion (auto rebuild DB) + grounded, agent-driven chat endpoint.
Simplified version: single tenant, no auth, no rate limiting (per hackathon "Out of Scope")."""
import base64
import io

from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel

from backend import db_builder, memory
from backend.agent import run_agent
from backend.config import (
    DEFAULT_LLM_PROVIDER,
    DEFAULT_TENANT,
    LLM_BASE_URL,
    LLM_MODEL,
    SARVAM_BASE_URL,
    SARVAM_MODEL,
    SUPPORTED_EXTENSIONS,
    tenant_data_dir,
)
from backend.logging_config import configure_logging, get_logger
from backend.query_cache import get_query_cache
from backend.query_engine import clear_query_cache, get_query_stats, run_query
from backend.schema_introspect import get_schema_map
from backend.tracing import configure_tracing

configure_logging()
configure_tracing()
log = get_logger(__name__)

app = FastAPI(title="Finance Assistant API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
FastAPIInstrumentor.instrument_app(app)


class ChatRequest(BaseModel):
    session_id: str = "default"
    message: str
    llm_provider: str | None = None  # "qwen" or "sarvam"


class ChatResponse(BaseModel):
    answer: str
    sql: str | None = None
    table: list[dict]
    confidence: dict | None = None
    anomalies: list[dict] = []
    status: str  # "ok" | "clarification_needed" | "out_of_scope" | "no_data" | "error"


@app.on_event("startup")
def startup_rebuild() -> None:
    db_builder.build_database(DEFAULT_TENANT, force=False)


@app.get("/health")
def health() -> dict:
    """Liveness/readiness probe: reports DB availability, query cache stats,
    and whether LLM endpoints are configured (does not call the LLMs)."""
    tables = get_schema_map(DEFAULT_TENANT)
    return {
        "status": "ok",
        "tables_loaded": len(tables),
        "llm_configured": bool(LLM_MODEL and LLM_BASE_URL),
        "sarvam_configured": bool(SARVAM_MODEL and SARVAM_BASE_URL),
        "default_provider": DEFAULT_LLM_PROVIDER,
        "query_stats": get_query_stats(),
    }


@app.get("/models")
def list_models() -> dict:
    """List available LLM providers and their configuration status."""
    return {
        "providers": [
            {
                "id": "qwen",
                "name": "Qwen (Local)",
                "model": LLM_MODEL,
                "configured": bool(LLM_MODEL and LLM_BASE_URL),
            },
            {
                "id": "sarvam",
                "name": "Sarvam AI",
                "model": SARVAM_MODEL,
                "configured": bool(SARVAM_MODEL and SARVAM_BASE_URL),
            },
        ],
        "default": DEFAULT_LLM_PROVIDER,
    }


@app.post("/upload")
async def upload_files(files: list[UploadFile]) -> dict:
    """Replaces the tenant's dataset: removes existing CSV/Excel files first
    so a new upload fully replaces old data instead of merging with it, then
    rebuilds the database fresh. Clears query cache after rebuild."""
    data_dir = tenant_data_dir(DEFAULT_TENANT)
    removed = []
    for existing in data_dir.glob("**/*"):
        if existing.is_file() and existing.suffix.lower() in SUPPORTED_EXTENSIONS:
            existing.unlink()
            removed.append(existing.name)

    saved = []
    for f in files:
        dest = data_dir / f.filename
        content = await f.read()
        dest.write_bytes(content)
        saved.append(f.filename)
    result = db_builder.build_database(DEFAULT_TENANT, force=True)
    # Clear query cache since data has changed
    clear_query_cache(DEFAULT_TENANT)
    log.info("uploaded_files=%s removed_files=%s rebuilt=%s cache_cleared=True", saved, removed, result.get("rebuilt"))
    return {"saved_files": saved, "removed_files": removed, **result}


@app.post("/rebuild")
def rebuild_db() -> dict:
    """Rebuild the database from data files and clear query cache."""
    result = db_builder.build_database(DEFAULT_TENANT, force=True)
    clear_query_cache(DEFAULT_TENANT)
    log.info("rebuilt=%s cache_cleared=True", result.get("rebuilt"))
    return {"rebuilt": result.get("rebuilt"), "cache_cleared": True}


@app.post("/cache/clear")
def clear_cache() -> dict:
    """Clear the query result cache. Call this after data changes
    if not using /upload or /rebuild endpoints."""
    clear_query_cache(DEFAULT_TENANT)
    log.info("cache_cleared tenant_id=%s", DEFAULT_TENANT)
    return {"cache_cleared": True, "tenant_id": DEFAULT_TENANT}


@app.get("/cache/stats")
def cache_stats() -> dict:
    """Get query cache statistics."""
    return get_query_stats()


@app.get("/tables")
def tables() -> dict:
    return {"tables": get_schema_map(DEFAULT_TENANT)}


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    if not get_schema_map(DEFAULT_TENANT):
        raise HTTPException(400, "No data loaded yet. Upload a CSV/Excel file first.")

    history = memory.get_history(req.session_id, DEFAULT_TENANT)

    try:
        result = run_agent(req.message, history, DEFAULT_TENANT, req.llm_provider)
    except Exception as exc:  # noqa: BLE001 - surface as a chat error, never crash
        answer = f"The assistant model is unavailable: {exc}"
        memory.append_turn(req.session_id, req.message, None, answer, DEFAULT_TENANT)
        return ChatResponse(answer=answer, table=[], status="error")

    memory.append_turn(req.session_id, req.message, result.get("sql"), result["answer"], DEFAULT_TENANT)
    return ChatResponse(
        answer=result["answer"],
        sql=result.get("sql"),
        table=result.get("table", []),
        confidence=result.get("confidence"),
        anomalies=result.get("anomalies", []),
        status=result.get("status", "ok"),
    )


@app.post("/export")
def export(req: ChatRequest, fmt: str = "csv") -> dict:
    """Re-runs the last SQL from the session history and returns it as
    CSV bytes (base64) for download."""
    history = memory.get_history(req.session_id, DEFAULT_TENANT)
    if not history or not history[-1].get("sql"):
        raise HTTPException(400, "No previous query to export.")

    df = run_query(history[-1]["sql"], DEFAULT_TENANT)
    buffer = io.BytesIO()
    df.to_csv(buffer, index=False)
    media_type = "text/csv"
    buffer.seek(0)
    return {"filename": "export.csv",
            "media_type": media_type,
            "content_base64": base64.b64encode(buffer.read()).decode()}
