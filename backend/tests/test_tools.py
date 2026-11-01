import unittest

from app.tools import (
    DATABASE_SHARDS,
    SIMULATED_SHARD_STATUS,
    check_db_status,
    fetch_service_logs,
    restart_resource,
)


class SimulatedToolTests(unittest.TestCase):
    def setUp(self) -> None:
        SIMULATED_SHARD_STATUS.update(DATABASE_SHARDS)

    def test_fetch_known_service_logs(self) -> None:
        self.assertIn("DB_SHARD_04", fetch_service_logs("payment_gateway"))

    def test_reject_unknown_service(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown simulated service"):
            fetch_service_logs("unknown_service")

    def test_check_known_shard_status(self) -> None:
        self.assertIn("OFFLINE", check_db_status("DB_SHARD_04"))

    def test_reject_unknown_shard(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown simulated shard"):
            check_db_status("DB_SHARD_UNKNOWN")

    def test_restart_is_explicitly_simulated(self) -> None:
        result = restart_resource("DB_SHARD_04")
        self.assertIn("SIMULATED SUCCESS", result)
        self.assertIn("No real infrastructure was changed", result)
        self.assertIn("ONLINE", check_db_status("DB_SHARD_04"))

    def test_reject_unknown_restart_target(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown simulated resource"):
            restart_resource("production")


if __name__ == "__main__":
    unittest.main()
