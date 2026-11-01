from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.tools import DATABASE_SHARDS, SERVICE_LOGS

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


class IncidentRead(BaseModel):
    incident_id: UUID
    title: str
    logs: str
    severity: Severity
    status: IncidentStatus
    diagnosis: str | None
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


class AnalysisRead(BaseModel):
    diagnosis: str
    action: ActionRead


class ActionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
