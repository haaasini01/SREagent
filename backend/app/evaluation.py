import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage

from app.schemas import ActionCreate
from app.workflow import analyze_incident

CASE_FILE = Path(__file__).resolve().parents[1] / "evaluation" / "cases.json"
PROMPT_VERSION = "grounded-analysis-v1"


class FixtureModel:
    def __init__(self, output: dict[str, Any] | None) -> None:
        self.output = output

    def bind(self, **_: object) -> "FixtureModel":
        return self

    async def ainvoke(self, _: object) -> AIMessage:
        if self.output is None:
            raise AssertionError("A model fixture was used for a no-evidence case")
        return AIMessage(content=json.dumps(self.output))


def load_cases() -> dict[str, Any]:
    with CASE_FILE.open(encoding="utf-8") as case_file:
        suite = json.load(case_file)
    if not isinstance(suite, dict) or not isinstance(suite.get("cases"), list):
        raise ValueError(f"Invalid evaluation suite format: {CASE_FILE}")
    return suite


async def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    result = await analyze_incident(
        incident_id=uuid4(),
        logs=case["logs"],
        model=FixtureModel(case["model_output"]),
    )
    expected_evidence = set(case["expected_evidence_ids"])
    retrieved_evidence = {item.source_id for item in result.runbook_evidence}
    expected_citations = set(case["expected_citations"])
    observed_citations = set(result.cited_evidence_ids)
    action = result.proposal
    action_is_valid = action is None or ActionCreate.model_validate(
        action.model_dump()
    )
    observed_tool = action.tool_name if action is not None else None
    checks = {
        "retrieval": expected_evidence == retrieved_evidence,
        "citations": expected_citations == observed_citations,
        "abstention": case["expected_abstention"] == result.abstained,
        "action": case["expected_tool"] == observed_tool,
        "allowlist": bool(action_is_valid),
    }
    return {
        "case_id": case["case_id"],
        "retrieved_evidence_ids": sorted(retrieved_evidence),
        "cited_evidence_ids": sorted(observed_citations),
        "abstained": result.abstained,
        "tool": observed_tool,
        "checks": checks,
        "passed": all(checks.values()),
    }


async def run_evaluation() -> dict[str, Any]:
    suite = load_cases()
    results = [
        await evaluate_case(case)
        for case in suite["cases"]
    ]
    check_names = ("retrieval", "citations", "abstention", "action", "allowlist")
    totals = {
        name: sum(result["checks"][name] for result in results)
        for name in check_names
    }
    check_count = len(results)
    return {
        "suite_version": suite.get("suite_version", "unknown"),
        "workflow_version": "local-runbook-retrieval-v1",
        "prompt_version": PROMPT_VERSION,
        "model": "scripted fixtures (no Ollama inference)",
        "case_count": check_count,
        "passed_cases": sum(result["passed"] for result in results),
        "checks": {
            name: {
                "passed": passed,
                "total": check_count,
                "rate": passed / check_count if check_count else 1.0,
            }
            for name, passed in totals.items()
        },
        "results": results,
    }


def main() -> int:
    report = asyncio.run(run_evaluation())
    print(json.dumps(report, indent=2))
    return 0 if report["passed_cases"] == report["case_count"] else 1


if __name__ == "__main__":
    sys.exit(main())
