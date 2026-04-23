import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, apiGet, type AnswerDetail, type TaskByArmRow } from "../api/client";
import { JsonBlock } from "../components/JsonBlock";

export default function AnswerDetailPage() {
  const { runId, taskIndex } = useParams();
  const [row, setRow] = useState<AnswerDetail | null>(null);
  const [byArm, setByArm] = useState<TaskByArmRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId || taskIndex === undefined) {
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const idx = Number(taskIndex);
        if (Number.isNaN(idx)) {
          throw new Error("invalid task_index");
        }
        const detail = await apiGet<AnswerDetail>(
          `/answers/detail?run_id=${encodeURIComponent(runId)}&task_index=${idx}`,
        );
        if (cancelled) {
          return;
        }
        setRow(detail);
        setError(null);
        try {
          const arms = await apiGet<TaskByArmRow[]>(
            `/tasks/${encodeURIComponent(detail.task_id)}/by-arm`,
          );
          if (!cancelled) {
            setByArm(arms);
          }
        } catch {
          if (!cancelled) {
            setByArm([]);
          }
        }
      } catch (e) {
        if (!cancelled) {
          setRow(null);
          setByArm(null);
          setError(e instanceof ApiError ? e.body ?? e.message : String(e));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runId, taskIndex]);

  if (!runId || taskIndex === undefined) {
    return <p className="muted">Missing route parameters.</p>;
  }
  if (error) {
    return (
      <div className="panel error" role="alert">
        Could not load answer: {error}
      </div>
    );
  }
  if (!row) {
    return <p className="muted">Loading answer detail…</p>;
  }

  return (
    <div>
      <p>
        <Link to="/answers">← Back to answers</Link>
      </p>
      <div className="panel">
        <h2>Answer detail</h2>
        <p className="muted">
          <strong>run_id</strong> {row.run_id} · <strong>task_index</strong> {row.task_index} ·{" "}
          <strong>task_id</strong> {row.task_id} · <strong>patient</strong> {row.patient_id ?? "—"} ·{" "}
          <strong>snapshot</strong> {row.snapshot_date ?? "—"} · <strong>arm</strong>{" "}
          {row.context_arm ?? "—"} · <strong>model</strong> {row.resolved_model ?? "—"}
        </p>
        <p className="muted">
          parse_ok: {row.parse_ok ? "yes" : "no"} · finish: {row.finish_reason ?? "—"} · latency_ms:{" "}
          {row.latency_ms ?? "—"} · tokens: {row.total_tokens ?? "—"} · focus:{" "}
          {row.exp3_focus_score ?? "—"}
        </p>
      </div>

      {byArm && byArm.length > 0 ? (
        <div className="panel">
          <h2>Same task across arms</h2>
          <table className="data">
            <thead>
              <tr>
                <th className="no-sort">context_arm</th>
                <th className="no-sort">focus</th>
                <th className="no-sort">tokens</th>
                <th className="no-sort">latency</th>
                <th className="no-sort">run_id</th>
                <th className="no-sort">open</th>
              </tr>
            </thead>
            <tbody>
              {byArm.map((r) => (
                <tr key={`${r.run_id}-${r.task_index}-${r.context_arm ?? ""}`}>
                  <td>{r.context_arm ?? ""}</td>
                  <td>{r.exp3_focus_score ?? ""}</td>
                  <td>{r.total_tokens ?? ""}</td>
                  <td>{r.latency_ms ?? ""}</td>
                  <td>{r.run_id}</td>
                  <td>
                    <Link to={`/answers/${encodeURIComponent(r.run_id)}/${r.task_index}`}>open</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      <div className="panel">
        <h2>Raw model output</h2>
        <pre className="raw-text" role="region" aria-label="raw_text">
          {row.raw_text}
        </pre>
      </div>

      <div className="grid-2">
        <div className="panel">
          <JsonBlock value={row.parsed_json} title="parsed_json" />
        </div>
        <div className="panel">
          <JsonBlock value={row.score_json} title="score_json" />
        </div>
        <div className="panel" style={{ gridColumn: "1 / -1" }}>
          <JsonBlock value={row.usage_json} title="usage_json" />
        </div>
      </div>
    </div>
  );
}
