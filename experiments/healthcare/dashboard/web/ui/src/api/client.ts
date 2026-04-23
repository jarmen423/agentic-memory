/**
 * Thin fetch wrapper for the FastAPI dashboard. Same-origin in production;
 * Vite dev server proxies ``/api`` to uvicorn.
 */

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function parseDetail(res: Response): Promise<string> {
  const text = await res.text();
  try {
    const j = JSON.parse(text) as { detail?: unknown };
    if (j.detail !== undefined) {
      return typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    }
  } catch {
    /* use raw text */
  }
  return text;
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await fetch(path.startsWith("http") ? path : `/api${path}`);
  if (!res.ok) {
    const body = await parseDetail(res);
    throw new ApiError(`HTTP ${res.status}`, res.status, body);
  }
  return res.json() as Promise<T>;
}

export type RunRow = {
  run_id: string;
  experiment: string;
  variant: string | null;
  context_arm: string | null;
  n_tasks: number;
  requested_model: string | null;
  reasoning_effort: string | null;
  imported_at: string;
};

export type ArmSummaryRow = {
  context_arm: string | null;
  answers: number;
  avg_focus: string | number | null;
  avg_tokens: string | number | null;
  avg_latency_ms: string | number | null;
  avg_cost: string | number | null;
};

export type ModelAnswerListItem = {
  run_id: string;
  task_index: number;
  task_id: string;
  patient_id: string | null;
  snapshot_date: string | null;
  context_arm: string | null;
  exp3_focus_score: number | null;
  total_tokens: number | null;
  latency_ms: number | null;
  estimated_cost_usd: number | null;
  parse_ok: boolean;
  finish_reason: string | null;
  resolved_model: string | null;
};

export type AnswersPageResponse = {
  page: number;
  page_size: number;
  total: number;
  items: ModelAnswerListItem[];
};

export type AnswerDetail = {
  run_id: string;
  task_index: number;
  task_id: string;
  patient_id: string | null;
  snapshot_date: string | null;
  context_arm: string | null;
  resolved_model: string | null;
  requested_model: string | null;
  provider: string | null;
  finish_reason: string | null;
  parse_ok: boolean;
  latency_ms: number | null;
  total_tokens: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  reasoning_tokens: number | null;
  estimated_cost_usd: number | null;
  exp3_focus_score: number | null;
  future_issue_recall: number | null;
  history_relevance_recall: number | null;
  grounded_evidence_rate: number | null;
  hallucination_rate: number | null;
  raw_text: string;
  parsed_json: unknown;
  score_json: unknown;
  usage_json: unknown;
};

export type PoorTaskRow = {
  run_id: string;
  task_index: number;
  task_id: string;
  patient_id: string | null;
  context_arm: string | null;
  exp3_focus_score: number | null;
  future_issue_recall: number | null;
  grounded_evidence_rate: number | null;
  hallucination_rate: number | null;
  total_tokens: number | null;
  latency_ms: number | null;
  parse_ok: boolean;
  finish_reason: string | null;
};

export type TaskByArmRow = {
  run_id: string;
  task_index: number;
  context_arm: string | null;
  exp3_focus_score: number | null;
  total_tokens: number | null;
  latency_ms: number | null;
  parsed_json: unknown;
};
