import unittest

from app.evaluation import run_evaluation


class EvaluationSuiteTests(unittest.IsolatedAsyncioTestCase):
    async def test_versioned_fixture_suite_passes_every_contract_check(self) -> None:
        report = await run_evaluation()

        self.assertEqual(report["suite_version"], "1.0.0")
        self.assertEqual(report["case_count"], 5)
        self.assertEqual(report["passed_cases"], 5)
        self.assertEqual(report["model"], "scripted fixtures (no Ollama inference)")
        self.assertTrue(
            all(
                check["rate"] == 1
                for check in report["checks"].values()
            )
        )

    async def test_suite_contains_missing_and_conflicting_evidence_cases(self) -> None:
        report = await run_evaluation()
        results = {item["case_id"]: item for item in report["results"]}

        self.assertTrue(results["unmatched-incident"]["abstained"])
        self.assertEqual(
            results["unmatched-incident"]["retrieved_evidence_ids"],
            [],
        )
        self.assertTrue(
            results["conflicting-database-and-latency-signals"]["abstained"]
        )


if __name__ == "__main__":
    unittest.main()
