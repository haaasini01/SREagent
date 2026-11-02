import asyncio
import hashlib
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.database import connect
from app.main import app
from app.repository import release_idempotency, reserve_idempotency
from app.schemas import (
    ActionCreate,
    RunbookEvidence,
    SandboxScenario,
    TelemetryEvent,
    TelemetryMetrics,
    TelemetrySnapshot,
)
from app.workflow import WorkflowAnalysis


class IncidentApiIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.incident_ids: list[str] = []
        self.addCleanup(self._delete_test_incidents)

    def _create_incident(self, title: str) -> str:
        response = self.client.post(
            "/api/incidents",
            json={
                "title": title,
                "logs": "Simulated DB_SHARD_04 failure",
                "severity": "CRITICAL",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        incident_id = response.json()["incident_id"]
        self.incident_ids.append(incident_id)
        return incident_id

    def _create_restart_action(self, incident_id: str) -> dict[str, str]:
        response = self.client.post(
            f"/api/incidents/{incident_id}/actions",
            json={
                "tool_name": "restart_resource",
                "arguments": {"resource_id": "DB_SHARD_04"},
                "description": "Restart the simulated database shard",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def _delete_test_incidents(self) -> None:
        if self.incident_ids:
            with connect() as connection:
                connection.execute(
                    "DELETE FROM incidents WHERE incident_id = ANY(%s)",
                    (self.incident_ids,),
                )

    def test_runbook_search_returns_inspectable_source(self) -> None:
        response = self.client.get(
            "/api/runbooks/search",
            params={"q": "connection refused DB_SHARD_04"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        evidence = response.json()
        self.assertEqual(evidence[0]["source_id"], "DB-001")
        self.assertEqual(evidence[0]["source_file"], "database.md")
        self.assertIn("connection", evidence[0]["matched_terms"])

    def test_sandbox_idempotency_replays_result_and_rejects_changed_payload(self) -> None:
        snapshot = TelemetrySnapshot(
            scenario=SandboxScenario.HEALTHY,
            captured_at="2026-11-02T10:00:00Z",
            events=[
                TelemetryEvent(
                    event_id=7002,
                    timestamp="2026-11-02T10:00:00Z",
                    service="checkout-api",
                    scenario=SandboxScenario.HEALTHY,
                    endpoint="/checkout",
                    status_code=200,
                    latency_ms=10,
                )
            ],
            metrics=TelemetryMetrics(
                request_count=1,
                error_count=0,
                error_rate=0,
                avg_latency_ms=10,
                p95_latency_ms=10,
            ),
        )
        headers = {"Idempotency-Key": f"sandbox-run-{uuid4().hex}"}
        request = {"scenario": "healthy", "request_count": 1}
        with patch(
            "app.main.fetch_sandbox_telemetry",
            new=AsyncMock(return_value=snapshot),
        ) as fetch:
            first = self.client.post(
                "/api/sandbox/run",
                json=request,
                headers=headers,
            )
            replay = self.client.post(
                "/api/sandbox/run",
                json=request,
                headers=headers,
            )
            changed = self.client.post(
                "/api/sandbox/run",
                json={"scenario": "high_latency", "request_count": 1},
                headers=headers,
            )

        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(replay.status_code, 201, replay.text)
        self.assertEqual(
            first.json()["incident"]["incident_id"],
            replay.json()["incident"]["incident_id"],
        )
        self.assertEqual(replay.headers["idempotency-replayed"], "true")
        self.assertEqual(changed.status_code, 409, changed.text)
        fetch.assert_awaited_once()
        self.incident_ids.append(first.json()["incident"]["incident_id"])

    def test_in_progress_idempotency_key_rejects_duplicate_request(self) -> None:
        key = f"sandbox-in-progress-{uuid4().hex}"
        body = b'{"scenario":"healthy","request_count":1}'
        reserve_idempotency(
            key,
            "POST:/api/sandbox/run",
            hashlib.sha256(body).hexdigest(),
        )
        self.addCleanup(release_idempotency, key)

        response = self.client.post(
            "/api/sandbox/run",
            content=body,
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": key,
            },
        )

        self.assertEqual(response.status_code, 409, response.text)
        self.assertIn("in progress", response.json()["detail"])

    def test_analysis_is_saved_and_waits_for_approval(self) -> None:
        incident_id = self._create_incident("Mocked model analysis test")
        proposal = ActionCreate(
            tool_name="check_db_status",
            arguments={"shard_id": "DB_SHARD_04"},
            description="Check the simulated shard status",
        )
        evidence = [
            RunbookEvidence(
                source_id="DB-001",
                title="Connection refused by a database shard",
                source_file="database.md",
                content="Check the simulated shard status.",
                score=5,
                matched_terms=["connection", "database", "shard"],
            )
        ]

        analysis = WorkflowAnalysis(
            diagnosis="DB connection refused.",
            proposal=proposal,
            runbook_evidence=evidence,
            cited_evidence_ids=["DB-001"],
            confidence=0.88,
            abstained=False,
            abstention_reason=None,
        )
        with patch(
            "app.main.analyze_incident",
            new=AsyncMock(return_value=analysis),
        ):
            response = self.client.post(
                f"/api/incidents/{incident_id}/analyze"
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["diagnosis"], "DB connection refused.")
        self.assertEqual(body["action"]["status"], "PENDING_APPROVAL")
        self.assertEqual(body["runbook_evidence"][0]["source_id"], "DB-001")
        self.assertEqual(body["cited_evidence_ids"], ["DB-001"])
        self.assertEqual(body["confidence"], 0.88)
        self.assertFalse(body["abstained"])
        saved_incident = self.client.get(
            f"/api/incidents/{incident_id}"
        ).json()
        self.assertEqual(saved_incident["status"], "AWAITING_APPROVAL")
        self.assertEqual(saved_incident["cited_evidence_ids"], ["DB-001"])
        self.assertEqual(saved_incident["analysis_confidence"], 0.88)
        self.assertEqual(
            saved_incident["runbook_evidence"][0]["source_file"],
            "database.md",
        )

    def test_abstained_analysis_is_saved_without_creating_action(self) -> None:
        incident_id = self._create_incident("Mocked abstention analysis test")
        analysis = WorkflowAnalysis(
            diagnosis="The available evidence is insufficient.",
            proposal=None,
            runbook_evidence=[],
            cited_evidence_ids=[],
            confidence=0,
            abstained=True,
            abstention_reason="No relevant runbook evidence was retrieved.",
        )

        with patch(
            "app.main.analyze_incident",
            new=AsyncMock(return_value=analysis),
        ):
            response = self.client.post(
                f"/api/incidents/{incident_id}/analyze"
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertTrue(body["abstained"])
        self.assertIsNone(body["action"])
        self.assertEqual(body["confidence"], 0)
        self.assertIn("No relevant", body["abstention_reason"])
        self.assertEqual(
            self.client.get(
                f"/api/incidents/{incident_id}/actions"
            ).json(),
            [],
        )
        saved_incident = self.client.get(
            f"/api/incidents/{incident_id}"
        ).json()
        self.assertEqual(saved_incident["status"], "OPEN")
        self.assertTrue(saved_incident["analysis_abstained"])
        self.assertEqual(saved_incident["analysis_confidence"], 0)
        self.assertEqual(
            saved_incident["abstention_reason"],
            "No relevant runbook evidence was retrieved.",
        )

    def test_invalid_model_analysis_returns_gateway_error(self) -> None:
        incident_id = self._create_incident("Invalid model analysis test")
        with patch(
            "app.main.analyze_incident",
            new=AsyncMock(side_effect=ValueError("Unknown evidence ID")),
        ):
            response = self.client.post(
                f"/api/incidents/{incident_id}/analyze"
            )

        self.assertEqual(response.status_code, 502, response.text)
        self.assertEqual(
            self.client.get(
                f"/api/incidents/{incident_id}/actions"
            ).json(),
            [],
        )

    def test_analysis_timeout_returns_gateway_timeout(self) -> None:
        incident_id = self._create_incident("Timed analysis test")

        async def slow_analysis(**_: object) -> None:
            await asyncio.sleep(0.05)

        with (
            patch("app.main.settings.analysis_timeout_seconds", 0.01),
            patch(
                "app.main.analyze_incident",
                new=AsyncMock(side_effect=slow_analysis),
            ),
        ):
            response = self.client.post(
                f"/api/incidents/{incident_id}/analyze"
            )

        self.assertEqual(response.status_code, 504, response.text)

    def test_action_history_records_decision_and_execution_timeout(self) -> None:
        incident_id = self._create_incident("Timed action test")
        action = self._create_restart_action(incident_id)

        async def slow_action(*_: object) -> str:
            await asyncio.sleep(0.05)
            return "late result"

        with (
            patch("app.main.settings.mcp_execution_timeout_seconds", 0.01),
            patch(
                "app.main.execute_action",
                new=AsyncMock(side_effect=slow_action),
            ),
        ):
            response = self.client.post(
                f"/api/actions/{action['action_id']}/decision",
                json={"decision": "approve"},
            )

        self.assertEqual(response.status_code, 504, response.text)
        events_response = self.client.get(
            f"/api/actions/{action['action_id']}/events"
        )
        self.assertEqual(events_response.status_code, 200, events_response.text)
        events = events_response.json()
        self.assertEqual(
            [event["event_type"] for event in events],
            [
                "ACTION_CREATED",
                "ACTION_DECISION",
                "ACTION_EXECUTION_FAILED",
            ],
        )
        self.assertEqual(events[-1]["to_status"], "FAILED")
        self.assertEqual(
            self.client.get(
                f"/api/incidents/{incident_id}/actions"
            ).json()[0]["status"],
            "FAILED",
        )

    def test_approval_runs_and_verifies_simulated_restart(self) -> None:
        incident_id = self._create_incident("Approved restart test")
        action = self._create_restart_action(incident_id)

        decision_url = f"/api/actions/{action['action_id']}/decision"
        idempotency_key = f"approve-action-{uuid4().hex}"
        response = self.client.post(
            decision_url,
            json={"decision": "approve"},
            headers={"Idempotency-Key": idempotency_key},
        )
        replay = self.client.post(
            decision_url,
            json={"decision": "approve"},
            headers={"Idempotency-Key": idempotency_key},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "EXECUTED")
        self.assertIn("Verification: ONLINE", response.json()["result"])
        self.assertEqual(replay.status_code, 200, replay.text)
        self.assertEqual(replay.headers["idempotency-replayed"], "true")
        self.assertEqual(replay.json(), response.json())
        self.assertEqual(
            self.client.get(f"/api/incidents/{incident_id}").json()["status"],
            "RESOLVED",
        )

    def test_rejection_does_not_call_mcp_and_cannot_be_repeated(self) -> None:
        incident_id = self._create_incident("Rejected action test")
        action = self._create_restart_action(incident_id)

        with patch("app.main.execute_action", new=AsyncMock()) as execute:
            response = self.client.post(
                f"/api/actions/{action['action_id']}/decision",
                json={"decision": "reject"},
            )
            execute.assert_not_awaited()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "REJECTED")
        repeated = self.client.post(
            f"/api/actions/{action['action_id']}/decision",
            json={"decision": "approve"},
        )
        self.assertEqual(repeated.status_code, 409, repeated.text)

    def test_action_target_must_be_allowlisted(self) -> None:
        incident_id = self._create_incident("Invalid action target test")
        response = self.client.post(
            f"/api/incidents/{incident_id}/actions",
            json={
                "tool_name": "restart_resource",
                "arguments": {"resource_id": "production"},
                "description": "Invalid target",
            },
        )
        self.assertEqual(response.status_code, 422, response.text)


if __name__ == "__main__":
    unittest.main()
