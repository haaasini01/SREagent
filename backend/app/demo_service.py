import asyncio
import math
import time
from datetime import datetime, timezone

from fastapi import FastAPI

from app.schemas import (
    SandboxRunRequest,
    SandboxScenario,
    TelemetryEvent,
    TelemetryMetrics,
    TelemetrySnapshot,
)

app = FastAPI(title="SRE Agent Telemetry Sandbox")
_next_event_id = 1
_last_snapshot: TelemetrySnapshot | None = None


def build_snapshot(
    scenario: SandboxScenario,
    events: list[TelemetryEvent],
) -> TelemetrySnapshot:
    latencies = sorted(event.latency_ms for event in events)
    request_count = len(events)
    error_count = sum(event.status_code >= 500 for event in events)
    p95_index = max(0, math.ceil(0.95 * request_count) - 1)
    return TelemetrySnapshot(
        scenario=scenario,
        captured_at=datetime.now(timezone.utc),
        events=events,
        metrics=TelemetryMetrics(
            request_count=request_count,
            error_count=error_count,
            error_rate=error_count / request_count if request_count else 0,
            avg_latency_ms=(
                sum(latencies) / request_count if request_count else 0
            ),
            p95_latency_ms=latencies[p95_index] if latencies else 0,
        ),
    )


@app.post("/simulate", response_model=TelemetrySnapshot)
async def simulate_requests(request: SandboxRunRequest) -> TelemetrySnapshot:
    global _next_event_id, _last_snapshot

    events: list[TelemetryEvent] = []
    for _ in range(request.request_count):
        started = time.perf_counter()
        error: str | None = None
        status_code = 200

        if request.scenario == SandboxScenario.DATABASE_FAILURE:
            status_code = 503
            error = "connection_refused: DB_SHARD_04"
        elif request.scenario == SandboxScenario.HIGH_LATENCY:
            await asyncio.sleep(0.12)

        latency_ms = (time.perf_counter() - started) * 1000
        events.append(
            TelemetryEvent(
                event_id=_next_event_id,
                timestamp=datetime.now(timezone.utc),
                service="checkout-api",
                scenario=request.scenario,
                endpoint="/checkout",
                status_code=status_code,
                latency_ms=round(latency_ms, 2),
                error=error,
            )
        )
        _next_event_id += 1

    _last_snapshot = build_snapshot(request.scenario, events)
    return _last_snapshot


@app.get("/telemetry", response_model=TelemetrySnapshot | None)
async def read_latest_telemetry() -> TelemetrySnapshot | None:
    return _last_snapshot
