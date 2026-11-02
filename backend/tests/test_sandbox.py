import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.database import connect
from app.demo_service import app as sandbox_app
from app.main import app as api_app
from app.schemas import (
    SandboxScenario,
    TelemetryEvent,
    TelemetryMetrics,
    TelemetrySnapshot,
)


class TelemetrySandboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(sandbox_app)

    def test_database_failure_generates_structured_errors(self) -> None:
        response = self.client.post(
            "/simulate",
            json={"scenario": "database_failure", "request_count": 3},
        )

        self.assertEqual(response.status_code, 200, response.text)
        snapshot = response.json()
        self.assertEqual(snapshot["metrics"]["request_count"], 3)
        self.assertEqual(snapshot["metrics"]["error_count"], 3)
        self.assertEqual(snapshot["metrics"]["error_rate"], 1)
        self.assertTrue(
            all(
                event["error"] == "connection_refused: DB_SHARD_04"
                for event in snapshot["events"]
            )
        )

    def test_high_latency_scenario_records_observed_latency(self) -> None:
        response = self.client.post(
            "/simulate",
            json={"scenario": "high_latency", "request_count": 1},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertGreaterEqual(
            response.json()["metrics"]["p95_latency_ms"],
            100,
        )

    def test_request_count_is_bounded_and_scenario_is_allowlisted(self) -> None:
        too_many = self.client.post(
            "/simulate",
            json={"scenario": "healthy", "request_count": 11},
        )
        unknown = self.client.post(
            "/simulate",
            json={"scenario": "production", "request_count": 1},
        )

        self.assertEqual(too_many.status_code, 422)
        self.assertEqual(unknown.status_code, 422)


class TelemetryIngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(api_app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.incident_id: str | None = None
        self.addCleanup(self._delete_test_incident)

    def _delete_test_incident(self) -> None:
        if self.incident_id:
            with connect() as connection:
                connection.execute(
                    "DELETE FROM incidents WHERE incident_id = %s",
                    (self.incident_id,),
                )

    def test_sandbox_run_persists_incident_and_telemetry(self) -> None:
        snapshot = TelemetrySnapshot(
            scenario=SandboxScenario.DATABASE_FAILURE,
            captured_at="2026-11-02T10:00:00Z",
            events=[
                TelemetryEvent(
                    event_id=7001,
                    timestamp="2026-11-02T10:00:00Z",
                    service="checkout-api",
                    scenario=SandboxScenario.DATABASE_FAILURE,
                    endpoint="/checkout",
                    status_code=503,
                    latency_ms=3.5,
                    error="connection_refused: DB_SHARD_04",
                )
            ],
            metrics=TelemetryMetrics(
                request_count=1,
                error_count=1,
                error_rate=1,
                avg_latency_ms=3.5,
                p95_latency_ms=3.5,
            ),
        )
        with patch(
            "app.main.fetch_sandbox_telemetry",
            new=AsyncMock(return_value=snapshot),
        ):
            response = self.client.post(
                "/api/sandbox/run",
                json={
                    "scenario": "database_failure",
                    "request_count": 1,
                },
            )

        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.incident_id = body["incident"]["incident_id"]
        self.assertEqual(
            body["incident"]["title"],
            "Sandbox database connection failure",
        )
        self.assertEqual(
            body["incident"]["telemetry"]["metrics"]["error_count"],
            1,
        )
        stored = self.client.get(
            f"/api/incidents/{self.incident_id}"
        ).json()
        self.assertEqual(stored["telemetry"]["events"][0]["status_code"], 503)
        self.assertIn("connection_refused", stored["logs"])


if __name__ == "__main__":
    unittest.main()
