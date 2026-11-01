from uuid import UUID, uuid4

from psycopg.types.json import Jsonb

from app.database import connect
from app.schemas import (
    ActionDecision,
    ActionCreate,
    ActionRead,
    ActionStatus,
    IncidentCreate,
    IncidentRead,
    IncidentStatus,
)


def create_incident(payload: IncidentCreate) -> IncidentRead:
    incident_id = uuid4()
    with connect() as connection:
        row = connection.execute(
            """
            INSERT INTO incidents (
                incident_id, title, logs, severity, status
            )
            VALUES (%s, %s, %s, %s, %s)
            RETURNING *
            """,
            (
                incident_id,
                payload.title,
                payload.logs,
                payload.severity.value,
                IncidentStatus.OPEN.value,
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
    return ActionRead.model_validate(row)


def save_analysis_and_action(
    incident_id: UUID,
    diagnosis: str,
    payload: ActionCreate,
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
            SET diagnosis = %s, status = %s, updated_at = now()
            WHERE incident_id = %s
            """,
            (
                diagnosis,
                IncidentStatus.AWAITING_APPROVAL.value,
                incident_id,
            ),
        )
    return ActionRead.model_validate(row)


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
