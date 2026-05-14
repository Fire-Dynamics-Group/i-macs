import { useParams, Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import { getRun, getRunTimeseries, type Run, type TimeSeriesRow } from "../api/client";
import { CheckBreakdown } from "../components/CheckBreakdown";
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
        <h1 className="text-2xl font-semibold tracking-tight">Run #{runId}</h1>
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

function toNumber(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function RunSummary({ run }: { run: Run }) {
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
          </div>
        </>
      )}
    </section>
  );
}

function TimeSeriesTable({ rows }: { rows: TimeSeriesRow[] }) {
  if (!rows || rows.length === 0) {
    return null;
  }
  return (
    <section className="mt-6 overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm">
      <h2 className="border-b border-slate-100 px-6 py-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Capacity vs time
      </h2>
      <div className="max-h-96 overflow-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-4 py-2 text-left font-medium text-slate-700">Time (min)</th>
              <th className="px-4 py-2 text-left font-medium text-slate-700">Fire temp (°C)</th>
              <th className="px-4 py-2 text-left font-medium text-slate-700">UF</th>
              <th className="px-4 py-2 text-left font-medium text-slate-700">
                Total slab capacity (kN/m²)
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.time_step} className="border-t border-slate-100">
                <td className="px-4 py-1 tabular-nums">{row.time_min.toFixed(1)}</td>
                <td className="px-4 py-1 tabular-nums">{row.fire_temp.toFixed(0)}</td>
                <td className="px-4 py-1 tabular-nums">
                  {row.utilization_factor.toFixed(3)}
                </td>
                <td className="px-4 py-1 tabular-nums">
                  {row.total_plate_capacity.toFixed(1)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
