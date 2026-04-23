import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, apiGet, type AnswersPageResponse } from "../api/client";

type SortKey = "exp3_focus_score" | "total_tokens" | "latency_ms" | "estimated_cost_usd";

export default function AnswersPage() {
  const [search, setSearch] = useSearchParams();
  const runId = search.get("run_id") ?? "";
  const contextArm = search.get("context_arm") ?? "";
  const patientId = search.get("patient_id") ?? "";
  const parseOkParam = search.get("parse_ok");
  const parseOk =
    parseOkParam === "true" ? true : parseOkParam === "false" ? false : null;
  const includeSmoke = search.get("include_smoke") === "true";

  const page = Math.max(1, Number(search.get("page") ?? "1") || 1);
  const sort = (search.get("sort") as SortKey | null) ?? "exp3_focus_score";
  const order = search.get("order") === "asc" ? "asc" : "desc";

  const [data, setData] = useState<AnswersPageResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const queryString = useMemo(() => {
    const p = new URLSearchParams();
    p.set("page", String(page));
    p.set("page_size", "50");
    p.set("sort", sort);
    p.set("order", order);
    if (runId) {
      p.set("run_id", runId);
    }
    if (contextArm) {
      p.set("context_arm", contextArm);
    }
    if (patientId) {
      p.set("patient_id", patientId);
    }
    if (parseOk !== null) {
      p.set("parse_ok", parseOk ? "true" : "false");
    }
    if (includeSmoke) {
      p.set("include_smoke", "true");
    }
    return `?${p.toString()}`;
  }, [page, sort, order, runId, contextArm, patientId, parseOk, includeSmoke]);

  const load = useCallback(async () => {
    try {
      const res = await apiGet<AnswersPageResponse>(`/answers${queryString}`);
      setData(res);
      setError(null);
    } catch (e) {
      setData(null);
      setError(e instanceof ApiError ? e.body ?? e.message : String(e));
    }
  }, [queryString]);

  useEffect(() => {
    void load();
  }, [load]);

  const setParam = (updates: Record<string, string | null>) => {
    const next = new URLSearchParams(search);
    for (const [k, v] of Object.entries(updates)) {
      if (v === null || v === "") {
        next.delete(k);
      } else {
        next.set(k, v);
      }
    }
    setSearch(next, { replace: true });
  };

  const onSort = (col: SortKey) => {
    if (sort === col) {
      setParam({ order: order === "asc" ? "desc" : "asc", page: "1" });
    } else {
      setParam({ sort: col, order: "desc", page: "1" });
    }
  };

  const sortIndicator = (col: SortKey) => (sort === col ? (order === "asc" ? " ▲" : " ▼") : "");

  if (error) {
    return (
      <div className="panel error" role="alert">
        Could not load answers: {error}
      </div>
    );
  }
  if (!data) {
    return <p className="muted">Loading model answers…</p>;
  }

  const totalPages = Math.max(1, Math.ceil(data.total / data.page_size));

  return (
    <div className="panel">
      <h2>Model answers</h2>
      <div className="filters">
        <label>
          run_id
          <input
            value={runId}
            onChange={(ev) => setParam({ run_id: ev.target.value, page: "1" })}
            placeholder="filter"
          />
        </label>
        <label>
          context_arm
          <input
            value={contextArm}
            onChange={(ev) => setParam({ context_arm: ev.target.value, page: "1" })}
            placeholder="filter"
          />
        </label>
        <label>
          patient_id
          <input
            value={patientId}
            onChange={(ev) => setParam({ patient_id: ev.target.value, page: "1" })}
            placeholder="filter"
          />
        </label>
        <label>
          parse_ok
          <select
            value={parseOk === null ? "" : parseOk ? "true" : "false"}
            onChange={(ev) => {
              const v = ev.target.value;
              setParam({
                parse_ok: v === "" ? null : v,
                page: "1",
              });
            }}
          >
            <option value="">any</option>
            <option value="true">true</option>
            <option value="false">false</option>
          </select>
        </label>
        <label style={{ flexDirection: "row", alignItems: "center", gap: "0.35rem" }}>
          <input
            type="checkbox"
            checked={includeSmoke}
            onChange={(ev) => setParam({ include_smoke: ev.target.checked ? "true" : null, page: "1" })}
          />
          include smoke rows
        </label>
      </div>
      <p className="muted">
        {data.total} row(s) · page {data.page} of {totalPages}
      </p>
      <table className="data">
        <thead>
          <tr>
            <th className="no-sort">detail</th>
            <th onClick={() => onSort("exp3_focus_score")}>focus{sortIndicator("exp3_focus_score")}</th>
            <th onClick={() => onSort("total_tokens")}>tokens{sortIndicator("total_tokens")}</th>
            <th onClick={() => onSort("latency_ms")}>latency_ms{sortIndicator("latency_ms")}</th>
            <th onClick={() => onSort("estimated_cost_usd")}>
              cost_usd{sortIndicator("estimated_cost_usd")}
            </th>
            <th className="no-sort">task_id</th>
            <th className="no-sort">patient</th>
            <th className="no-sort">arm</th>
            <th className="no-sort">parse</th>
            <th className="no-sort">finish</th>
            <th className="no-sort">model</th>
          </tr>
        </thead>
        <tbody>
          {data.items.map((r) => (
            <tr key={`${r.run_id}-${r.task_index}`}>
              <td className="row-actions">
                <Link to={`/answers/${encodeURIComponent(r.run_id)}/${r.task_index}`}>open</Link>
              </td>
              <td>{r.exp3_focus_score ?? ""}</td>
              <td>{r.total_tokens ?? ""}</td>
              <td>{r.latency_ms ?? ""}</td>
              <td>{r.estimated_cost_usd ?? ""}</td>
              <td>{r.task_id}</td>
              <td>{r.patient_id ?? ""}</td>
              <td>{r.context_arm ?? ""}</td>
              <td>{r.parse_ok ? "yes" : "no"}</td>
              <td>{r.finish_reason ?? ""}</td>
              <td>{r.resolved_model ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="pagination">
        <button
          type="button"
          disabled={page <= 1}
          onClick={() => setParam({ page: String(page - 1) })}
        >
          Previous
        </button>
        <button
          type="button"
          disabled={page >= totalPages}
          onClick={() => setParam({ page: String(page + 1) })}
        >
          Next
        </button>
      </div>
    </div>
  );
}
