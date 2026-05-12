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

// ─── Endpoints ──────────────────────────────────────────────────────────

export const fetchHealth = () => getJson<HealthResponse>("/healthz");
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

/** Resolved URL for the SSE endpoint. The dashboard's hook opens an
 *  EventSource against this URL. */
export async function getEventsUrl(): Promise<string> {
  const base = await baseUrl();
  return `${base}/api/sweeps/events`;
}
