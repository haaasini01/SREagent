# SRE Agent

A staged incident-response agent using FastAPI, React/TypeScript, LangGraph, the MCP Python SDK, PostgreSQL, and local Ollama inference.

The working folder is still named `ops-swarm-rebuild`; the app and project branding is now **SRE Agent**.

The project is being built in stages. All operations remain simulated; no tool connects to or modifies real infrastructure.

**Progress:** Original stages 1–7 and portfolio-upgrade Stages 1–7 are implemented. The local telemetry sandbox generates request events and metrics; analysis retrieves and validates version-controlled runbook evidence.

See [PROJECT_GUIDE.md](../PROJECT_GUIDE.md) for the full explanation of the
project, architecture, request flow, setup, and API. The stage-by-stage build
record is in [the workspace-level `PROJECT_STAGES.md`](../PROJECT_STAGES.md).
The next portfolio-upgrade stages are tracked in [ROADMAP_NEXT.md](./ROADMAP_NEXT.md).

## Run the deterministic evaluation

From the project directory in PowerShell, with backend dependencies installed:

```powershell
$env:PYTHONPATH = "backend"
python -m app.evaluation
```

The versioned fixture suite checks expected runbook retrieval, citations,
abstention, action choice, and tool allowlist behavior. It uses scripted model
responses, not Ollama inference; its passing rates validate deterministic
workflow contracts and are not measurements of model accuracy.

The telemetry sandbox is a separate local service. Compose starts it with the
database, and the API ingests its generated events and metrics through
`POST /api/sandbox/run`. Telemetry scenarios are controlled/synthetic and do
not originate from an external production system.

## Run the application

### Start PostgreSQL

From this directory, start the local database and telemetry sandbox:

```powershell
docker compose up -d --build db sandbox
```

The sandbox generates structured request events for healthy, database-failure,
and high-latency scenarios. The API ingests each run as a persisted incident.

### Backend

From this directory, in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m uvicorn app.main:app --app-dir backend --reload
```

The API health check is at `http://localhost:8000/api/health`; interactive API docs are at `http://localhost:8000/docs`. The API creates its tables at startup and requires PostgreSQL to be running.

### Frontend

In a second terminal:

```powershell
Set-Location frontend
npm install
npm run dev
```

Open the Vite URL shown in the terminal (normally `http://localhost:5173`).
The dashboard checks the backend through Vite's local API proxy. Use **Run
sandbox & ingest** to generate three requests and persist their telemetry as an
incident.

### One-command local start

After completing the one-time dependency setup above, run this from the
project directory:

```powershell
.\scripts\start-local.ps1
```

The script starts PostgreSQL and the sandbox with Docker Compose, then opens
backend and frontend development servers in separate terminal windows. Ollama
still needs to be installed, have the configured model available, and be
running for incident analysis. Stop the development servers with `Ctrl+C` in
their windows; stop local containers with `docker compose stop db sandbox`.

## Implemented stages

1. Foundation: API/UI shells and local database service.
2. Incident and remediation data models, plus PostgreSQL persistence.
3. Simulated operations exposed as MCP tools.
4. LangGraph diagnosis and remediation proposal workflow (local Ollama).
5. Human approval/rejection and simulated execution verification.
6. Dashboard scenarios and operator console.
7. Safety policy tests, integration tests, and operational documentation.

The portfolio upgrade is tracked separately in [ROADMAP_NEXT.md](./ROADMAP_NEXT.md).
Upgrade Stages 1–7 (telemetry, runbooks, evidence-grounded analysis,
operator experience, deterministic evaluation, reliability/security hardening,
and portfolio presentation) are implemented. The demo recording/publishing
remains an optional manual follow-up.

The portfolio demo storyboard and recording guidance are in
[DEMO_WALKTHROUGH.md](./DEMO_WALKTHROUGH.md).

## Resume-ready project summary

- Built a local SRE incident-triage application with FastAPI, LangGraph,
  Ollama, PostgreSQL, MCP, and a React/TypeScript dashboard.
- Implemented structured telemetry ingestion, deterministic runbook
  retrieval, citation-ID validation, and no-action abstention while
  preserving mandatory human approval for simulated operations.
- Added PostgreSQL action history, opt-in idempotent API retries, bounded
  analysis/tool execution, and regression tests; backend and frontend checks
  run in GitHub Actions.

These bullets describe shipped prototype features. The included fixture
evaluation is not a real-model quality benchmark; do not claim production
remediation or calibrated model accuracy.

## API

- `POST /api/incidents`: create an incident with a title, severity, and logs.
- `GET /api/incidents`: list incidents, newest first.
- `GET /api/incidents/{incident_id}`: retrieve one incident.
- `POST /api/incidents/{incident_id}/actions`: record an allowlisted action as `PENDING_APPROVAL`.
- `GET /api/incidents/{incident_id}/actions`: list the incident's proposed actions.
- `POST /api/incidents/{incident_id}/analyze`: analyze logs with Ollama and retrieved runbook evidence; returns a validated pending action or an abstention with no action.
- `GET /api/runbooks/search?q=...`: retrieve relevant checked-in runbook sections with matched terms and explainable overlap scores.
- `GET /api/actions/{action_id}/events`: view the persisted decision and execution history for an action.
- `POST /api/actions/{action_id}/decision`: submit `{"decision":"approve"}` or `{"decision":"reject"}`. Approval runs the simulated MCP tool and returns its result; a restart is verified through a simulated health check. Rejected actions are never run.
- `POST /api/sandbox/run`: run a bounded local telemetry scenario and create an incident containing the structured events and metrics.

Only explicitly approved, allowlisted simulated actions can run. No endpoint controls live infrastructure.

### Request safety and retries

POST requests may include an `Idempotency-Key` header (1–128 printable ASCII
characters). The API stores the request body hash and response for 24 hours;
repeating the same key and request replays the original response, while
reusing a key for a different request returns `409`. A concurrent duplicate
returns `409` while the first request is still in progress. Clients should
reuse a key only when retrying the exact same request.

Analysis and simulated MCP execution have configurable timeouts via
`ANALYSIS_TIMEOUT_SECONDS` (default 60) and
`MCP_EXECUTION_TIMEOUT_SECONDS` (default 20). Action state transitions are
recorded in PostgreSQL and can be inspected with the action events endpoint.

## Stage 3: Simulated MCP tools

With the backend dependencies installed, launch the MCP server locally:

```powershell
$env:PYTHONPATH = "backend"
python -m app.mcp_server
```

The server uses stdio transport for MCP clients and exposes `fetch_service_logs`, `check_db_status`, and `restart_resource`. They operate on in-memory sample scenarios and an allowlist only; they never inspect host services or modify live infrastructure.

Run the simulated tool checks with:

```powershell
$env:PYTHONPATH = "backend"
python -m unittest discover -s backend\tests -v
```

The test suite includes API/database integration tests, so start PostgreSQL with Docker Compose first. Ollama is mocked in the fast workflow tests; a local model is not needed to run the test suite.

## Stage 4: Local agent workflow

Start the Ollama app, or run `ollama serve` in a separate terminal. By default, the backend uses `gemma4:e4b`. If you do not have it, download it once:

```powershell
ollama pull gemma4:e4b
```

Keep the Ollama service running and use the `/api/incidents/{incident_id}/analyze` endpoint. You can override `OLLAMA_BASE_URL` and `OLLAMA_MODEL` in your local `.env`. Analysis requests structured JSON containing a diagnosis, cited runbook IDs, model-reported confidence, abstention status/reason, and an optional action. The API rejects citations that do not match retrieved evidence and validates any proposed tool and target against the simulated allowlist. Confidence below 0.60 and missing runbook evidence produce an abstention with no action. A valid proposal is still saved as pending approval; analysis never executes it.

Analysis also retrieves relevant passages from the checked-in runbooks in
`backend/app/runbooks/`. Retrieval is deterministic local token overlap, not
vector search. The analysis response returns source IDs, passages, citations,
confidence, and abstention details; the incident stores that state for later
display. Citation validation checks that IDs were actually retrieved, not
whether a citation semantically proves the diagnosis. Confidence is model
reported, not calibrated, and identifying conflicting evidence remains a
model judgment.

## Stage 5: Approval and simulated execution

The decision endpoint only accepts actions still in `PENDING_APPROVAL`. Rejecting marks the action without calling MCP. Approving transitions it to `APPROVED`, runs the tool through the MCP stdio server, then records `EXECUTED` or `FAILED`. A simulated restart is followed by a health-status check in the same MCP session; only a verified simulated restart marks the incident `RESOLVED`.

## Stages 6–7: Dashboard and verification

The React dashboard includes incident scenarios, saved incidents, diagnosis, proposed actions, approval/rejection controls, and simulated execution results. All backend tests include allowlist and approval-path checks. Run them after starting PostgreSQL:

```powershell
$env:PYTHONPATH = "backend"
python -m unittest discover -s backend\tests -v
```
