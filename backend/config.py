"""Central configuration for the finance assistant backend."""
import os
import re
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Each tenant gets its own data folder and SQLite file, so uploads from one
# customer/org never mix with another's. DEFAULT_TENANT keeps single-tenant
# usage (and the existing tests/scripts) working unchanged.
DATA_ROOT = Path(os.environ.get("FIN_DATA_DIR", BASE_DIR / "data"))
DB_ROOT = Path(os.environ.get("FIN_DB_DIR", BASE_DIR / "db"))
DEFAULT_TENANT = "default"

# Finance database backend. SQLite remains the default for local CSV uploads;
# set DB_BACKEND=mysql to query an existing MySQL database directly.
DB_BACKEND = os.environ.get("FIN_DB_BACKEND", "sqlite").lower()
MYSQL_HOST = os.environ.get("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_DB = os.environ.get("MYSQL_DB", "finance_db")
MYSQL_SSL_CA = os.environ.get("MYSQL_SSL_CA", "")

DATA_ROOT.mkdir(parents=True, exist_ok=True)
DB_ROOT.mkdir(parents=True, exist_ok=True)

_TENANT_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _validate_tenant_id(tenant_id: str) -> str:
    """tenant_id is user-controlled (request body/query param). Without
    this check, a crafted value like '../../etc' could escape DATA_ROOT/
    DB_ROOT (path traversal), and arbitrary values would each lazily create
    a new SQLite file on disk (unbounded disk usage)."""
    if not _TENANT_ID_RE.match(tenant_id):
        raise ValueError(
            "Invalid tenant_id: only letters, digits, '_' and '-' are allowed (max 64 chars)."
        )
    return tenant_id


def tenant_data_dir(tenant_id: str) -> Path:
    tenant_id = _validate_tenant_id(tenant_id)
    # The single-tenant UI reads its finance files directly from data/. Named
    # tenants remain isolated in their own data/<tenant_id>/ directories.
    path = DATA_ROOT if tenant_id == DEFAULT_TENANT else DATA_ROOT / tenant_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def tenant_db_path(tenant_id: str) -> Path:
    tenant_id = _validate_tenant_id(tenant_id)
    return DB_ROOT / f"{tenant_id}.db"


def tenant_manifest_path(tenant_id: str) -> Path:
    tenant_id = _validate_tenant_id(tenant_id)
    return DB_ROOT / f"{tenant_id}.manifest.json"


# Shared, cross-tenant SQLite store for conversation history (session
# memory). Kept separate from the per-tenant finance data.
SESSIONS_DB_PATH = DB_ROOT / "sessions.db"

# Local Qwen model served via an OpenAI-compatible endpoint (e.g. vLLM).
# Values come solely from .env - no hardcoded fallback here to avoid drift.
LLM_MODEL = os.environ.get("FIN_LLM_MODEL")
LLM_BASE_URL = os.environ.get("FIN_LLM_BASE_URL")
LLM_API_KEY = os.environ.get("FIN_LLM_API_KEY")
LLM_TEMPERATURE = float(os.environ.get("FIN_LLM_TEMPERATURE", "0.2"))
LLM_TIMEOUT_SECONDS = float(os.environ.get("FIN_LLM_TIMEOUT_SECONDS", "30"))
LLM_MAX_RETRIES = int(os.environ.get("FIN_LLM_MAX_RETRIES", "3"))

# Sarvam AI API configuration (alternative provider)
SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY")
SARVAM_BASE_URL = os.environ.get("SARVAM_BASE_URL", "https://api.sarvam.ai/v1")
SARVAM_MODEL = os.environ.get("SARVAM_MODEL", "sarvam-1")

# Default LLM provider (qwen or sarvam)
DEFAULT_LLM_PROVIDER = os.environ.get("DEFAULT_LLM_PROVIDER", "qwen")

# Disable SSL certificate verification (use with caution - only for development/testing)
DISABLE_SSL_VERIFICATION = os.environ.get("DISABLE_SSL_VERIFICATION", "false").lower() in ("true", "1", "yes")

# If set, all endpoints except /health require this value in the
# X-API-Key header. Leave unset only for local development.
API_KEY = os.environ.get("FIN_API_KEY")

# Comma-separated list of API keys that are granted cross-tenant (admin)
# access. Holders of these keys can list all tenants and query across
# multiple/all tenants. Regular API keys are still scoped to a single
# tenant per request. Leave unset to disable the admin view entirely.
ADMIN_API_KEYS = {
    k.strip()
    for k in os.environ.get("FIN_ADMIN_API_KEYS", "").split(",")
    if k.strip()
}

# Simple per-key rate limit (requests per minute). Single-instance only -
# see backend/rate_limiter.py for the multi-instance upgrade path.
RATE_LIMIT_PER_MINUTE = int(os.environ.get("FIN_RATE_LIMIT_PER_MINUTE", "60"))

# Distributed tracing. Console output by default; set to a collector's OTLP
# HTTP endpoint (e.g. http://localhost:4318/v1/traces) to ship spans to
# Jaeger/Tempo/Grafana/etc.
OTEL_SERVICE_NAME = os.environ.get("FIN_OTEL_SERVICE_NAME", "finance-assistant")
OTEL_EXPORTER_OTLP_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")

SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}

