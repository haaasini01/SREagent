import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.database import connect
from app.main import app
from app.schemas import ActionCreate


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

    def test_analysis_is_saved_and_waits_for_approval(self) -> None:
        incident_id = self._create_incident("Mocked model analysis test")
        proposal = ActionCreate(
            tool_name="check_db_status",
            arguments={"shard_id": "DB_SHARD_04"},
            description="Check the simulated shard status",
        )

        with patch(
            "app.main.analyze_incident",
            new=AsyncMock(
                return_value=("DB connection refused.", proposal)
            ),
        ):
            response = self.client.post(
                f"/api/incidents/{incident_id}/analyze"
            )

        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["diagnosis"], "DB connection refused.")
        self.assertEqual(body["action"]["status"], "PENDING_APPROVAL")
        self.assertEqual(
            self.client.get(f"/api/incidents/{incident_id}").json()["status"],
            "AWAITING_APPROVAL",
        )

    def test_approval_runs_and_verifies_simulated_restart(self) -> None:
        incident_id = self._create_incident("Approved restart test")
        action = self._create_restart_action(incident_id)

        response = self.client.post(
            f"/api/actions/{action['action_id']}/decision",
            json={"decision": "approve"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "EXECUTED")
        self.assertIn("Verification: ONLINE", response.json()["result"])
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
