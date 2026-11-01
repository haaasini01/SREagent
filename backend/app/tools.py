SERVICE_LOGS = {
    "payment_gateway": (
        "[INFO] Transaction started\n"
        "[ERROR] Connection refused: DB_SHARD_04 unreachable\n"
        "[CRITICAL] Transaction rolled back"
    ),
    "auth_service": "[INFO] Health check: OK",
}

DATABASE_SHARDS = {
    "DB_SHARD_04": "OFFLINE; simulated CPU load 100%, memory 99%",
    "DB_SHARD_01": "ONLINE; simulated load normal",
}
SIMULATED_SHARD_STATUS = dict(DATABASE_SHARDS)


def fetch_service_logs(service_name: str) -> str:
    """Return sample logs for a known simulated service."""
    try:
        return SERVICE_LOGS[service_name]
    except KeyError as error:
        raise ValueError(f"Unknown simulated service: {service_name}") from error


def check_db_status(shard_id: str) -> str:
    """Return the simulated health status of a known database shard."""
    if shard_id not in DATABASE_SHARDS:
        raise ValueError(f"Unknown simulated shard: {shard_id}")
    return SIMULATED_SHARD_STATUS[shard_id]


def restart_resource(resource_id: str) -> str:
    """Simulate restarting an allowlisted resource without touching infrastructure."""
    if resource_id not in DATABASE_SHARDS:
        raise ValueError(f"Unknown simulated resource: {resource_id}")
    SIMULATED_SHARD_STATUS[resource_id] = "ONLINE; simulated load normal"
    return (
        f"SIMULATED SUCCESS: {resource_id} restart recorded. "
        "Simulated health check passed. No real infrastructure was changed."
    )
