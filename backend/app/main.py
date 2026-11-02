import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator
from uuid import UUID

import httpx
from ollama import ResponseError
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from starlette.responses import JSONResponse, Response

from app.config import settings
from app.database import initialize_database
from app.mcp_client import MCPExecutionError, execute_action
from app.repository import (
    ActionDecisionConflict,
    IdempotencyConflict,
    complete_idempotency,
    create_action,
    create_incident,
    finish_approved_action,
    get_incident,
    list_actions,
    list_action_events,
    list_incidents,
    release_idempotency,
    reserve_idempotency,
    save_analysis_result,
    transition_pending_action,
)
from app.schemas import (
    ActionDecision,
    ActionCreate,
    ActionEventRead,
    ActionRead,
    AnalysisRead,
    IncidentCreate,
    IncidentRead,
    RunbookEvidence,
    SandboxRunRead,
    SandboxRunRequest,
    SandboxScenario,
    TelemetrySnapshot,
)
from app.runbooks import retrieve_runbooks
from app.workflow import analyze_incident


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialize_database()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.middleware("http")
async def idempotent_post_requests(
    request: Request,
    call_next: Any,
) -> Response:
    idempotency_key = request.headers.get("Idempotency-Key")
    if request.method != "POST" or idempotency_key is None:
        return await call_next(request)
    if (
        not 1 <= len(idempotency_key) <= 128
        or not all(32 <= ord(character) <= 126 for character in idempotency_key)
    ):
        return JSONResponse(
            status_code=400,
            content={"detail": "Idempotency-Key must be 1-128 printable ASCII characters"},
        )

    body = await request.body()
    request_hash = hashlib.sha256(body).hexdigest()
    operation = f"{request.method}:{request.url.path}"
    try:
        state, status_code, cached_body = reserve_idempotency(
            idempotency_key,
            operation,
            request_hash,
        )
    except IdempotencyConflict as error:
        return JSONResponse(status_code=409, content={"detail": str(error)})

    if state == "replay":
        if status_code is None:
            raise RuntimeError("Completed idempotency record has no HTTP status")
        return JSONResponse(
            status_code=status_code,
            content=cached_body,
            headers={"Idempotency-Replayed": "true"},
        )
    if state == "in_progress":
        return JSONResponse(
            status_code=409,
            content={"detail": "A request with this Idempotency-Key is in progress"},
        )

    request_body: bytes | None = body

    async def replay_body():
        nonlocal request_body
        if request_body is None:
            return {"type": "http.disconnect"}
        current_body = request_body
        request_body = None
        return {
            "type": "http.request",
            "body": current_body,
            "more_body": False,
        }

    try:
        response = await call_next(
            Request(request.scope, receive=replay_body)
        )
        response_content = b"".join(
            [chunk async for chunk in response.body_iterator]
        )
        response_payload = json.loads(response_content)
        complete_idempotency(
            idempotency_key,
            response.status_code,
            response_payload,
        )
        return Response(
            content=response_content,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
    except Exception:
        release_idempotency(idempotency_key)
        raise


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
    }


async def fetch_sandbox_telemetry(
    request: SandboxRunRequest,
) -> TelemetrySnapshot:
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{settings.demo_service_url.rstrip('/')}/simulate",
                json=request.model_dump(mode="json"),
            )
            response.raise_for_status()
            return TelemetrySnapshot.model_validate(response.json())
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.TimeoutException) as error:
        raise HTTPException(
            status_code=503,
            detail=(
                "The local telemetry sandbox is unavailable at "
                f"{settings.demo_service_url}. Start it with "
                "'python -m uvicorn app.demo_service:app --app-dir backend "
                "--port 8100'."
            ),
        ) from error
    except httpx.HTTPStatusError as error:
        raise HTTPException(
            status_code=502,
            detail=(
                "The local telemetry sandbox returned "
                f"HTTP {error.response.status_code}."
            ),
        ) from error
    except (ValueError, ValidationError) as error:
        raise HTTPException(
            status_code=502,
            detail="The local telemetry sandbox returned an invalid response.",
        ) from error


@app.post(
    "/api/sandbox/run",
    response_model=SandboxRunRead,
    status_code=201,
)
async def run_sandbox_scenario(
    request: SandboxRunRequest,
) -> SandboxRunRead:
    telemetry = await fetch_sandbox_telemetry(request)
    title_by_scenario = {
        SandboxScenario.HEALTHY: "Sandbox healthy baseline",
        SandboxScenario.DATABASE_FAILURE: "Sandbox database connection failure",
        SandboxScenario.HIGH_LATENCY: "Sandbox high latency",
    }
    severity_by_scenario = {
        SandboxScenario.HEALTHY: "LOW",
        SandboxScenario.DATABASE_FAILURE: "CRITICAL",
        SandboxScenario.HIGH_LATENCY: "HIGH",
    }
    logs = "\n".join(
        [
            f"METRICS {telemetry.metrics.model_dump_json()}",
            *[event.model_dump_json() for event in telemetry.events],
        ]
    )
    incident = create_incident(
        IncidentCreate(
            title=title_by_scenario[telemetry.scenario],
            logs=logs,
            severity=severity_by_scenario[telemetry.scenario],
            telemetry=telemetry,
        )
    )
    return SandboxRunRead(incident=incident, telemetry=telemetry)


@app.post(
    "/api/incidents/{incident_id}/analyze",
    response_model=AnalysisRead,
)
async def analyze_incident_endpoint(incident_id: UUID) -> AnalysisRead:
    incident = get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    try:
        async with asyncio.timeout(settings.analysis_timeout_seconds):
            analysis = await analyze_incident(
                incident_id=incident_id,
                logs=incident.logs,
            )
    except TimeoutError as error:
        raise HTTPException(
            status_code=504,
            detail=(
                "Incident analysis exceeded the configured "
                f"{settings.analysis_timeout_seconds:g}-second timeout."
            ),
        ) from error
    except (httpx.ConnectError, httpx.ConnectTimeout) as error:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Cannot connect to Ollama at {settings.ollama_base_url}. "
                "Start the Ollama service and ensure the configured model "
                f"'{settings.ollama_model}' is available."
            ),
        ) from error
    except ResponseError as error:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Ollama could not run model '{settings.ollama_model}': "
                f"{error}. Pull the model with "
                f"'ollama pull {settings.ollama_model}'."
            ),
        ) from error
    except (ValidationError, ValueError) as error:
        raise HTTPException(
            status_code=502,
            detail="Ollama returned an invalid or unsupported incident analysis.",
        ) from error
    found, action = save_analysis_result(
        incident_id=incident_id,
        diagnosis=analysis.diagnosis,
        payload=analysis.proposal,
        runbook_evidence=analysis.runbook_evidence,
        cited_evidence_ids=analysis.cited_evidence_ids,
        confidence=analysis.confidence,
        abstained=analysis.abstained,
        abstention_reason=analysis.abstention_reason,
    )
    if not found:
        raise HTTPException(status_code=404, detail="Incident not found")
    return AnalysisRead(
        diagnosis=analysis.diagnosis,
        action=action,
        runbook_evidence=analysis.runbook_evidence,
        cited_evidence_ids=analysis.cited_evidence_ids,
        confidence=analysis.confidence,
        abstained=analysis.abstained,
        abstention_reason=analysis.abstention_reason,
    )


@app.get("/api/runbooks/search", response_model=list[RunbookEvidence])
def search_runbooks(q: str) -> list[RunbookEvidence]:
    return retrieve_runbooks(q)


@app.post("/api/incidents", response_model=IncidentRead, status_code=201)
def post_incident(payload: IncidentCreate) -> IncidentRead:
    return create_incident(payload)


@app.get("/api/incidents", response_model=list[IncidentRead])
def get_incidents() -> list[IncidentRead]:
    return list_incidents()


@app.get("/api/incidents/{incident_id}", response_model=IncidentRead)
def get_incident_by_id(incident_id: UUID) -> IncidentRead:
    incident = get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


@app.post(
    "/api/incidents/{incident_id}/actions",
    response_model=ActionRead,
    status_code=201,
)
def post_action(incident_id: UUID, payload: ActionCreate) -> ActionRead:
    action = create_action(incident_id, payload)
    if action is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return action


@app.get(
    "/api/incidents/{incident_id}/actions",
    response_model=list[ActionRead],
)
def get_actions(incident_id: UUID) -> list[ActionRead]:
    actions = list_actions(incident_id)
    if actions is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return actions


@app.get(
    "/api/actions/{action_id}/events",
    response_model=list[ActionEventRead],
)
def get_action_events(action_id: UUID) -> list[ActionEventRead]:
    events = list_action_events(action_id)
    if events is None:
        raise HTTPException(status_code=404, detail="Action not found")
    return events


@app.post(
    "/api/actions/{action_id}/decision",
    response_model=ActionRead,
)
async def decide_action(
    action_id: UUID,
    decision: ActionDecision,
) -> ActionRead:
    try:
        action = transition_pending_action(action_id, decision)
    except ActionDecisionConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    if decision.decision == "reject":
        return action

    try:
        async with asyncio.timeout(settings.mcp_execution_timeout_seconds):
            result = await execute_action(action.tool_name, action.arguments)
    except (MCPExecutionError, OSError, TimeoutError) as error:
        finish_approved_action(
            action_id,
            succeeded=False,
            result=f"Simulated MCP execution failed: {error}",
        )
        status_code = 504 if isinstance(error, TimeoutError) else 502
        raise HTTPException(
            status_code=status_code,
            detail=(
                "Simulated MCP execution timed out."
                if isinstance(error, TimeoutError)
                else f"Simulated MCP execution failed: {error}"
            ),
        ) from error

    completed = finish_approved_action(
        action_id,
        succeeded=True,
        result=result,
    )
    if completed is None:
        raise HTTPException(
            status_code=409,
            detail="Approved action could not be finalized",
        )
    return completed
