import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, apiGet, type PoorTaskRow } from "../api/client";

export default function PoorTasksPage() {
  const [rows, setRows] = useState<PoorTaskRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiGet<PoorTaskRow[]>("/poor-tasks?limit=25");
        if (!cancelled) {
          setRows(data);
          setError(null);
        }
      } catch (e) {
        if (!cancelled) {
          setRows(null);
          setError(e instanceof ApiError ? e.body ?? e.message : String(e));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <div className="panel error" role="alert">
        Could not load poor-task queue: {error}
      </div>
    );
  }
  if (!rows) {
    return <p className="muted">Loading lowest-scoring answers…</p>;
  }

  return (
    <div className="panel">
      <h2>Poor-task review queue</h2>
      <p className="muted">
        Lowest ``exp3_focus_score`` (non-null), limit 25 — for qualitative review.
      </p>
      <table className="data">
        <thead>
          <tr>
            <th className="no-sort">review</th>
            <th className="no-sort">focus</th>
            <th className="no-sort">task_id</th>
            <th className="no-sort">patient</th>
            <th className="no-sort">arm</th>
            <th className="no-sort">fut_recall</th>
            <th className="no-sort">grounded</th>
            <th className="no-sort">halluc</th>
            <th className="no-sort">tokens</th>
            <th className="no-sort">latency</th>
            <th className="no-sort">parse</th>
            <th className="no-sort">finish</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.run_id}-${r.task_index}`}>
              <td className="row-actions">
                <Link to={`/answers/${encodeURIComponent(r.run_id)}/${r.task_index}`}>open</Link>
              </td>
              <td>{r.exp3_focus_score ?? ""}</td>
              <td>{r.task_id}</td>
              <td>{r.patient_id ?? ""}</td>
              <td>{r.context_arm ?? ""}</td>
              <td>{r.future_issue_recall ?? ""}</td>
              <td>{r.grounded_evidence_rate ?? ""}</td>
              <td>{r.hallucination_rate ?? ""}</td>
              <td>{r.total_tokens ?? ""}</td>
              <td>{r.latency_ms ?? ""}</td>
              <td>{r.parse_ok ? "yes" : "no"}</td>
              <td>{r.finish_reason ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
