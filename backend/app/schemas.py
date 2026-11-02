from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.tools import DATABASE_SHARDS, SERVICE_LOGS


class SandboxScenario(StrEnum):
    HEALTHY = "healthy"
    DATABASE_FAILURE = "database_failure"
    HIGH_LATENCY = "high_latency"


class TelemetryEvent(BaseModel):
    event_id: int
    timestamp: datetime
    service: str
    scenario: SandboxScenario
    endpoint: str
    status_code: int
    latency_ms: float = Field(ge=0)
    error: str | None = None


class TelemetryMetrics(BaseModel):
    request_count: int = Field(ge=0)
    error_count: int = Field(ge=0)
    error_rate: float = Field(ge=0, le=1)
    avg_latency_ms: float = Field(ge=0)
    p95_latency_ms: float = Field(ge=0)


class TelemetrySnapshot(BaseModel):
    scenario: SandboxScenario
    captured_at: datetime
    events: list[TelemetryEvent]
    metrics: TelemetryMetrics


class RunbookEvidence(BaseModel):
    source_id: str
    title: str
    source_file: str
    content: str
    score: int = Field(ge=1)
    matched_terms: list[str]


class SandboxRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: SandboxScenario
    request_count: int = Field(default=3, ge=1, le=10)


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(StrEnum):
    OPEN = "OPEN"
    ANALYZING = "ANALYZING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class ActionStatus(StrEnum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


class IncidentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=200)
    logs: str = Field(min_length=1, max_length=50_000)
    severity: Severity
    telemetry: TelemetrySnapshot | None = None


class IncidentRead(BaseModel):
    incident_id: UUID
    title: str
    logs: str
    severity: Severity
    status: IncidentStatus
    diagnosis: str | None
    telemetry: TelemetrySnapshot | None = None
    runbook_evidence: list[RunbookEvidence] = Field(default_factory=list)
    cited_evidence_ids: list[str] = Field(default_factory=list)
    analysis_confidence: float | None = Field(default=None, ge=0, le=1)
    analysis_abstained: bool = False
    abstention_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class ActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: Literal[
        "fetch_service_logs",
        "check_db_status",
        "restart_resource",
    ]
    arguments: dict[str, str] = Field(default_factory=dict)
    description: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_tool_arguments(self) -> "ActionCreate":
        required_argument = {
            "fetch_service_logs": "service_name",
            "check_db_status": "shard_id",
            "restart_resource": "resource_id",
        }[self.tool_name]
        if set(self.arguments) != {required_argument}:
            raise ValueError(
                f"{self.tool_name} requires only the "
                f"{required_argument!r} argument"
            )

        allowed_values = (
            SERVICE_LOGS
            if self.tool_name == "fetch_service_logs"
            else DATABASE_SHARDS
        )
        if self.arguments[required_argument] not in allowed_values:
            raise ValueError(
                f"Unknown simulated target: "
                f"{self.arguments[required_argument]}"
            )
        return self


class ActionRead(BaseModel):
    action_id: UUID
    incident_id: UUID
    tool_name: str
    arguments: dict[str, str]
    description: str
    status: ActionStatus
    result: str | None
    created_at: datetime
    updated_at: datetime


class ActionEventRead(BaseModel):
    event_id: UUID
    action_id: UUID
    from_status: ActionStatus | None
    to_status: ActionStatus
    event_type: str
    details: dict[str, str] = Field(default_factory=dict)
    created_at: datetime


class AnalysisRead(BaseModel):
    diagnosis: str
    action: ActionRead | None
    runbook_evidence: list[RunbookEvidence]
    cited_evidence_ids: list[str]
    confidence: float = Field(ge=0, le=1)
    abstained: bool
    abstention_reason: str | None


class SandboxRunRead(BaseModel):
    incident: IncidentRead
    telemetry: TelemetrySnapshot


class ActionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
