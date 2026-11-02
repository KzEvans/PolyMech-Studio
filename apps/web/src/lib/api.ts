/** Thin JSON client for the FastAPI backend. Errors carry the backend's Chinese `detail`. */

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, message: string, code = "") {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (res.ok) return (await res.json()) as T;
  let detail = `请求失败（HTTP ${res.status}）`;
  let code = "";
  try {
    const body = await res.json();
    if (typeof body.detail === "string") detail = body.detail;
    else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg: string }) => d.msg).join("；");
    code = body.code ?? "";
  } catch {
    /* non-JSON error body: keep the generic message */
  }
  throw new ApiError(res.status, detail, code);
}

export const api = {
  get: <T>(path: string) => fetch(`/api${path}`).then((r) => handle<T>(r)),
  post: <T>(path: string, body?: unknown) =>
    fetch(`/api${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then((r) => handle<T>(r)),
  put: <T>(path: string, body: unknown) =>
    fetch(`/api${path}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(
      (r) => handle<T>(r),
    ),
  patch: <T>(path: string, body: unknown) =>
    fetch(`/api${path}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).then(
      (r) => handle<T>(r),
    ),
  delete: <T>(path: string) => fetch(`/api${path}`, { method: "DELETE" }).then((r) => handle<T>(r)),
  upload: <T>(path: string, files: File[]) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    return fetch(`/api${path}`, { method: "POST", body: fd }).then((r) => handle<T>(r));
  },
  /** POST returning a file; triggers a browser download. */
  download: async (path: string, body: unknown, fallbackName: string) => {
    const res = await fetch(`/api${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) await handle(res);
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") ?? "";
    const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(cd)?.[1];
    const name = utf8 ? decodeURIComponent(utf8) : /filename="([^"]+)"/.exec(cd)?.[1] ?? fallbackName;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    a.click();
    URL.revokeObjectURL(a.href);
  },
};

// ------------------------------------------------------------------ shared types
export type Severity = "info" | "warning" | "error";
export type Flag = { code: string; severity: Severity; message: string };

export type Suggestion = {
  column_index: number;
  header: string;
  quantity: string | null;
  unit: string | null;
  confidence: number;
  rationale: string[];
  ambiguities: string[];
  needs_confirmation: boolean;
  alternatives: [string, number][];
  source: string;
};

export type ImportTable = {
  index: number;
  source: string;
  sheet: string | null;
  encoding: string | null;
  delimiter: string | null;
  n_rows: number;
  preamble: string[];
  preamble_fields: Record<string, string>;
  warnings: string[];
  columns: { index: number; header: string; name: string; unit_text: string | null; n_missing: number; n_non_numeric: number; preview: (number | null)[] }[];
  suggestions: Suggestion[];
  profile: string | null;
};

export type ImportFile = { raw_file_id: number; file_name: string; sha256: string; tables: ImportTable[] };
export type Vocabulary = { quantities: { id: string; label: string; kind: string }[]; test_types: { id: string; label: string }[] };
export type QualityIssue = { code: string; severity: Severity; message: string; quantity: string | null; indices: number[] };
export type CheckResult = {
  n_rows: number;
  issues: QualityIssue[];
  x_quantity: string | null;
  preview: Record<string, { x: number[]; y: number[] }>;
  conversions: { quantity: string; header: string; from_unit: string; to_unit: string }[];
};

export type ExperimentSummary = {
  id: number;
  test_type: string;
  material: { id: number; name: string };
  specimen: { id: number; label: string; thickness_m: number | null; width_m: number | null; gauge_length_m: number | null; height_m: number | null; notch_length_m: number | null };
  batch: string;
  created_at: string;
  n_runs: number;
  latest_run: { id: number; method: string; version: number; status: string } | null;
  missing_metadata: { field: string; label: string }[];
  instrument: string;
  test_date: string;
  temperature_k: number | null;
  stretch_rate_per_s: number | null;
  cycle_frequency_hz: number | null;
  crack_resolution_m: number | null;
  notes: string;
};

export type RunSummary = { id: number; method: string; version: number; status: string; created_at: string; operator: string; parent_run_id: number | null; result_sha256: string };

export type ExperimentDetail = ExperimentSummary & {
  raw_files: { id: number; original_name: string; sha256: string; sheet: string | null; encoding: string | null; size_bytes: number; imported_at: string; mappings: { column_index: number; header: string; quantity: string; unit: string; source: string; confidence: number | null }[] }[];
  runs: RunSummary[];
};

export type Property = { id: number; quantity: string; value: number | null; unit: string; uncertainty: number | null; uncertainty_kind: string; lower_bound: number | null; upper_bound: number | null; conditions: Record<string, unknown> };

export type Run = RunSummary & {
  experiment_id: number;
  params: Record<string, unknown>;
  inputs: Record<string, unknown>;
  result: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  flags: Flag[];
  software_version: string;
  input_sha256: string;
  properties: Property[];
  curves: Record<string, (number | null)[]>;
  curves_total_points: Record<string, number>;
};
