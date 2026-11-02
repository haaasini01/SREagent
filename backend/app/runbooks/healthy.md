# Healthy baseline runbook

## [BASE-001] No errors observed in the sample window

Keywords: healthy, baseline, no errors, zero errors, status 200, normal,
successful requests, low latency.

Interpretation: a sample with successful responses, no server errors, and low
latency does not establish an active incident. Check that the sample window is
large enough and compare it with a known baseline before escalating.

Safe next step: do not propose remediation based on this sample alone. Capture
additional telemetry if the operator needs a longer observation window.
