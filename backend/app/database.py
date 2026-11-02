import psycopg
from psycopg.rows import dict_row

from app.config import settings


def connect() -> psycopg.Connection:
    return psycopg.connect(settings.database_url, row_factory=dict_row)


def initialize_database() -> None:
    with connect() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id UUID PRIMARY KEY,
                title VARCHAR(200) NOT NULL,
                logs TEXT NOT NULL,
                severity VARCHAR(16) NOT NULL
                    CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
                status VARCHAR(32) NOT NULL
                    CHECK (status IN (
                        'OPEN', 'ANALYZING', 'AWAITING_APPROVAL',
                        'RESOLVED', 'REJECTED', 'FAILED'
                    )),
                diagnosis TEXT,
                telemetry JSONB,
                runbook_evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
                cited_evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                analysis_confidence DOUBLE PRECISION,
                analysis_abstained BOOLEAN NOT NULL DEFAULT FALSE,
                abstention_reason TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        connection.execute(
            "ALTER TABLE incidents ADD COLUMN IF NOT EXISTS telemetry JSONB"
        )
        connection.execute(
            """
            ALTER TABLE incidents
            ADD COLUMN IF NOT EXISTS runbook_evidence JSONB
            NOT NULL DEFAULT '[]'::jsonb
            """
        )
        connection.execute(
            """
            ALTER TABLE incidents
            ADD COLUMN IF NOT EXISTS cited_evidence_ids JSONB
            NOT NULL DEFAULT '[]'::jsonb
            """
        )
        connection.execute(
            """
            ALTER TABLE incidents
            ADD COLUMN IF NOT EXISTS analysis_confidence DOUBLE PRECISION
            """
        )
        connection.execute(
            """
            ALTER TABLE incidents
            ADD COLUMN IF NOT EXISTS analysis_abstained BOOLEAN
            NOT NULL DEFAULT FALSE
            """
        )
        connection.execute(
            """
            ALTER TABLE incidents
            ADD COLUMN IF NOT EXISTS abstention_reason TEXT
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS remediation_actions (
                action_id UUID PRIMARY KEY,
                incident_id UUID NOT NULL REFERENCES incidents(incident_id)
                    ON DELETE CASCADE,
                tool_name VARCHAR(80) NOT NULL
                    CHECK (tool_name IN (
                        'fetch_service_logs',
                        'check_db_status',
                        'restart_resource'
                    )),
                arguments JSONB NOT NULL DEFAULT '{}'::jsonb,
                description VARCHAR(500) NOT NULL,
                status VARCHAR(32) NOT NULL
                    CHECK (status IN (
                        'PENDING_APPROVAL', 'APPROVED', 'REJECTED',
                        'EXECUTED', 'FAILED'
                    )),
                result TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS action_events (
                event_id UUID PRIMARY KEY,
                action_id UUID NOT NULL REFERENCES remediation_actions(action_id)
                    ON DELETE CASCADE,
                from_status VARCHAR(32),
                to_status VARCHAR(32) NOT NULL,
                event_type VARCHAR(64) NOT NULL,
                details JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS action_events_action_created_idx
            ON action_events (action_id, created_at)
            """
        )
        connection.execute(
            """
            INSERT INTO action_events (
                event_id, action_id, from_status, to_status,
                event_type, details
            )
            SELECT
                gen_random_uuid(), action.action_id, NULL, action.status,
                'LEGACY_STATE',
                '{"note":"State recorded before event history was enabled"}'::jsonb
            FROM remediation_actions AS action
            WHERE NOT EXISTS (
                SELECT 1 FROM action_events AS event
                WHERE event.action_id = action.action_id
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency_records (
                idempotency_key VARCHAR(128) PRIMARY KEY,
                operation VARCHAR(256) NOT NULL,
                request_hash VARCHAR(64) NOT NULL,
                response_status INTEGER,
                response_body JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idempotency_records_created_idx
            ON idempotency_records (created_at)
            """
        )
