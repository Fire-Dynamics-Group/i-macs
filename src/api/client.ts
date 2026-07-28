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
  // Browser dev (no Tauri runtime — e.g. viewing over a VS Code tunnel):
  // talk to an explicit sidecar URL instead of the get_sidecar_port IPC.
  // Unset in the packaged desktop app, so production still uses the IPC.
  const envBase = (import.meta as unknown as {
    env?: Record<string, string | undefined>;
  }).env?.VITE_SIDECAR_URL;
  if (envBase) {
    cachedBase = envBase.replace(/\/+$/, "");
  } else {
    const port = await invoke<number>("get_sidecar_port");
    cachedBase = `http://127.0.0.1:${port}`;
  }
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

async function patchJson<T>(path: string, body: unknown): Promise<T> {
  const base = await baseUrl();
  const resp = await fetch(`${base}${path}`, {
    method: "PATCH",
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
    throw new Error(`PATCH ${path} failed: ${resp.status} ${detail}`);
  }
  return (await resp.json()) as T;
}

async function deleteJson<T>(path: string): Promise<T> {
  const base = await baseUrl();
  const resp = await fetch(`${base}${path}`, { method: "DELETE" });
  if (!resp.ok) {
    throw new Error(`DELETE ${path} failed: ${resp.status} ${resp.statusText}`);
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

/** The .frc a batch or run was seeded from, as returned inline on batch and
 *  run responses. The XML itself is fetched separately via `getFrcImport` —
 *  inlining a ~6 KB blob per row would bloat the batches list. */
export interface FrcRef {
  id: string;
  filename: string | null;
  /** Raw <Project> properties: ProjectName, JobNumber, ClientCompany, … */
  project: Record<string, string>;
}

/** Human-friendly labels + .frc provenance sent alongside a run/sweep submit. */
export interface SubmitMeta {
  name?: string;
  project_name?: string;
  frc_import_id?: string;
}

export interface Run {
  id: number;
  uf_max: number | null;
  duration_ms: number | null;
  error: string | null;
  overall_pass: boolean;
  checks: Check[];
  /** Labels. On a run inside a batch these are resolved from its batch; an
   *  ungrouped single run carries its own. */
  name?: string | null;
  project_name?: string | null;
  frc?: FrcRef | null;
  /** FRACOF engine version that produced this run (e.g. "2.0.0.2"); null for
   *  runs recorded before engine-version stamping. */
  engine_version?: string | null;
  /** Beams whose degree of shear connection is below the EN 1994-1-1 minimum.
   *  Advisory — does not affect the pass/fail verdict. */
  shear_flags?: ShearFlag[];
  [field: string]: unknown;
}

export interface TimeSeriesRow {
  time_step: number;
  time_min: number;
  fire_temp: number;
  lofl_temp: number;
  mesh_temp: number;
  slabtop_temp: number;
  slabbot_temp: number;
  beam_hot_capacity: number;
  deflection: number;
  slab_cap: number;
  total_plate_capacity: number;
  utilization_factor: number;
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
  /** Sampling mode from the stored config: "paired" | "lhs" | null.
   *  null = historical grid sweep (predates paired-mode); Rerun is disabled. */
  sampling?: string | null;
  /** User-supplied batch label; null falls back to the short batch id. */
  name?: string | null;
  project_name?: string | null;
  /** The .frc this batch was seeded from, or null if configured by hand. */
  frc?: FrcRef | null;
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

export interface ImportFrcResponse {
  params: Record<string, unknown>;
  project: Record<string, string>;
  /** Content-hash id of the stored file — send it back in `meta` on submit so
   *  the resulting batch stays traceable to this exact .frc. */
  frc_import_id: string;
  frc_filename: string | null;
}

/** Upload a .frc file to the sidecar for parsing. Returns engine-keyed
 *  params + project metadata, and persists the file so the run or batch it
 *  seeds can point back at it. The frontend then runs the params through
 *  hydrateFormFromFrcParams to map them to FormValues. */
export async function importFrc(file: File): Promise<ImportFrcResponse> {
  const base = await baseUrl();
  const form = new FormData();
  form.append("file", file, file.name);
  const resp = await fetch(`${base}/api/import-frc`, {
    method: "POST",
    body: form,
  });
  if (!resp.ok) {
    let detail = "";
    try {
      const err = await resp.json();
      detail = err.error ?? err.detail ?? JSON.stringify(err);
    } catch {
      detail = resp.statusText;
    }
    throw new Error(detail || `Failed to import .frc (${resp.status})`);
  }
  return (await resp.json()) as ImportFrcResponse;
}

export function listRuns(opts: { batchId?: string } = {}): Promise<RunsListResponse> {
  const path = opts.batchId
    ? `/api/runs?batch_id=${encodeURIComponent(opts.batchId)}`
    : "/api/runs";
  return getJson<RunsListResponse>(path);
}

export const getBatch = (batchId: string) =>
  getJson<BatchSummary>(`/api/batches/${encodeURIComponent(batchId)}`);

/** Relabel a batch. Omitted fields are left untouched; an empty string clears
 *  one back to the short-id fallback. */
export const renameBatch = (
  batchId: string,
  patch: { name?: string; project_name?: string },
) =>
  patchJson<BatchSummary>(
    `/api/batches/${encodeURIComponent(batchId)}`,
    patch,
  );

/** One input of a batch's shared setup. `varies: false` carries a single
 *  `value`; `varies: true` carries a numeric `min`/`max` range, or a sampled
 *  `values` list when the field isn't numeric. */
export interface SetupField {
  key: string;
  label: string;
  /** "mm", "MPa", … or "" for dimensionless fields. */
  unit: string;
  varies: boolean;
  value?: string | number | null;
  distinct?: number;
  min?: number;
  max?: number;
  values?: Array<string | number | null>;
}

export interface BatchSetup {
  run_count: number;
  groups: Array<{ title: string; fields: SetupField[] }>;
}

/** The configuration shared by every run in a batch, derived from the stored
 *  runs — so it works for hand-configured batches, not just .frc-seeded ones. */
export const getBatchSetup = (batchId: string) =>
  getJson<BatchSetup>(`/api/batches/${encodeURIComponent(batchId)}/setup`);

/** The inputs a single run was calculated with — same shape as the batch
 *  setup (a one-run batch varies in nothing). Works for errored runs. */
export const getRunSetup = (runId: number) =>
  getJson<BatchSetup>(`/api/runs/${runId}/setup`);

/** Distinct project names across batches and ungrouped runs — powers the
 *  config-page autocomplete and the dashboard filter. */
export const listProjects = () =>
  getJson<{ projects: string[] }>("/api/projects");

export interface StoredFrc extends FrcRef {
  /** The original file, byte-for-byte. */
  xml: string;
  imported_at: string | null;
}

/** Fetch a stored .frc including its XML, for *view original* / *save a copy*. */
export const getFrcImport = (frcId: string) =>
  getJson<StoredFrc>(`/api/frc-imports/${encodeURIComponent(frcId)}`);

/** One beam whose degree of shear connection is below the EN 1994-1-1 minimum. */
export interface ShearFlag {
  beam: string;
  sh_con: number;
  fy: number;
  span: number;
  eta_min_pct: number;
}

export interface ShearCheckResponse {
  batch_id: string;
  /** Number of runs inspected. */
  checked: number;
  sub_limit_runs: Array<{ run_id: number; flags: ShearFlag[] }>;
}

/** Runs in a batch whose degree of shear connection falls below the
 *  EN 1994-1-1 minimum — mirrors the MACS+ beam-check warning. Advisory only:
 *  it does not change the pass/fail verdict. */
export const getShearCheck = (batchId: string) =>
  getJson<ShearCheckResponse>(
    `/api/batches/${encodeURIComponent(batchId)}/shear-check`,
  );

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
  const base = await baseUrl();
  return `${base}/api/report/docx?batch_id=${encodeURIComponent(batchId)}`;
}

/** PNG chart URL (scatter / capacity) for embedding directly via <img>. */
export async function getReportChartUrl(
  chartType: "scatter" | "capacity",
  batchId: string,
): Promise<string> {
  const base = await baseUrl();
  return `${base}/api/report/chart/${chartType}?batch_id=${encodeURIComponent(batchId)}`;
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

/** A user-defined beam section, stored in the per-device SQLite DB. The
 *  sidecar merges these ahead of the Blue Book / Data.xml catalogue, so they
 *  sort to the top of the section dropdown as "<name> (Custom)". */
export interface CustomSection {
  id: string;
  name: string;
  h: number;
  b: number;
  tw: number;
  tf: number;
  created_at?: string | null;
}

export type CustomSectionInput = Omit<CustomSection, "id" | "created_at">;

export const listCustomSections = () =>
  getJson<CustomSection[]>("/api/custom-sections");

export const createCustomSection = (section: CustomSectionInput) =>
  postJson<CustomSection>("/api/custom-sections", section);

export const deleteCustomSection = (id: string) =>
  deleteJson<{ ok?: boolean }>(
    `/api/custom-sections/${encodeURIComponent(id)}`,
  );

/** Resolved URL for the SSE endpoint. The dashboard's hook opens an
 *  EventSource against this URL. */
export async function getEventsUrl(): Promise<string> {
  const base = await baseUrl();
  return `${base}/api/sweeps/events`;
}
