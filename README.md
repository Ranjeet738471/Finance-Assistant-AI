# Finance Assistant

A conversational assistant that answers plain-language questions about your
own financial data (spend, vendor payouts, reconciliation status). Every
number in an answer comes from a real SQL query against your data — the
local LLM only translates the question into SQL and narrates the result; it
never computes or invents a figure.

## How grounding works (tool-calling agent)

1. Any `.csv` or `.xlsx`/`.xls` file dropped directly into `data/` is
  auto-loaded for the default assistant.
   Columns and types are inferred automatically — no fixed schema.
2. Uploading a new/changed file **drops the old database and rebuilds it
   fresh** from whatever is currently in `data/` (old data is never mixed in).
3. The local Qwen model runs as a real tool-calling agent with two tools:
   - `get_schema` — inspect real tables/columns/sample rows.
   - `run_sql` — execute a validated, read-only SELECT and get the actual
     computed rows (plus confidence + anomaly info).
4. The agent decides which tool(s) to call and in what order, then writes
   the final answer. It is instructed to never state a number that didn't
   come from a `run_sql` result, and to ask for clarification instead of
   guessing when a question is ambiguous.
5. Every `run_sql` call is validated at the AST level (via `sqlglot`, not
   string matching) - only a single read-only SELECT over known tables is
   allowed. DML/DDL/PRAGMA/ATTACH/multi-statement injection is rejected even
   inside subqueries.
6. Multi-turn follow-ups reuse the last few turns of conversation so the
   agent can resolve references like "the month before".
7. Tool output (row values, descriptions, etc.) is explicitly treated as
   untrusted data, not instructions, to reduce prompt-injection risk.

## Project layout

```
backend/
  config.py             # paths, LLM endpoint config
  db_builder.py          # CSV/Excel -> SQLite, auto column detection, fresh rebuild
  schema_introspect.py    # live schema for prompts + AST-based SQL validation (sqlglot)
  llm_client.py            # local Qwen model client (OpenAI-compatible API, retries/timeout)
  query_engine.py           # safe SQL execution
  confidence.py              # confidence scoring + robust (MAD-based) anomaly callouts
  tools.py                    # agent tool factory: get_schema, run_sql
  agent.py                     # tool-calling agent loop + tracing spans
  memory.py                     # persistent session history (SQLite-backed)
  tracing.py                      # OpenTelemetry setup (console or OTLP exporter)
  logging_config.py                # structured stdout logging
  main.py                           # FastAPI app (/upload, /chat, /tables, /export, /health)
frontend/
  app.py                          # Gradio chat UI
scripts/
  generate_sample_data.py          # optional: synthetic demo dataset
data/default/                          # CSV/Excel files for the default tenant
db/default.db                          # SQLite DB (gitignored)
db/sessions.db                         # conversation history store (gitignored)
tests/                                # pytest: SQL safety, anomaly/confidence
Dockerfile, docker-compose.yml         # container build + local orchestration (optional)
```

> **Note:** This is a simplified single-tenant version. Multi-tenancy, auth, and rate limiting were removed per the hackathon "Out of Scope" requirements.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Local model

The assistant expects an OpenAI-compatible endpoint serving Qwen (e.g. vLLM)
at `http://localhost:8008/v1`. Settings are read from a `.env` file in the
project root (already created; copy `.env.example` if you need to recreate
it):

```
FIN_LLM_MODEL=Qwen2.5-14B-Instruct
FIN_LLM_BASE_URL=http://localhost:8008/v1
FIN_LLM_API_KEY=EMPTY
FIN_LLM_TEMPERATURE=0.2
```

`.env` is gitignored so it's never committed; edit it directly to point at a
different model/endpoint.

### MySQL database

To query an existing MySQL database instead of rebuilding a local SQLite
database from uploaded files, add these values to `.env`:

```dotenv
FIN_DB_BACKEND=mysql
MYSQL_HOST=10.20.16.189
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=your-password
MYSQL_DB=finance_db
MYSQL_SSL_CA=
```

The phpMyAdmin URL is only the database administration web interface. The
application connects directly to MySQL on port `3306`.

**Tool calling requirement:** the agent relies on OpenAI-style tool/function
calling. If serving Qwen via vLLM, start it with tool-calling enabled, e.g.
`--enable-auto-tool-choice --tool-call-parser hermes` (or the Qwen-specific
parser for your vLLM version).

### Data

Put CSV/Excel files directly in `data/`. They are automatically loaded when
the backend starts; restart the backend or call `/rebuild` after changing the
files. The database is rebuilt fresh whenever it detects changed source data.
Optionally generate a synthetic demo dataset:

```powershell
.\.venv\Scripts\python.exe scripts\generate_sample_data.py
```

## Run

Use the PowerShell runner to launch either module without activating the
virtual environment. This also works when PowerShell blocks unsigned
activation scripts:

```powershell
# Backend only
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1 -Target backend

# Frontend only (requires the backend to already be running)
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1 -Target frontend

# Start both; closing the frontend stops the backend
powershell -ExecutionPolicy Bypass -File .\scripts\run.ps1 -Target all
```

The equivalent direct commands are:

```powershell
# Terminal 1: backend API
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000

# Terminal 2: chat UI (Gradio)
.\.venv\Scripts\python.exe frontend\app.py
```

Open the Gradio URL (http://localhost:8502), upload a file (or rely on `data/` files already
present), and start asking questions.

### Run with Docker

```powershell
docker compose up --build
```

Backend on `:8000`, Gradio UI on `:8502`. `data/` and `db/` are mounted as
volumes so uploaded files and the SQLite DB persist across restarts.

## Features included

- **Persistent session memory** (`backend/memory.py`): SQLite-backed,
  survives restarts, and is safe to share across multiple API worker
  processes. Swappable for Redis/Postgres later without changing the call
  sites (`get_history`/`append_turn`).
- **Distributed tracing** (OpenTelemetry): every `/chat` request, agent LLM
  call, and tool call is wrapped in a span (`backend/tracing.py`). Spans
  print to console by default; set `OTEL_EXPORTER_OTLP_ENDPOINT` to ship them
  to Jaeger/Tempo/Grafana/Honeycomb once a collector is deployed.
- **LLM call resilience**: configurable timeout (`FIN_LLM_TIMEOUT_SECONDS`)
  and automatic retries (`FIN_LLM_MAX_RETRIES`) on the OpenAI-compatible
  client, so transient network/model errors don't immediately fail a request.
- **AST-based SQL validation** (`sqlglot`) instead of keyword blacklisting —
  blocks multi-statement injection, UNION-based exfiltration, DML/DDL/PRAGMA,
  even inside subqueries.
- **`/health` endpoint** for liveness/readiness probes (reports DB and LLM
  config status without calling the LLM).
- **Structured logging** of every agent tool call and final answer status.
- **Prompt-injection guardrail**: the agent is instructed to treat all tool
  output/data as inert content, never as instructions.
- **Dockerfile + docker-compose** with a container health check (optional -
  not required to run locally; `docker compose up --build` when ready).
- **pytest suite** (`tests/`) covering SQL injection attempts and
  anomaly/confidence edge cases — run with `pytest -q`.

> **Note:** Multi-tenancy, API key auth, and rate limiting were removed per
> the hackathon "Out of Scope" requirements. This is a single-tenant,
> no-auth deployment suitable for demonstration purposes.

### Production hardening (not implemented - out of scope)

The following were explicitly marked "Out of Scope" for the hackathon:

- **Multi-tenancy**: Currently single-tenant only (`default`). Each tenant
  would need isolated data folders (`data/<tenant_id>/`) and DB files
  (`db/<tenant_id>.db`) with strict `tenant_id` validation.
- **Authentication**: No API key required. Add `FIN_API_KEY` env var and
  `X-API-Key` header validation for production.
- **Rate limiting**: No request throttling. Add per-key sliding-window limit
  (e.g., 60/min) returning HTTP 429 when exceeded.
- **Database scaling**: SQLite is fine for demo/small datasets. Move to
  Postgres/DuckDB for concurrent writers or large datasets.
- **Load balancing**: Add nginx/Kubernetes Service in front of multiple
  backend replicas for HA.
- **CORS restriction**: Currently allows all origins (`*`). Restrict to your
  actual frontend domain in production.
- **OTLP collector**: Traces print to console only. Deploy Jaeger/Tempo to
  receive traces in production.

## Environment variables reference

| Variable | Purpose | Default |
|---|---|---|
| `FIN_LLM_MODEL`, `FIN_LLM_BASE_URL`, `FIN_LLM_API_KEY` | Qwen endpoint | required |
| `FIN_LLM_TEMPERATURE` | Sampling temperature | `0.2` |
| `FIN_LLM_TIMEOUT_SECONDS` | Per-call LLM timeout | `30` |
| `FIN_LLM_MAX_RETRIES` | LLM call retries | `3` |
| `FIN_DATA_DIR`, `FIN_DB_DIR` | Root folders for data/DB | `./data`, `./db` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Ship traces to a collector | unset (console only) |
| `FIN_OTEL_SERVICE_NAME` | Service name in traces | `finance-assistant` |

> **Removed (out of scope):** `FIN_API_KEY`, `FIN_RATE_LIMIT_PER_MINUTE` —
> auth and rate limiting are not implemented in this simplified version.


## Notes

- Rebuilding is automatic on backend startup and on every `/upload`, based on
  file size/mtime changes — no manual DB migration needed.
- `/export` re-runs the last query and returns CSV/Excel bytes for download.
- If the LLM endpoint is unreachable, the API returns a clear error instead
  of a fabricated answer.
- The agent is capped at 5 tool-call steps per question (`MAX_STEPS` in
  `backend/agent.py`) to prevent runaway loops.
#   F i n a n c e - A s s i s t a n t - A I 
 
 