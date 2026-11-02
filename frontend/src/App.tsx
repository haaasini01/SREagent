import { useEffect, useState } from "react";

type HealthStatus = {
  status: string;
  service: string;
  version: string;
};

type Incident = {
  incident_id: string;
  title: string;
  logs: string;
  severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  status:
    | "OPEN"
    | "ANALYZING"
    | "AWAITING_APPROVAL"
    | "RESOLVED"
    | "REJECTED"
    | "FAILED";
  diagnosis: string | null;
  telemetry: TelemetrySnapshot | null;
  runbook_evidence: RunbookEvidence[];
  cited_evidence_ids: string[];
  analysis_confidence: number | null;
  analysis_abstained: boolean;
  abstention_reason: string | null;
  created_at: string;
};

type RunbookEvidence = {
  source_id: string;
  title: string;
  source_file: string;
  content: string;
  score: number;
  matched_terms: string[];
};

type TelemetryEvent = {
  event_id: number;
  timestamp: string;
  service: string;
  scenario: string;
  endpoint: string;
  status_code: number;
  latency_ms: number;
  error: string | null;
};

type TelemetrySnapshot = {
  scenario: string;
  captured_at: string;
  events: TelemetryEvent[];
  metrics: {
    request_count: number;
    error_count: number;
    error_rate: number;
    avg_latency_ms: number;
    p95_latency_ms: number;
  };
};

type Action = {
  action_id: string;
  incident_id: string;
  tool_name: string;
  arguments: Record<string, string>;
  description: string;
  status:
    | "PENDING_APPROVAL"
    | "APPROVED"
    | "REJECTED"
    | "EXECUTED"
    | "FAILED";
  result: string | null;
};

type ActionEvent = {
  event_id: string;
  action_id: string;
  from_status: Action["status"] | null;
  to_status: Action["status"];
  event_type: string;
  details: Record<string, string>;
  created_at: string;
};

async function requestJson<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const responseText = await response.text();
    let detail = responseText || `HTTP ${response.status}`;
    if (responseText) {
      try {
        const body = JSON.parse(responseText) as { detail?: unknown };
        if (typeof body.detail === "string") detail = body.detail;
      } catch {
        detail = responseText;
      }
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

function statusClass(status: string) {
  return status.toLowerCase().replaceAll("_", "-");
}

export default function App() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | null>(
    null,
  );
  const [selectedScenario, setSelectedScenario] = useState("database_failure");
  const [actions, setActions] = useState<Action[]>([]);
  const [actionEvents, setActionEvents] = useState<
    Record<string, ActionEvent[]>
  >({});
  const [expandedEventsId, setExpandedEventsId] = useState<string | null>(null);
  const [loadingEventsId, setLoadingEventsId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selectedIncident = incidents.find(
    (incident) => incident.incident_id === selectedIncidentId,
  );

  useEffect(() => {
    let active = true;
    async function loadDashboard() {
      try {
        const [apiHealth, savedIncidents] = await Promise.all([
          requestJson<HealthStatus>("/api/health"),
          requestJson<Incident[]>("/api/incidents"),
        ]);
        if (!active) return;
        setHealth(apiHealth);
        setIncidents(savedIncidents);
        setSelectedIncidentId((current) => current ?? savedIncidents[0]?.incident_id ?? null);
      } catch (reason) {
        if (active) {
          setError(
            reason instanceof Error ? reason.message : "Unable to load dashboard",
          );
        }
      }
    }
    void loadDashboard();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    if (!selectedIncidentId) {
      setActions([]);
      return () => {
        active = false;
      };
    }

    requestJson<Action[]>(
      `/api/incidents/${selectedIncidentId}/actions`,
    )
      .then((savedActions) => {
        if (active) setActions(savedActions);
      })
      .catch((reason: unknown) => {
        if (active) {
          setError(
            reason instanceof Error ? reason.message : "Unable to load actions",
          );
        }
      });
    return () => {
      active = false;
    };
  }, [selectedIncidentId]);

  async function runSandboxScenario() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await requestJson<{
        incident: Incident;
        telemetry: TelemetrySnapshot;
      }>("/api/sandbox/run", {
        method: "POST",
        body: JSON.stringify({ scenario: selectedScenario, request_count: 3 }),
      });
      const incident = result.incident;
      setIncidents((current) => [incident, ...current]);
      setSelectedIncidentId(incident.incident_id);
      setActions([]);
      setNotice(
        `Sandbox generated ${result.telemetry.metrics.request_count} telemetry events and created an incident.`,
      );
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Sandbox run failed",
      );
    } finally {
      setBusy(false);
    }
  }

  async function analyzeIncident() {
    if (!selectedIncident) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await requestJson<{
        diagnosis: string;
        action: Action | null;
        runbook_evidence: RunbookEvidence[];
        cited_evidence_ids: string[];
        confidence: number;
        abstained: boolean;
        abstention_reason: string | null;
      }>(
        `/api/incidents/${selectedIncident.incident_id}/analyze`,
        { method: "POST" },
      );
      setIncidents((current) =>
        current.map((incident) =>
          incident.incident_id === selectedIncident.incident_id
            ? {
                ...incident,
                diagnosis: result.diagnosis,
                runbook_evidence: result.runbook_evidence,
                cited_evidence_ids: result.cited_evidence_ids,
                analysis_confidence: result.confidence,
                analysis_abstained: result.abstained,
                abstention_reason: result.abstention_reason,
                status: result.action ? "AWAITING_APPROVAL" : "OPEN",
              }
            : incident,
        ),
      );
      const action = result.action;
      if (action) {
        setActions((current) => [...current, action]);
      }
      setNotice(
        result.abstained
          ? "Analysis saved without a proposed action. Review the evidence and abstention reason."
          : "Analysis saved. Review the cited evidence and proposed operation before approving.",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Incident analysis failed");
    } finally {
      setBusy(false);
    }
  }

  async function decideAction(action: Action, decision: "approve" | "reject") {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await requestJson<Action>(
        `/api/actions/${action.action_id}/decision`,
        {
          method: "POST",
          body: JSON.stringify({ decision }),
        },
      );
      setActions((current) =>
        current.map((item) =>
          item.action_id === updated.action_id ? updated : item,
        ),
      );
      setActionEvents((current) => {
        const next = { ...current };
        delete next[action.action_id];
        return next;
      });
      const refreshedIncident = await requestJson<Incident>(
        `/api/incidents/${action.incident_id}`,
      );
      setIncidents((current) =>
        current.map((item) =>
          item.incident_id === refreshedIncident.incident_id
            ? refreshedIncident
            : item,
        ),
      );
      setNotice(
        decision === "approve"
          ? "Approved simulated operation finished. Review its result below."
          : "Proposal rejected. No simulated operation was run.",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Decision failed");
    } finally {
      setBusy(false);
    }
  }

  async function refreshSelectedIncident() {
    if (!selectedIncidentId) return;
    setRefreshing(true);
    setError(null);
    try {
      const [incident, savedActions] = await Promise.all([
        requestJson<Incident>(`/api/incidents/${selectedIncidentId}`),
        requestJson<Action[]>(
          `/api/incidents/${selectedIncidentId}/actions`,
        ),
      ]);
      setIncidents((current) =>
        current.map((item) =>
          item.incident_id === incident.incident_id ? incident : item,
        ),
      );
      setActions(savedActions);
      setActionEvents({});
      setExpandedEventsId(null);
      setNotice("Incident and action history refreshed.");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Unable to refresh incident",
      );
    } finally {
      setRefreshing(false);
    }
  }

  async function toggleActionEvents(actionId: string) {
    if (expandedEventsId === actionId) {
      setExpandedEventsId(null);
      return;
    }
    setExpandedEventsId(actionId);
    if (actionEvents[actionId]) return;

    setLoadingEventsId(actionId);
    setError(null);
    try {
      const events = await requestJson<ActionEvent[]>(
        `/api/actions/${actionId}/events`,
      );
      setActionEvents((current) => ({ ...current, [actionId]: events }));
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Unable to load action history",
      );
      setExpandedEventsId(null);
    } finally {
      setLoadingEventsId(null);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">O</div>
          <div>
            <p className="eyebrow">INCIDENT OPERATIONS</p>
            <h1>SRE Agent</h1>
          </div>
        </div>
        <div className="topbar-right">
          <span className="stage-pill">UPGRADE 3 · GROUNDED ANALYSIS</span>
          <span className={`api-indicator ${health ? "connected" : ""}`}>
            <i />
            {health ? "API CONNECTED" : "API OFFLINE"}
          </span>
        </div>
      </header>

      <div className="workspace">
        <aside className="sidebar">
          <div className="side-heading">
            <p className="eyebrow">WORKSPACE</p>
            <span className="env-pill">SIMULATED</span>
          </div>
          <section className="scenario-box">
            <p className="section-label">INCIDENT SIMULATOR</p>
            <label htmlFor="scenario">Choose a scenario</label>
            <select
              id="scenario"
              value={selectedScenario}
              onChange={(event) => setSelectedScenario(event.target.value)}
            >
              <option value="healthy">Healthy baseline</option>
              <option value="database_failure">Database connection failure</option>
              <option value="high_latency">High latency</option>
            </select>
            <button
              className="button button-primary full-width"
              onClick={() => void runSandboxScenario()}
              disabled={busy || !health}
            >
              {busy ? "Running sandbox…" : "Run sandbox & ingest"}
            </button>
            <p className="sandbox-note">
              Runs 3 local requests, captures generated logs and metrics, then
              creates an incident from that telemetry.
            </p>
          </section>

          <section className="incident-list">
            <div className="section-heading">
              <p className="section-label">RECENT INCIDENTS</p>
              <span>{incidents.length.toString().padStart(2, "0")}</span>
            </div>
            {incidents.length === 0 ? (
              <p className="muted small">No incidents yet. Create a scenario to begin.</p>
            ) : (
              <ul>
                {incidents.map((incident) => (
                  <li key={incident.incident_id}>
                    <button
                      className={`incident-link ${selectedIncidentId === incident.incident_id ? "selected" : ""}`}
                      onClick={() => setSelectedIncidentId(incident.incident_id)}
                    >
                      <span className={`severity-dot ${statusClass(incident.severity)}`} />
                      <span className="incident-link-content">
                        <strong>{incident.title}</strong>
                        <small>{incident.status.replaceAll("_", " ")}</small>
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <div className="sidebar-foot">
            <span className="safe-icon">✓</span>
            <span>NO LIVE INFRASTRUCTURE<br />CONNECTED</span>
          </div>
        </aside>

        <main className="main-content">
          <div className="page-title">
            <div>
              <p className="eyebrow">AUTONOMOUS SRE WORKBENCH</p>
              <h2>{selectedIncident?.title ?? "Respond to incidents with control."}</h2>
            </div>
            {selectedIncident && (
              <div className="incident-toolbar">
                <button
                  className="button button-secondary"
                  onClick={() => void refreshSelectedIncident()}
                  disabled={refreshing || busy}
                >
                  {refreshing ? "Refreshing…" : "Refresh"}
                </button>
                <span className={`status-badge ${statusClass(selectedIncident.status)}`}>
                  {selectedIncident.status.replaceAll("_", " ")}
                </span>
              </div>
            )}
          </div>

          {error && <div className="alert alert-error" role="alert" aria-live="assertive">{error}</div>}
          {notice && <div className="alert alert-success" role="status" aria-live="polite">{notice}</div>}
          {busy && (
            <div className="operation-progress" role="status" aria-live="polite">
              Request in progress. Waiting for the API response…
            </div>
          )}

          {!selectedIncident ? (
            <section className="empty-state panel">
              <div className="empty-glyph">⌁</div>
              <p className="eyebrow">READY WHEN YOU ARE</p>
              <h3>Run a sandbox scenario</h3>
              <p className="muted">
                Generate local request telemetry from a controlled scenario.
                The agent can then analyze its evidence and propose an
                allowlisted action for your review.
              </p>
            </section>
          ) : (
            <>
              <div className="metrics-row">
                <article className="metric panel">
                  <span className="metric-icon">ID</span>
                  <div><small>INCIDENT</small><strong>{selectedIncident.incident_id.slice(0, 8).toUpperCase()}</strong></div>
                </article>
                <article className="metric panel">
                  <span className="metric-icon severity-icon">!</span>
                  <div><small>SEVERITY</small><strong>{selectedIncident.severity}</strong></div>
                </article>
                <article className="metric panel">
                  <span className="metric-icon">AI</span>
                  <div><small>AI PROVIDER</small><strong>{health?.status === "ok" ? "Ollama · local" : "Offline"}</strong></div>
                </article>
              </div>

              <div className="content-grid">
                <section className="panel incident-panel">
                  <div className="panel-heading">
                    <div>
                      <p className="eyebrow">INCIDENT CONTEXT</p>
                      <h3>Signal & diagnosis</h3>
                    </div>
                    {!selectedIncident.diagnosis && (
                      <button
                        className="button button-secondary"
                        onClick={() => void analyzeIncident()}
                        disabled={busy}
                      >
                        {busy ? "Analyzing…" : "Analyze logs"}
                      </button>
                    )}
                  </div>
                  <div className="subsection">
                    <p className="section-label">SOURCE LOGS</p>
                    <pre className="log-view">{selectedIncident.logs}</pre>
                  </div>
                  {selectedIncident.telemetry && (
                    <div className="subsection telemetry-section">
                      <p className="section-label">CAPTURED TELEMETRY</p>
                      <p className="telemetry-captured">
                        Captured {new Date(selectedIncident.telemetry.captured_at).toLocaleString()}
                      </p>
                      <div className="telemetry-metrics">
                        <div><small>REQUESTS</small><strong>{selectedIncident.telemetry.metrics.request_count}</strong></div>
                        <div><small>ERRORS</small><strong>{selectedIncident.telemetry.metrics.error_count}</strong></div>
                        <div><small>ERROR RATE</small><strong>{(selectedIncident.telemetry.metrics.error_rate * 100).toFixed(0)}%</strong></div>
                        <div><small>AVG LATENCY</small><strong>{selectedIncident.telemetry.metrics.avg_latency_ms.toFixed(1)} ms</strong></div>
                        <div><small>P95 LATENCY</small><strong>{selectedIncident.telemetry.metrics.p95_latency_ms.toFixed(1)} ms</strong></div>
                      </div>
                      <div className="event-list">
                        {selectedIncident.telemetry.events.map((event) => (
                          <div className="telemetry-event" key={event.event_id}>
                            <span className={event.status_code >= 500 ? "event-error" : "event-ok"}>
                              {event.status_code}
                            </span>
                            <code>{event.service} {event.endpoint}</code>
                            <span>{event.latency_ms.toFixed(1)} ms</span>
                            <time dateTime={event.timestamp}>
                              {new Date(event.timestamp).toLocaleTimeString()}
                            </time>
                            {event.error && <small>{event.error}</small>}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="subsection diagnosis">
                    <p className="section-label">MODEL ASSESSMENT</p>
                    {selectedIncident.diagnosis ? (
                      <>
                        <p>{selectedIncident.diagnosis}</p>
                        {selectedIncident.analysis_confidence !== null && (
                          <div className="analysis-meta">
                            <span>
                              CONFIDENCE{" "}
                              {(selectedIncident.analysis_confidence * 100).toFixed(0)}%
                            </span>
                            <span>
                              CITED{" "}
                              {selectedIncident.cited_evidence_ids.length > 0
                                ? selectedIncident.cited_evidence_ids.join(", ")
                                : "NONE"}
                            </span>
                            {selectedIncident.analysis_abstained && (
                              <strong>ABSTAINED</strong>
                            )}
                          </div>
                        )}
                        {selectedIncident.analysis_confidence !== null && (
                          <small className="confidence-note">
                            Model-reported confidence; not calibrated.
                          </small>
                        )}
                        {selectedIncident.analysis_abstained &&
                          selectedIncident.abstention_reason && (
                            <p className="abstention-reason">
                              {selectedIncident.abstention_reason}
                            </p>
                          )}
                      </>
                    ) : (
                      <p className="muted">Run analysis to generate a diagnosis and proposed action.</p>
                    )}
                  </div>
                  {selectedIncident.diagnosis && (
                    <div className="subsection runbook-evidence">
                      <p className="section-label">RETRIEVED RUNBOOK EVIDENCE</p>
                      {selectedIncident.runbook_evidence.length === 0 ? (
                        <p className="muted small">
                          No relevant runbook passage was found for this incident.
                        </p>
                      ) : (
                        <div className="evidence-list">
                          {selectedIncident.runbook_evidence.map((evidence) => (
                            <article className="evidence-card" key={evidence.source_id}>
                              <div className="evidence-heading">
                                <strong>{evidence.source_id} · {evidence.title}</strong>
                                <div className="evidence-tags">
                                  <small>{evidence.source_file} · score {evidence.score}</small>
                                  {selectedIncident.cited_evidence_ids.includes(evidence.source_id) ? (
                                    <span className="citation-tag">CITED</span>
                                  ) : (
                                    <span className="citation-tag not-cited">NOT CITED</span>
                                  )}
                                </div>
                              </div>
                              <details>
                                <summary>Inspect retrieved passage</summary>
                                <p>{evidence.content}</p>
                              </details>
                              <small>
                                Matched terms: {evidence.matched_terms.join(", ")}
                              </small>
                            </article>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </section>

                <section className="panel operations-panel">
                  <div className="panel-heading">
                    <div>
                      <p className="eyebrow">HUMAN-IN-THE-LOOP</p>
                      <h3>Proposed operations</h3>
                    </div>
                    <span className="count-badge">{actions.length}</span>
                  </div>
                  {actions.length === 0 ? (
                    <div className="no-actions">
                      <span>⌘</span>
                      <p>
                        {selectedIncident.analysis_abstained
                          ? "No action proposed"
                          : "No proposed actions"}
                      </p>
                      <small>
                        {selectedIncident.analysis_abstained
                          ? "The analysis abstained; review its evidence and reason before deciding what to do next."
                          : "The agent has not submitted a plan for review."}
                      </small>
                    </div>
                  ) : (
                    <div className="action-list">
                      {actions.map((action) => (
                        <article className="action-card" key={action.action_id}>
                          <div className="action-title-row">
                            <span className="tool-icon">ƒ</span>
                            <div className="action-title">
                              <strong>{action.tool_name}</strong>
                              <small>{action.description}</small>
                            </div>
                            <span className={`status-badge ${statusClass(action.status)}`}>
                              {action.status.replaceAll("_", " ")}
                            </span>
                          </div>
                          <div className="argument-row">
                            <span>ARGUMENTS</span>
                            <code>{JSON.stringify(action.arguments)}</code>
                          </div>
                          {action.result && (
                            <div className="result-box">
                              <span>EXECUTION RESULT</span>
                              <pre>{action.result}</pre>
                            </div>
                          )}
                          <button
                            className="button button-history"
                            onClick={() => void toggleActionEvents(action.action_id)}
                            disabled={loadingEventsId === action.action_id}
                            aria-expanded={expandedEventsId === action.action_id}
                          >
                            {loadingEventsId === action.action_id
                              ? "Loading history…"
                              : expandedEventsId === action.action_id
                                ? "Hide action history"
                                : "Show action history"}
                          </button>
                          {expandedEventsId === action.action_id &&
                            actionEvents[action.action_id] && (
                              <ol className="action-timeline">
                                {actionEvents[action.action_id].map((event) => (
                                  <li key={event.event_id}>
                                    <strong>{event.event_type.replaceAll("_", " ")}</strong>
                                    <span>
                                      {event.from_status
                                        ? `${event.from_status} → ${event.to_status}`
                                        : event.to_status}
                                    </span>
                                    <time dateTime={event.created_at}>
                                      {new Date(event.created_at).toLocaleString()}
                                    </time>
                                    {Object.keys(event.details).length > 0 && (
                                      <small>{JSON.stringify(event.details)}</small>
                                    )}
                                  </li>
                                ))}
                              </ol>
                            )}
                          {action.status === "PENDING_APPROVAL" && (
                            <div className="decision-row">
                              <p>Review carefully. Approval runs this simulated tool.</p>
                              <div className="decision-buttons">
                                <button
                                  className="button button-danger"
                                  onClick={() => void decideAction(action, "reject")}
                                  disabled={busy}
                                >
                                  Reject
                                </button>
                                <button
                                  className="button button-approve"
                                  onClick={() => void decideAction(action, "approve")}
                                  disabled={busy}
                                >
                                  {busy ? "Working…" : "Approve & run"}
                                </button>
                              </div>
                            </div>
                          )}
                        </article>
                      ))}
                    </div>
                  )}
                  {selectedIncident.diagnosis &&
                    actions.length === 0 &&
                    !selectedIncident.analysis_abstained && (
                    <button
                      className="button button-secondary full-width"
                      onClick={() => void analyzeIncident()}
                      disabled={busy}
                    >
                      Analyze and propose an action
                    </button>
                  )}
                </section>
              </div>
            </>
          )}
          <footer className="main-footer">
            <span>SRE AGENT · LOCAL DEVELOPMENT</span>
            <span>SIMULATED TOOLS ONLY</span>
          </footer>
        </main>
      </div>
    </div>
  );
}
