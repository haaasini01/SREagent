from contextlib import asynccontextmanager
from typing import AsyncIterator
from uuid import UUID

import httpx
from ollama import ResponseError
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import initialize_database
from app.mcp_client import MCPExecutionError, execute_action
from app.repository import (
    ActionDecisionConflict,
    create_action,
    create_incident,
    finish_approved_action,
    get_incident,
    list_actions,
    list_incidents,
    save_analysis_and_action,
    transition_pending_action,
)
from app.schemas import (
    ActionDecision,
    ActionCreate,
    ActionRead,
    AnalysisRead,
    IncidentCreate,
    IncidentRead,
)
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


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@app.post(
    "/api/incidents/{incident_id}/analyze",
    response_model=AnalysisRead,
)
async def analyze_incident_endpoint(incident_id: UUID) -> AnalysisRead:
    incident = get_incident(incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    try:
        diagnosis, proposal = await analyze_incident(
            incident_id=incident_id,
            logs=incident.logs,
        )
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
    action = save_analysis_and_action(
        incident_id=incident_id,
        diagnosis=diagnosis,
        payload=proposal,
    )
    if action is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return AnalysisRead(diagnosis=diagnosis, action=action)


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
        result = await execute_action(action.tool_name, action.arguments)
    except (MCPExecutionError, OSError) as error:
        finish_approved_action(
            action_id,
            succeeded=False,
            result=f"Simulated MCP execution failed: {error}",
        )
        raise HTTPException(
            status_code=502,
            detail=f"Simulated MCP execution failed: {error}",
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
