import unittest
from uuid import uuid4

from langchain_core.messages import AIMessage
from pydantic import ValidationError

from app.workflow import AgentProposal, analyze_incident


class StubModel:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = iter(outputs)

    def bind(self, **_: object) -> "StubModel":
        return self

    async def ainvoke(self, _: object) -> AIMessage:
        return AIMessage(content=next(self.outputs))


class AgentWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_graph_returns_validated_pending_action_proposal(self) -> None:
        model = StubModel(
            [
                "Payment gateway cannot connect to DB shard 04.",
                (
                    '{"tool_name":"restart_resource",'
                    '"arguments":{"resource_id":"DB_SHARD_04"},'
                    '"description":"Restart the failing simulated shard."}'
                ),
            ]
        )

        diagnosis, proposal = await analyze_incident(
            uuid4(),
            "Connection refused by DB_SHARD_04",
            model=model,
        )

        self.assertIn("DB shard 04", diagnosis)
        self.assertEqual(proposal.tool_name, "restart_resource")
        self.assertEqual(proposal.arguments, {"resource_id": "DB_SHARD_04"})

    def test_proposal_rejects_unknown_targets(self) -> None:
        with self.assertRaises(ValidationError):
            AgentProposal.model_validate(
                {
                    "tool_name": "restart_resource",
                    "arguments": {"resource_id": "production"},
                    "description": "Restart production",
                }
            )

    def test_proposal_rejects_extra_arguments(self) -> None:
        with self.assertRaises(ValidationError):
            AgentProposal.model_validate(
                {
                    "tool_name": "restart_resource",
                    "arguments": {
                        "resource_id": "DB_SHARD_04",
                        "force": "true",
                    },
                    "description": "Restart the simulated shard",
                }
            )


if __name__ == "__main__":
    unittest.main()
