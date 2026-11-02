# Database connectivity runbook

## [DB-001] Connection refused by a database shard

Keywords: connection refused, connection_refused, database, DB_SHARD_04,
checkout, payment gateway, shard unreachable, database unavailable.

Interpretation: repeated connection-refused errors naming a database shard
indicate that the calling service cannot establish a connection to that shard.
Check the shard's reported status and correlate the error timestamps with the
service request events.

Safe next step: use the read-only `check_db_status` simulated tool for the
named, allowlisted shard. Do not restart a resource based on this runbook alone;
an operator must review the evidence and explicitly approve any proposed
simulated action.
