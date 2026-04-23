import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, apiGet, type RunRow } from "../api/client";

export default function RunsPage() {
  const [rows, setRows] = useState<RunRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiGet<RunRow[]>("/runs");
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
        Could not load runs: {error}
      </div>
    );
  }
  if (!rows) {
    return <p className="muted">Loading runs…</p>;
  }
  if (rows.length === 0) {
    return (
      <div className="panel">
        <p>No rows in ``experiment_runs``. Import CSVs with ``load_postgres.py``.</p>
      </div>
    );
  }

  return (
    <div className="panel">
      <h2>Run overview</h2>
      <p className="muted">Rows from ``experiment_runs`` (newest import first).</p>
      <table className="data">
        <thead>
          <tr>
            <th className="no-sort">run_id</th>
            <th className="no-sort">experiment</th>
            <th className="no-sort">variant</th>
            <th className="no-sort">context_arm</th>
            <th className="no-sort">n_tasks</th>
            <th className="no-sort">requested_model</th>
            <th className="no-sort">reasoning_effort</th>
            <th className="no-sort">imported_at</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.run_id}>
              <td>
                <Link to={`/answers?run_id=${encodeURIComponent(r.run_id)}`}>{r.run_id}</Link>
              </td>
              <td>{r.experiment}</td>
              <td>{r.variant ?? ""}</td>
              <td>{r.context_arm ?? ""}</td>
              <td>{r.n_tasks}</td>
              <td>{r.requested_model ?? ""}</td>
              <td>{r.reasoning_effort ?? ""}</td>
              <td>{r.imported_at}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
