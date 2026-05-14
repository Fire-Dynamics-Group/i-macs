/**
 * Typed API client for the Python FastAPI sidecar.
 *
 * The sidecar's port is dynamic (chosen by the Tauri shell at startup to
 * dodge port-conflict bugs), so every fetch resolves the port via the Tauri
 * `get_sidecar_port` command on first call and caches the base URL.
 */
import { invoke } from "@tauri-apps/api/core";

let cachedBase: string | null = null;

async function baseUrl(): Promise<string> {
  if (cachedBase !== null) return cachedBase;
  const port = await invoke<number>("get_sidecar_port");
  cachedBase = `http://127.0.0.1:${port}`;
  return cachedBase;
}

/** For tests — reset the cached port between cases. */
export function _resetBaseUrl(): void {
  cachedBase = null;
}

async function getJson<T>(path: string): Promise<T> {
  const base = await baseUrl();
  const resp = await fetch(`${base}${path}`);
  if (!resp.ok) {
    throw new Error(`GET ${path} failed: ${resp.status} ${resp.statusText}`);
  }
  return (await resp.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const base = await baseUrl();
  const resp = await fetch(`${base}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) {
    let detail = "";
    try {
      const err = await resp.json();
      detail = err.error ?? err.detail ?? JSON.stringify(err);
    } catch {
      detail = resp.statusText;
    }
    throw new Error(`POST ${path} failed: ${resp.status} ${detail}`);
  }
  return (await resp.json()) as T;
}

// ─── Types ──────────────────────────────────────────────────────────────

export interface SectionsByFamily {
  [family: string]: Array<{ id: string; name: string; h: number; b: number }>;
}

export interface OccupancyPreset {
  name: string;
  mean: number;
  type: string;
  cov: number;
}

export interface RefData {
  sections: SectionsByFamily;
  decks: Record<string, Record<string, unknown>>;
  meshes: Record<string, Record<string, unknown>>;
  defaults: Record<string, unknown>;
  occupancy_presets: OccupancyPreset[];
}

export interface Check {
  name: string;
  value: number | null;
  limit: number;
  pass: boolean;
}

export interface SubmitRunResponse {
  id: number;
  uf_max: number;
  duration_ms: number;
  overall_pass: boolean;
  checks: Check[];
}

export interface Run {
  id: number;
  uf_max: number | null;
  duration_ms: number | null;
  error: string | null;
  overall_pass: boolean;
  checks: Check[];
  [field: string]: unknown;
}

export interface TimeSeriesRow {
  time_step: number;
  time_min: number;
  fire_temp: number;
  utilization_factor: number;
  total_plate_capacity: number;
  [k: string]: number;
}

export interface HealthResponse {
  sidecar: string;
  macs_installed: boolean;
  macs_version: string | null;
  // Issue #23: richer install signal.
  data_xml?: boolean;
  com?: boolean;
  install_path?: string | null;
  attempted_paths?: string[];
}

export interface InstallLocationResponse {
  ok: boolean;
  validated_path: string | null;
  error: string | null;
}

export interface RunsListResponse {
  runs: Run[];
  stats: Record<string, number>;
}

export interface SubmitSweepResponse {
  batch_id: string;
  total: number;
  message: string;
}

export interface BatchSummary {
  batch_id: string;
  created_at: string | null;
  mode: string | null;
  total_expected: number;
  run_count: number;
  pass_count: number;
  fail_count: number;
  error_count: number;
  varying_params: Record<string, unknown>;
  fixed_params: Record<string, unknown>;
  // Multi-desktop sync provenance (#11). Not surfaced in the dashboard yet —
  // the cloud-sync slice owns the device-name display + friendly-name UI.
  device_name?: string | null;
  app_version?: string | null;
  synced_at?: string | null;
}

export interface BatchesListResponse {
  batches: BatchSummary[];
  total: number;
}

export interface UngroupedRunsResponse {
  runs: Run[];
  total: number;
}

export interface StatsResponse {
  total: number;
  successful: number;
  errors: number;
  pass_count: number;
  fail_count: number;
}

// ─── Endpoints ──────────────────────────────────────────────────────────

export const fetchHealth = () => getJson<HealthResponse>("/healthz");
export const setInstallLocation = (folder: string) =>
  postJson<InstallLocationResponse>("/api/install-location", { folder });
export const fetchRefData = () => getJson<RefData>("/api/ref-data");
export const submitRun = (payload: Record<string, unknown>) =>
  postJson<SubmitRunResponse>("/api/runs", payload);
export const submitSweep = (payload: Record<string, unknown>) =>
  postJson<SubmitSweepResponse>("/api/sweeps", payload);
export const getRun = (id: number) => getJson<Run>(`/api/runs/${id}`);
export const getRunTimeseries = (id: number) =>
  getJson<TimeSeriesRow[]>(`/api/runs/${id}/timeseries`);

export function listRuns(opts: { batchId?: string } = {}): Promise<RunsListResponse> {
  const path = opts.batchId
    ? `/api/runs?batch_id=${encodeURIComponent(opts.batchId)}`
    : "/api/runs";
  return getJson<RunsListResponse>(path);
}

export const getBatch = (batchId: string) =>
  getJson<BatchSummary>(`/api/batches/${encodeURIComponent(batchId)}`);

export interface DistributionResponse {
  /** [time_min, value] tuples; exact arithmetic mean across all successful runs. */
  average: Array<[number, number]>;
  /** Up to `spaghetti_n` runs (stride-sampled when batch size exceeds N). */
  spaghetti: Array<{ run_id: number; points: Array<[number, number]> }>;
  /** Null for non-capacity columns. */
  factored_hot_min: number | null;
  factored_hot_max: number | null;
}

/** Fetch the distribution payload for one column of a batch (capacity /
 *  lofl_temp / mesh_temp). Powers the 3 MACS+-style distribution charts on
 *  the AnalyticalView. */
export function fetchDistribution(
  batchId: string,
  column: "total_plate_capacity" | "lofl_temp" | "mesh_temp",
  spaghettiN = 500,
): Promise<DistributionResponse> {
  const params = new URLSearchParams({
    column,
    spaghetti_n: String(spaghettiN),
  });
  return getJson<DistributionResponse>(
    `/api/batches/${encodeURIComponent(batchId)}/distribution?${params.toString()}`,
  );
}

/** Resolved URL for the DOCX report — the dashboard's Download button
 *  navigates to this so the browser handles the file save dialog. */
export async function getReportDocxUrl(batchId: string): Promise<string> {
  const port = await invoke<number>("get_sidecar_port");
  return `http://127.0.0.1:${port}/api/report/docx?batch_id=${encodeURIComponent(batchId)}`;
}

/** PNG chart URL (scatter / capacity) for embedding directly via <img>. */
export async function getReportChartUrl(
  chartType: "scatter" | "capacity",
  batchId: string,
): Promise<string> {
  const port = await invoke<number>("get_sidecar_port");
  return `http://127.0.0.1:${port}/api/report/chart/${chartType}?batch_id=${encodeURIComponent(batchId)}`;
}

export function listBatches(
  opts: { limit?: number; offset?: number } = {},
): Promise<BatchesListResponse> {
  const params = new URLSearchParams();
  if (opts.limit != null) params.set("limit", String(opts.limit));
  if (opts.offset != null) params.set("offset", String(opts.offset));
  const query = params.toString();
  return getJson<BatchesListResponse>(
    query ? `/api/batches?${query}` : "/api/batches",
  );
}

export function listUngroupedRuns(
  opts: { limit?: number; offset?: number } = {},
): Promise<UngroupedRunsResponse> {
  const params = new URLSearchParams();
  if (opts.limit != null) params.set("limit", String(opts.limit));
  if (opts.offset != null) params.set("offset", String(opts.offset));
  const query = params.toString();
  return getJson<UngroupedRunsResponse>(
    query ? `/api/runs/ungrouped?${query}` : "/api/runs/ungrouped",
  );
}

export const fetchStats = () => getJson<StatsResponse>("/api/stats");

/** Resolved URL for the SSE endpoint. The dashboard's hook opens an
 *  EventSource against this URL. */
export async function getEventsUrl(): Promise<string> {
  const base = await baseUrl();
  return `${base}/api/sweeps/events`;
}
