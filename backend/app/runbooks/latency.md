# Request latency runbook

## [LAT-001] Elevated endpoint latency

Keywords: latency, high latency, slow, response time, p95, percentile,
checkout-api, endpoint, timeout, duration.

Interpretation: high average or p95 request latency with successful responses
indicates slowness rather than a confirmed dependency outage. Compare the
observed latency metrics across requests and inspect event timestamps and
endpoints before attributing a cause.

Safe next step: gather the simulated service logs and status evidence. Do not
restart a resource unless independent evidence identifies the target and an
operator approves the proposed simulated action.
