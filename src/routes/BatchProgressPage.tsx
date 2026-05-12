import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import type { BatchSummary, Run } from "../api/client";
import {
  getBatch,
  getReportChartUrl,
  getReportDocxUrl,
} from "../api/client";
import { detectVaryingFields } from "../sweep/buildScatterTraces";
import { SweepScatter } from "../sweep/SweepScatter";
import { useSweepEvents } from "../sweep/useSweepEvents";
import { VARYABLE_PARAMS } from "../sweep/varyableParams";

export default function BatchProgressPage() {
  const { batch_id } = useParams<{ batch_id: string }>();
  const id = batch_id ?? "";

  // The batch summary tells us whether to render the live-progress view or
  // the analytical view. A 404 (legacy batch / unknown id) is degraded to
  // "render live view" — that path still works via SSE backfill.
  const batchQuery = useQuery<BatchSummary | null>({
    queryKey: ["batch", id],
    queryFn: async () => {
      try {
        return await getBatch(id);
      } catch {
        return null;
      }
    },
    enabled: id.length > 0,
  });

  const batch = batchQuery.data;
  const isAnalytical =
    !!batch &&
    batch.total_expected > 0 &&
    batch.run_count >= batch.total_expected;

  if (isAnalytical && batch) {
    return <AnalyticalView batch={batch} />;
  }
  return <LiveProgressView batchId={id} />;
}

function LiveProgressView({ batchId }: { batchId: string }) {
  const { runs, status, error, total, completed, errors } =
    useSweepEvents(batchId);

  const candidateNames = useMemo(
    () => VARYABLE_PARAMS.map((p) => p.name),
    [],
  );
  const varyingFields = useMemo(
    () => detectVaryingFields(runs, candidateNames),
    [runs, candidateNames],
  );

  const totalLabel = total !== null ? String(total) : "?";
  const percent = total && total > 0 ? Math.round((completed / total) * 100) : 0;
  const headerStatus =
    status === "loading"
      ? "Loading…"
      : status === "streaming"
        ? "Running"
        : status === "closed"
          ? "Complete"
          : "Error";

  return (
    <div className="mx-auto max-w-5xl p-8">
      <Link to="/runs" className="text-sm text-blue-700 hover:underline">
        ← Back to history
      </Link>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight">
        Batch {batchId}
      </h1>
      <p className="text-xs text-slate-500">{headerStatus}</p>

      <section className="mt-4 rounded-md border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-baseline justify-between text-sm">
          <span className="font-medium text-slate-700">
            {completed} of {totalLabel} complete
          </span>
          {errors > 0 && (
            <span className="text-rose-700">
              {errors} error{errors === 1 ? "" : "s"}
            </span>
          )}
        </div>
        <div className="mt-2 h-2 w-full overflow-hidden rounded bg-slate-100">
          <div
            className={`h-full ${status === "error" ? "bg-rose-600" : "bg-blue-600"}`}
            style={{ width: `${total ? percent : 0}%` }}
          />
        </div>
        {error && <p className="mt-2 text-xs text-rose-700">{error}</p>}
      </section>

      <section className="mt-6 rounded-md border border-slate-200 bg-white p-4 shadow-sm">
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Trend
        </h2>
        <SweepScatter
          runs={runs}
          varyingX={varyingFields[0] ?? null}
          varyingColor={varyingFields[1] ?? null}
        />
      </section>

      <section className="mt-6 overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm">
        <h2 className="border-b border-slate-100 px-4 py-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Runs
        </h2>
        <div className="max-h-96 overflow-auto">
          <BatchRunsTable runs={runs} varyingFields={varyingFields} />
        </div>
      </section>
    </div>
  );
}

function AnalyticalView({ batch }: { batch: BatchSummary }) {
  // Backfill from /api/runs?batch_id=<id> through the existing hook (it
  // also opens an EventSource, but for a completed batch the stream stays
  // empty and closes cheaply once the server-side iterator wakes up).
  const { runs } = useSweepEvents(batch.batch_id);

  const varyingNames = useMemo(
    () => Object.keys(batch.varying_params ?? {}),
    [batch.varying_params],
  );
  const candidateNames = useMemo(
    () =>
      varyingNames.length > 0
        ? varyingNames
        : VARYABLE_PARAMS.map((p) => p.name),
    [varyingNames],
  );
  const varyingFields = useMemo(
    () => detectVaryingFields(runs, candidateNames),
    [runs, candidateNames],
  );

  const [docxUrl, setDocxUrl] = useState<string | null>(null);
  const [scatterUrl, setScatterUrl] = useState<string | null>(null);
  const [capacityUrl, setCapacityUrl] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      getReportDocxUrl(batch.batch_id),
      getReportChartUrl("scatter", batch.batch_id),
      getReportChartUrl("capacity", batch.batch_id),
    ])
      .then(([d, s, c]) => {
        if (cancelled) return;
        setDocxUrl(d);
        setScatterUrl(s);
        setCapacityUrl(c);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [batch.batch_id]);

  return (
    <div className="mx-auto max-w-6xl p-8">
      <Link to="/runs" className="text-sm text-blue-700 hover:underline">
        ← Back to history
      </Link>
      <header className="mt-2 flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Batch {batch.batch_id}
          </h1>
          <p className="text-xs text-slate-500">
            {batch.run_count} runs ·{" "}
            <span className="text-emerald-700">{batch.pass_count} pass</span> ·{" "}
            <span className="text-amber-700">{batch.fail_count} fail</span> ·{" "}
            <span className="text-rose-700">{batch.error_count} error</span>
          </p>
        </div>
        <div className="flex items-center gap-2">
          {docxUrl ? (
            <a
              href={docxUrl}
              className="rounded-md bg-slate-200 px-3 py-1.5 text-sm font-medium text-slate-800 hover:bg-slate-300"
            >
              Download report
            </a>
          ) : (
            <span className="rounded-md bg-slate-100 px-3 py-1.5 text-sm font-medium text-slate-400">
              Download report
            </span>
          )}
          <Link
            to={`/?from_batch=${encodeURIComponent(batch.batch_id)}`}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500"
          >
            Rerun batch
          </Link>
        </div>
      </header>

      <section className="mt-6 grid gap-4 md:grid-cols-2">
        <div className="rounded-md border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
            UF max vs {varyingFields[0] ?? "input"}
          </h2>
          <SweepScatter
            runs={runs}
            varyingX={varyingFields[0] ?? null}
            varyingColor={varyingFields[1] ?? null}
          />
          {scatterUrl && runs.length === 0 && (
            <img src={scatterUrl} alt="UF max scatter" className="w-full" />
          )}
        </div>
        <div className="rounded-md border border-slate-200 bg-white p-4 shadow-sm">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Total slab capacity
          </h2>
          {capacityUrl ? (
            <img src={capacityUrl} alt="Capacity over time" className="w-full" />
          ) : (
            <p className="text-sm text-slate-400">Loading capacity chart…</p>
          )}
        </div>
      </section>

      <section className="mt-6 overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm">
        <h2 className="border-b border-slate-100 px-4 py-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Runs
        </h2>
        <div className="max-h-[28rem] overflow-auto">
          <BatchRunsTable runs={runs} varyingFields={varyingFields} />
        </div>
      </section>
    </div>
  );
}

function BatchRunsTable({
  runs,
  varyingFields,
}: {
  runs: Run[];
  varyingFields: string[];
}) {
  if (runs.length === 0) {
    return <p className="px-4 py-3 text-sm text-slate-500">No runs yet.</p>;
  }
  return (
    <table className="w-full text-sm">
      <thead className="bg-slate-50">
        <tr>
          <th className="px-4 py-2 text-left font-medium text-slate-700">Run</th>
          {varyingFields.map((f) => (
            <th
              key={f}
              className="px-4 py-2 text-left font-medium text-slate-700"
            >
              {f}
            </th>
          ))}
          <th className="px-4 py-2 text-left font-medium text-slate-700">
            UF max
          </th>
          <th className="px-4 py-2 text-left font-medium text-slate-700">
            Status
          </th>
        </tr>
      </thead>
      <tbody>
        {runs.map((run) => (
          <tr
            key={run.id}
            className={
              "border-t border-slate-100 " + (run.error ? "bg-rose-50" : "")
            }
          >
            <td className="px-4 py-1">
              <Link
                to={`/runs/${run.id}`}
                className="text-blue-700 hover:underline"
              >
                #{run.id}
              </Link>
            </td>
            {varyingFields.map((f) => (
              <td key={f} className="px-4 py-1 tabular-nums">
                {String((run as Record<string, unknown>)[f] ?? "—")}
              </td>
            ))}
            <td className="px-4 py-1 tabular-nums">
              {run.uf_max != null ? run.uf_max.toFixed(3) : "—"}
            </td>
            <td className="px-4 py-1">
              {run.error ? (
                <span className="text-rose-700">Error</span>
              ) : run.overall_pass ? (
                <span className="text-emerald-700">Pass</span>
              ) : (
                <span className="text-amber-700">Fail</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
