from uuid import UUID, uuid4

import psycopg

from psycopg.types.json import Jsonb

from app.database import connect
from app.schemas import (
    ActionDecision,
    ActionCreate,
    ActionRead,
    ActionStatus,
    ActionEventRead,
    IncidentCreate,
    IncidentRead,
    IncidentStatus,
    RunbookEvidence,
)


class IdempotencyConflict(Exception):
    pass


def reserve_idempotency(
    idempotency_key: str,
    operation: str,
    request_hash: str,
) -> tuple[str, int | None, object | None]:
    with connect() as connection:
        connection.execute(
            """
            DELETE FROM idempotency_records
            WHERE created_at < now() - interval '24 hours'
            """
        )
        inserted = connection.execute(
            """
            INSERT INTO idempotency_records (
                idempotency_key, operation, request_hash
            )
            VALUES (%s, %s, %s)
            ON CONFLICT (idempotency_key) DO NOTHING
            RETURNING idempotency_key
            """,
            (idempotency_key, operation, request_hash),
        ).fetchone()
        if inserted is not None:
            return "new", None, None

        row = connection.execute(
            """
            SELECT operation, request_hash, response_status, response_body
            FROM idempotency_records
            WHERE idempotency_key = %s
            FOR UPDATE
            """,
            (idempotency_key,),
        ).fetchone()
        if row is None:
            raise RuntimeError("Idempotency record disappeared during lookup")
        if row["operation"] != operation or row["request_hash"] != request_hash:
            raise IdempotencyConflict(
                "Idempotency-Key was already used for a different request"
            )
        if row["response_status"] is None:
            return "in_progress", None, None
        return "replay", row["response_status"], row["response_body"]


def complete_idempotency(
    idempotency_key: str,
    status_code: int,
    response_body: object,
) -> None:
    with connect() as connection:
        updated = connection.execute(
            """
            UPDATE idempotency_records
            SET response_status = %s, response_body = %s
            WHERE idempotency_key = %s AND response_status IS NULL
            """,
            (status_code, Jsonb(response_body), idempotency_key),
        )
        if updated.rowcount != 1:
            raise RuntimeError("Unable to persist idempotent response")


def release_idempotency(idempotency_key: str) -> None:
    with connect() as connection:
        connection.execute(
            "DELETE FROM idempotency_records WHERE idempotency_key = %s",
            (idempotency_key,),
        )


def _record_action_event(
    connection: psycopg.Connection,
    action_id: UUID,
    from_status: ActionStatus | None,
    to_status: ActionStatus,
    event_type: str,
    details: dict[str, str] | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO action_events (
            event_id, action_id, from_status, to_status, event_type, details
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            uuid4(),
            action_id,
            from_status.value if from_status else None,
            to_status.value,
            event_type,
            Jsonb(details or {}),
        ),
    )


def create_incident(payload: IncidentCreate) -> IncidentRead:
    incident_id = uuid4()
    with connect() as connection:
        row = connection.execute(
            """
            INSERT INTO incidents (
                incident_id, title, logs, severity, status, telemetry
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                incident_id,
                payload.title,
                payload.logs,
                payload.severity.value,
                IncidentStatus.OPEN.value,
                Jsonb(payload.telemetry.model_dump(mode="json"))
                if payload.telemetry
                else None,
            ),
        ).fetchone()
    return IncidentRead.model_validate(row)


def list_incidents() -> list[IncidentRead]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM incidents ORDER BY created_at DESC"
        ).fetchall()
    return [IncidentRead.model_validate(row) for row in rows]


def get_incident(incident_id: UUID) -> IncidentRead | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM incidents WHERE incident_id = %s",
            (incident_id,),
        ).fetchone()
    return IncidentRead.model_validate(row) if row else None


def create_action(
    incident_id: UUID, payload: ActionCreate
) -> ActionRead | None:
    action_id = uuid4()
    with connect() as connection:
        incident = connection.execute(
            "SELECT incident_id FROM incidents WHERE incident_id = %s FOR UPDATE",
            (incident_id,),
        ).fetchone()
        if incident is None:
            return None

        row = connection.execute(
            """
            INSERT INTO remediation_actions (
                action_id, incident_id, tool_name, arguments,
                description, status
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                action_id,
                incident_id,
                payload.tool_name,
                Jsonb(payload.arguments),
                payload.description,
                ActionStatus.PENDING_APPROVAL.value,
            ),
        ).fetchone()
        connection.execute(
            """
            UPDATE incidents
            SET status = %s, updated_at = now()
            WHERE incident_id = %s
            """,
            (IncidentStatus.AWAITING_APPROVAL.value, incident_id),
        )
        _record_action_event(
            connection,
            action_id,
            None,
            ActionStatus.PENDING_APPROVAL,
            "ACTION_CREATED",
            {"source": "operator"},
        )
    return ActionRead.model_validate(row)


def save_analysis_result(
    incident_id: UUID,
    diagnosis: str,
    payload: ActionCreate | None,
    runbook_evidence: list[RunbookEvidence],
    cited_evidence_ids: list[str],
    confidence: float,
    abstained: bool,
    abstention_reason: str | None,
) -> tuple[bool, ActionRead | None]:
    with connect() as connection:
        incident = connection.execute(
            "SELECT incident_id FROM incidents WHERE incident_id = %s FOR UPDATE",
            (incident_id,),
        ).fetchone()
        if incident is None:
            return False, None

        action = None
        incident_status = IncidentStatus.OPEN
        if payload is not None:
            row = connection.execute(
                """
                INSERT INTO remediation_actions (
                    action_id, incident_id, tool_name, arguments,
                    description, status
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    uuid4(),
                    incident_id,
                    payload.tool_name,
                    Jsonb(payload.arguments),
                    payload.description,
                    ActionStatus.PENDING_APPROVAL.value,
                ),
            ).fetchone()
            action = ActionRead.model_validate(row)
            incident_status = IncidentStatus.AWAITING_APPROVAL
            _record_action_event(
                connection,
                action.action_id,
                None,
                ActionStatus.PENDING_APPROVAL,
                "ACTION_PROPOSED",
                {"source": "analysis"},
            )

        connection.execute(
            """
            UPDATE incidents
            SET diagnosis = %s, runbook_evidence = %s,
                cited_evidence_ids = %s, analysis_confidence = %s,
                analysis_abstained = %s, abstention_reason = %s,
                status = %s, updated_at = now()
            WHERE incident_id = %s
            """,
            (
                diagnosis,
                Jsonb(
                    [
                        evidence.model_dump(mode="json")
                        for evidence in runbook_evidence
                    ]
                ),
                Jsonb(cited_evidence_ids),
                confidence,
                abstained,
                abstention_reason,
                incident_status.value,
                incident_id,
            ),
        )
    return True, action


def list_actions(incident_id: UUID) -> list[ActionRead] | None:
    with connect() as connection:
        incident = connection.execute(
            "SELECT incident_id FROM incidents WHERE incident_id = %s",
            (incident_id,),
        ).fetchone()
        if incident is None:
            return None
        rows = connection.execute(
            """
            SELECT * FROM remediation_actions
            WHERE incident_id = %s
            ORDER BY created_at
            """,
            (incident_id,),
        ).fetchall()
    return [ActionRead.model_validate(row) for row in rows]


def list_action_events(action_id: UUID) -> list[ActionEventRead] | None:
    with connect() as connection:
        action = connection.execute(
            "SELECT action_id FROM remediation_actions WHERE action_id = %s",
            (action_id,),
        ).fetchone()
        if action is None:
            return None
        rows = connection.execute(
            """
            SELECT * FROM action_events
            WHERE action_id = %s
            ORDER BY created_at, event_id
            """,
            (action_id,),
        ).fetchall()
    return [ActionEventRead.model_validate(row) for row in rows]


class ActionDecisionConflict(Exception):
    pass


def transition_pending_action(
    action_id: UUID,
    decision: ActionDecision,
) -> ActionRead | None:
    new_status = (
        ActionStatus.APPROVED
        if decision.decision == "approve"
        else ActionStatus.REJECTED
    )
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM remediation_actions WHERE action_id = %s FOR UPDATE",
            (action_id,),
        ).fetchone()
        if row is None:
            return None
        if row["status"] != ActionStatus.PENDING_APPROVAL.value:
            raise ActionDecisionConflict(
                f"Action cannot be decided from {row['status']} status"
            )

        updated = connection.execute(
            """
            UPDATE remediation_actions
            SET status = %s, updated_at = now()
            WHERE action_id = %s
            RETURNING *
            """,
            (new_status.value, action_id),
        ).fetchone()
        _record_action_event(
            connection,
            action_id,
            ActionStatus.PENDING_APPROVAL,
            new_status,
            "ACTION_DECISION",
            {"decision": decision.decision},
        )
        if new_status == ActionStatus.REJECTED:
            connection.execute(
                """
                UPDATE incidents
                SET status = %s, updated_at = now()
                WHERE incident_id = %s
                """,
                (IncidentStatus.REJECTED.value, row["incident_id"]),
            )
    return ActionRead.model_validate(updated)


def finish_approved_action(
    action_id: UUID,
    succeeded: bool,
    result: str,
) -> ActionRead | None:
    action_status = (
        ActionStatus.EXECUTED if succeeded else ActionStatus.FAILED
    )
    with connect() as connection:
        row = connection.execute(
            """
            SELECT incident_id FROM remediation_actions
            WHERE action_id = %s AND status = %s FOR UPDATE
            """,
            (action_id, ActionStatus.APPROVED.value),
        ).fetchone()
        if row is None:
            return None

        updated = connection.execute(
            """
            UPDATE remediation_actions
            SET status = %s, result = %s, updated_at = now()
            WHERE action_id = %s
            RETURNING *
            """,
            (action_status.value, result, action_id),
        ).fetchone()
        _record_action_event(
            connection,
            action_id,
            ActionStatus.APPROVED,
            action_status,
            "ACTION_EXECUTION_SUCCEEDED"
            if succeeded
            else "ACTION_EXECUTION_FAILED",
        )

        if succeeded:
            action = updated
            incident_status = (
                IncidentStatus.RESOLVED
                if action["tool_name"] == "restart_resource"
                else IncidentStatus.OPEN
            )
        else:
            incident_status = IncidentStatus.FAILED
        connection.execute(
            """
            UPDATE incidents
            SET status = %s, updated_at = now()
            WHERE incident_id = %s
            """,
            (incident_status.value, row["incident_id"]),
        )
    return ActionRead.model_validate(updated)
