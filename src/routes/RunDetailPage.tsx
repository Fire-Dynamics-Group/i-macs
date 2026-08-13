import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { getRun, getRunTimeseries, type Run, type TimeSeriesRow } from "../api/client";
import { CheckBreakdown } from "../components/CheckBreakdown";
import { GoverningCriticalTempCard } from "../components/GoverningCriticalTempCard";
import { PerimeterBeamCheck } from "../components/PerimeterBeamCheck";
import { RunSetupPanel } from "../components/BatchSetupPanel";
import { frcLabel } from "../lib/batchLabel";
import { RunTemperatureChart } from "../sweep/RunTemperatureChart";
import { RunCapacityDeflectionChart } from "../sweep/RunCapacityDeflectionChart";

export default function RunDetailPage() {
  const { id } = useParams<{ id: string }>();
  const runId = Number(id);

  const runQuery = useQuery({
    queryKey: ["run", runId],
    queryFn: () => getRun(runId),
    enabled: Number.isFinite(runId),
  });
  const tsQuery = useQuery({
    queryKey: ["run-ts", runId],
    queryFn: () => getRunTimeseries(runId),
    enabled: Number.isFinite(runId),
  });

  if (!Number.isFinite(runId)) {
    return <p className="p-8 text-rose-700">Invalid run ID: {id}</p>;
  }

  return (
    <div className="mx-auto max-w-5xl p-8">
      <Link to="/" className="text-sm text-blue-700 hover:underline">
        ← Back to config
      </Link>
      <div className="mt-2 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            {runQuery.data?.name?.trim() || `Run #${runId}`}
          </h1>
          <RunProvenance run={runQuery.data} runId={runId} />
        </div>
        {Number.isFinite(runId) && (
          <Link
            to={`/?from_run=${runId}`}
            className="inline-flex items-center rounded border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100"
          >
            Duplicate run
          </Link>
        )}
      </div>

      {runQuery.isLoading && (
        <p className="mt-4 text-slate-600">Loading run…</p>
      )}
      {runQuery.isError && (
        <p className="mt-4 text-rose-700">{(runQuery.error as Error).message}</p>
      )}
      {runQuery.data && <RunSummary run={runQuery.data} />}
      {runQuery.data && !runQuery.data.error && (
        <CheckBreakdown checks={runQuery.data.checks ?? []} />
      )}
      {runQuery.data && !runQuery.data.error && (
        <GoverningCriticalTempCard run={runQuery.data} />
      )}
      {runQuery.data && !runQuery.data.error && (
        <PerimeterBeamCheck run={runQuery.data} />
      )}
      {Number.isFinite(runId) && <RunSetupPanel runId={runId} />}
      {tsQuery.data && tsQuery.data.length > 0 && (
        <>
          <section className="mt-6 rounded-md border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Temperature
            </h2>
            <RunTemperatureChart
              rows={tsQuery.data}
              timeLimit={toNumber(runQuery.data?.time_limit)}
            />
          </section>
          <section className="mt-6 rounded-md border border-slate-200 bg-white p-4 shadow-sm">
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Bending capacity + maximum allowable deflection
            </h2>
            <RunCapacityDeflectionChart
              rows={tsQuery.data}
              factoredHot={toNumber(runQuery.data?.factored_hot)}
              timeLimit={toNumber(runQuery.data?.time_limit)}
            />
          </section>
        </>
      )}
      {tsQuery.data && <TimeSeriesTable rows={tsQuery.data} />}
    </div>
  );
}

/** Project / .frc line under the run heading. A run in a batch inherits both
 *  from its batch (resolved server-side), so this reads the same either way. */
function RunProvenance({ run, runId }: { run?: Run; runId: number }) {
  if (!run) return null;
  const project = run.project_name?.trim();
  const named = !!run.name?.trim();
  if (!project && !run.frc && !named) return null;
  return (
    <p
      className="mt-0.5 flex flex-wrap items-center gap-x-2 text-xs text-slate-500"
      data-testid="run-provenance"
    >
      {named && <span className="font-mono">Run #{runId}</span>}
      {project && <span className="font-medium text-slate-700">{project}</span>}
      {run.frc && <span>seeded from {frcLabel(run.frc)}</span>}
    </p>
  );
}

function toNumber(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

export function RunSummary({ run }: { run: Run }) {
  const ufMax = run.uf_max;
  const passes = run.overall_pass;
  return (
    <section className="mt-4 rounded-md border border-slate-200 bg-white p-6 shadow-sm">
      {run.error ? (
        <p className="text-rose-700">
          Calculation failed: <code>{run.error}</code>
        </p>
      ) : (
        <>
          <div className="flex items-center gap-3">
            <span
              className={
                "inline-flex items-center rounded-full px-3 py-0.5 text-sm font-medium " +
                (passes
                  ? "bg-emerald-100 text-emerald-800"
                  : "bg-rose-100 text-rose-800")
              }
            >
              {passes ? "Pass" : "Fail"}
            </span>
            <span className="text-sm text-slate-600">
              UF max: <strong>{ufMax?.toFixed(3) ?? "—"}</strong>
            </span>
            <span className="text-sm text-slate-600">
              Duration: <strong>{run.duration_ms?.toFixed(0) ?? "—"} ms</strong>
            </span>
            <span className="text-sm text-slate-600">
              Engine: <strong>FRACOF {run.engine_version ?? "—"}</strong>
            </span>
          </div>
          {run.shear_flags && run.shear_flags.length > 0 && (
            <div className="mt-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800">
              <span className="font-medium">
                ⚠ Shear connection below EN 1994-1-1 minimum (advisory)
              </span>
              <ul className="mt-1 list-disc pl-5">
                {run.shear_flags.map((f) => (
                  <li key={f.beam}>
                    {f.beam}: {f.sh_con}% (minimum {f.eta_min_pct}%)
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}

interface TimeSeriesColumn {
  key: string;
  header: string;
  render: (row: TimeSeriesRow) => string;
}

const SUMMARY_COLUMNS: TimeSeriesColumn[] = [
  { key: "time", header: "Time (min)", render: (r) => r.time_min.toFixed(1) },
  { key: "fire_temp", header: "Fire temp (°C)", render: (r) => r.fire_temp.toFixed(0) },
  { key: "uf", header: "UF", render: (r) => r.utilization_factor.toFixed(3) },
  {
    key: "total_slab_capacity",
    header: "Total slab capacity (kN/m²)",
    render: (r) => r.total_plate_capacity.toFixed(1),
  },
];

// Mirrors the full per-time-step table from the MACS+ PDF report (see
// report_docx.py's beam/mesh temperature charts and pdf_oracle.py's column
// list) — lofl_temp is the unprotected beam's temperature.
const FULL_REPORT_COLUMNS: TimeSeriesColumn[] = [
  { key: "time", header: "Time (min)", render: (r) => r.time_min.toFixed(0) },
  { key: "beam_temp", header: "Beam (°C)", render: (r) => r.lofl_temp.toFixed(0) },
  { key: "mesh_temp", header: "Mesh (°C)", render: (r) => r.mesh_temp.toFixed(0) },
  { key: "slab_top_temp", header: "Slab top (°C)", render: (r) => r.slabtop_temp.toFixed(0) },
  {
    key: "slab_bottom_temp",
    header: "Slab bottom (°C)",
    render: (r) => r.slabbot_temp.toFixed(0),
  },
  {
    key: "beam_capacity",
    header: "Beam capacity (kN/m²)",
    render: (r) => r.beam_hot_capacity.toFixed(2),
  },
  {
    key: "max_deflection",
    header: "Maximum allowable deflection (mm)",
    render: (r) => r.deflection.toFixed(0),
  },
  {
    key: "slab_yield",
    header: "Slab yield (kN/m²)",
    render: (r) => r.slab_yield.toFixed(2),
  },
  {
    key: "enhancement",
    header: "Enhancement",
    render: (r) => r.enhancement.toFixed(2),
  },
  {
    key: "slab_capacity",
    header: "Slab capacity (kN/m²)",
    render: (r) => r.slab_cap.toFixed(2),
  },
  {
    key: "total_capacity",
    header: "Total capacity (kN/m²)",
    render: (r) => r.total_plate_capacity.toFixed(2),
  },
  {
    key: "unity_factor",
    header: "Unity factor",
    render: (r) => r.utilization_factor.toFixed(2),
  },
];

export function TimeSeriesTable({ rows }: { rows: TimeSeriesRow[] }) {
  const [expanded, setExpanded] = useState(false);
  if (!rows || rows.length === 0) {
    return null;
  }
  const columns = expanded ? FULL_REPORT_COLUMNS : SUMMARY_COLUMNS;
  return (
    <section className="mt-6 overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 px-6 py-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Capacity vs time
        </h2>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="text-xs font-medium text-blue-700 hover:underline"
        >
          {expanded ? "Show fewer columns" : "Show all columns"}
        </button>
      </div>
      <div className="max-h-96 overflow-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr>
              {columns.map((col) => (
                <th
                  key={col.key}
                  className="px-4 py-2 text-left font-medium text-slate-700"
                >
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.time_step} className="border-t border-slate-100">
                {columns.map((col) => (
                  <td key={col.key} className="px-4 py-1 tabular-nums">
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
