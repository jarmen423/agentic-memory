import { useMemo } from "react";

/**
 * Pretty-prints JSON for score/usage/parsed panels. Malformed values fall back
 * to ``String(value)`` so the UI never crashes on odd DB rows.
 */
export function JsonBlock({ value, title }: { value: unknown; title?: string }) {
  const text = useMemo(() => {
    if (value === null || value === undefined) {
      return String(value);
    }
    if (typeof value === "string") {
      try {
        const parsed = JSON.parse(value) as unknown;
        return JSON.stringify(parsed, null, 2);
      } catch {
        return value;
      }
    }
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }, [value]);

  return (
    <div>
      {title ? <h3 style={{ margin: "0 0 0.5rem", fontSize: "0.9rem" }}>{title}</h3> : null}
      <pre className="json-block" role="region" aria-label={title ?? "json"}>
        {text}
      </pre>
    </div>
  );
}
