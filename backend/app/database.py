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
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
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
