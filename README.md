# SRE Agent

A staged incident-response agent using FastAPI, React/TypeScript, LangGraph, the MCP Python SDK, PostgreSQL, and local Ollama inference.

The working folder is still named `ops-swarm-rebuild`; the app and project branding is now **SRE Agent**.

The project is being built in stages. All operations remain simulated; no tool connects to or modifies real infrastructure.

**Progress:** Stages 1–7 are implemented. The dashboard, real local Ollama analysis, explicit approval/rejection, and simulated MCP execution have been exercised end-to-end.

See [PROJECT_STAGES.md](./PROJECT_STAGES.md) for the detailed build record.

## Run the application

### Start PostgreSQL

From this directory, start the local database:

```powershell
docker compose up -d db
```

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

Open the Vite URL shown in the terminal (normally `http://localhost:5173`). The dashboard checks the backend through Vite's local API proxy.

## Implemented stages

1. Foundation: API/UI shells and local database service.
2. Incident and remediation data models, plus PostgreSQL persistence.
3. Simulated operations exposed as MCP tools.
4. LangGraph diagnosis and remediation proposal workflow (local Ollama).
5. Human approval/rejection and simulated execution verification.
6. Dashboard scenarios and operator console.
7. Safety policy tests, integration tests, and operational documentation.

## API

- `POST /api/incidents`: create an incident with a title, severity, and logs.
- `GET /api/incidents`: list incidents, newest first.
- `GET /api/incidents/{incident_id}`: retrieve one incident.
- `POST /api/incidents/{incident_id}/actions`: record an allowlisted action as `PENDING_APPROVAL`.
- `GET /api/incidents/{incident_id}/actions`: list the incident's proposed actions.
- `POST /api/incidents/{incident_id}/analyze`: analyze logs with the configured Ollama model and save a validated action as `PENDING_APPROVAL`.
- `POST /api/actions/{action_id}/decision`: submit `{"decision":"approve"}` or `{"decision":"reject"}`. Approval runs the simulated MCP tool and returns its result; a restart is verified through a simulated health check. Rejected actions are never run.

Only explicitly approved, allowlisted simulated actions can run. No endpoint controls live infrastructure.

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

Keep the Ollama service running and use the `/api/incidents/{incident_id}/analyze` endpoint. You can override `OLLAMA_BASE_URL` and `OLLAMA_MODEL` in your local `.env`. The graph diagnoses the logs, requests one JSON action proposal, validates the tool and target against the simulated allowlist, and saves it pending approval. This stage does not execute the proposal.

## Stage 5: Approval and simulated execution

The decision endpoint only accepts actions still in `PENDING_APPROVAL`. Rejecting marks the action without calling MCP. Approving transitions it to `APPROVED`, runs the tool through the MCP stdio server, then records `EXECUTED` or `FAILED`. A simulated restart is followed by a health-status check in the same MCP session; only a verified simulated restart marks the incident `RESOLVED`.

## Stages 6–7: Dashboard and verification

The React dashboard includes incident scenarios, saved incidents, diagnosis, proposed actions, approval/rejection controls, and simulated execution results. All backend tests include allowlist and approval-path checks. Run them after starting PostgreSQL:

```powershell
$env:PYTHONPATH = "backend"
python -m unittest discover -s backend\tests -v
```
