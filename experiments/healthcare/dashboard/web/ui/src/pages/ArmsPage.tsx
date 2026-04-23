import { useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ApiError, apiGet, type ArmSummaryRow } from "../api/client";

export default function ArmsPage() {
  const [includeSmoke, setIncludeSmoke] = useState(false);
  const [rows, setRows] = useState<ArmSummaryRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const q = includeSmoke ? "?include_smoke=true" : "?include_smoke=false";
        const data = await apiGet<ArmSummaryRow[]>(`/arms/summary${q}`);
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
  }, [includeSmoke]);

  const chartData = useMemo(() => {
    if (!rows) {
      return [];
    }
    return rows.map((r) => ({
      arm: r.context_arm && r.context_arm.length > 0 ? r.context_arm : "(empty)",
      avg_focus: r.avg_focus === null || r.avg_focus === undefined ? null : Number(r.avg_focus),
      avg_tokens:
        r.avg_tokens === null || r.avg_tokens === undefined ? null : Number(r.avg_tokens),
    }));
  }, [rows]);

  if (error) {
    return (
      <div className="panel error" role="alert">
        Could not load arm summary: {error}
      </div>
    );
  }
  if (!rows) {
    return <p className="muted">Loading arm comparison…</p>;
  }

  return (
    <div className="panel">
      <h2>Arm comparison</h2>
      <label className="muted" style={{ display: "inline-flex", gap: "0.5rem", alignItems: "center" }}>
        <input
          type="checkbox"
          checked={includeSmoke}
          onChange={(ev) => setIncludeSmoke(ev.target.checked)}
        />
        Include smoke / blank ``context_arm`` rows
      </label>
      <div className="chart-wrap">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={chartData} margin={{ top: 8, right: 8, left: 8, bottom: 48 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="arm" interval={0} angle={-28} textAnchor="end" height={60} tick={{ fontSize: 11 }} />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip />
            <Bar dataKey="avg_focus" name="Avg focus" fill="#2563eb" />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="muted" style={{ marginTop: "0.5rem" }}>
        Chart: average Exp3 focus score by ``context_arm``. See table for tokens, latency, and cost.
      </p>
      <table className="data" style={{ marginTop: "1rem" }}>
        <thead>
          <tr>
            <th className="no-sort">context_arm</th>
            <th className="no-sort">answers</th>
            <th className="no-sort">avg_focus</th>
            <th className="no-sort">avg_tokens</th>
            <th className="no-sort">avg_latency_ms</th>
            <th className="no-sort">avg_cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.context_arm ?? "null"}-${i}`}>
              <td>{r.context_arm ?? ""}</td>
              <td>{r.answers}</td>
              <td>{r.avg_focus ?? ""}</td>
              <td>{r.avg_tokens ?? ""}</td>
              <td>{r.avg_latency_ms ?? ""}</td>
              <td>{r.avg_cost ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
