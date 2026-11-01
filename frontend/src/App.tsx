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
  created_at: string;
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

type Scenario = {
  title: string;
  severity: Incident["severity"];
  logs: string;
};

const scenarios: Record<string, Scenario> = {
  database: {
    title: "Database connection failure",
    severity: "CRITICAL",
    logs: [
      "[ERROR] payment_gateway: Unable to connect to DB_SHARD_04.",
      "[CRITICAL] Connection refused. Transaction rolled back.",
    ].join("\n"),
  },
  auth: {
    title: "Auth service high latency",
    severity: "HIGH",
    logs: "[WARN] auth_service response time exceeded 2000ms.",
  },
  disk: {
    title: "Log storage pressure",
    severity: "HIGH",
    logs: "[CRITICAL] /var/log partition at 99% usage. Write failed.",
  },
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
  const [selectedScenario, setSelectedScenario] = useState("database");
  const [actions, setActions] = useState<Action[]>([]);
  const [busy, setBusy] = useState(false);
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

  async function createIncident() {
    const scenario = scenarios[selectedScenario];
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const incident = await requestJson<Incident>("/api/incidents", {
        method: "POST",
        body: JSON.stringify(scenario),
      });
      setIncidents((current) => [incident, ...current]);
      setSelectedIncidentId(incident.incident_id);
      setActions([]);
      setNotice("Incident created. Analyze the logs to request a safe proposal.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Incident creation failed");
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
      const result = await requestJson<{ diagnosis: string; action: Action }>(
        `/api/incidents/${selectedIncident.incident_id}/analyze`,
        { method: "POST" },
      );
      setIncidents((current) =>
        current.map((incident) =>
          incident.incident_id === selectedIncident.incident_id
            ? {
                ...incident,
                diagnosis: result.diagnosis,
                status: "AWAITING_APPROVAL",
              }
            : incident,
        ),
      );
      setActions((current) => [
        ...current.filter((action) => action.action_id !== result.action.action_id),
        result.action,
      ]);
      setNotice("Analysis saved. Review the proposed operation before approving.");
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
          <span className="stage-pill">STAGES 1–6 · SIMULATED SRE</span>
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
              <option value="database">Database connection failure</option>
              <option value="auth">Auth service high latency</option>
              <option value="disk">Log storage pressure</option>
            </select>
            <pre className="log-preview">{scenarios[selectedScenario].logs}</pre>
            <button
              className="button button-primary full-width"
              onClick={() => void createIncident()}
              disabled={busy || !health}
            >
              + Create incident
            </button>
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
              <span className={`status-badge ${statusClass(selectedIncident.status)}`}>
                {selectedIncident.status.replaceAll("_", " ")}
              </span>
            )}
          </div>

          {error && <div className="alert alert-error" role="alert">{error}</div>}
          {notice && <div className="alert alert-success" role="status">{notice}</div>}

          {!selectedIncident ? (
            <section className="empty-state panel">
              <div className="empty-glyph">⌁</div>
              <p className="eyebrow">READY WHEN YOU ARE</p>
              <h3>Create a simulated incident</h3>
              <p className="muted">
                Pick a scenario on the left. The agent will inspect its logs and
                propose an allowlisted action for your review.
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
                  <div className="subsection diagnosis">
                    <p className="section-label">ROOT CAUSE</p>
                    {selectedIncident.diagnosis ? (
                      <p>{selectedIncident.diagnosis}</p>
                    ) : (
                      <p className="muted">Run analysis to generate a diagnosis and proposed action.</p>
                    )}
                  </div>
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
                      <p>No proposed actions</p>
                      <small>The agent has not submitted a plan for review.</small>
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
                  {selectedIncident.diagnosis && actions.length === 0 && (
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
