import { useMemo } from "react";
import { Link, useParams } from "react-router-dom";

import type { Run } from "../api/client";
import { detectVaryingFields } from "../sweep/buildScatterTraces";
import { SweepScatter } from "../sweep/SweepScatter";
import { useSweepEvents } from "../sweep/useSweepEvents";
import { VARYABLE_PARAMS } from "../sweep/varyableParams";

export default function BatchProgressPage() {
  const { batch_id } = useParams<{ batch_id: string }>();
  const id = batch_id ?? "";
  const { runs, status, error, total, completed, errors } = useSweepEvents(id);

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
      <Link to="/" className="text-sm text-blue-700 hover:underline">
        ← Back to config
      </Link>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight">
        Batch {id}
      </h1>
      <p className="text-xs text-slate-500">{headerStatus}</p>

      <section className="mt-4 rounded-md border border-slate-200 bg-white p-4 shadow-sm">
        <div className="flex items-baseline justify-between text-sm">
          <span className="font-medium text-slate-700">
            {completed} of {totalLabel} complete
          </span>
          {errors > 0 && (
            <span className="text-rose-700">{errors} error{errors === 1 ? "" : "s"}</span>
          )}
        </div>
        <div className="mt-2 h-2 w-full overflow-hidden rounded bg-slate-100">
          <div
            className={`h-full ${
              status === "error" ? "bg-rose-600" : "bg-blue-600"
            }`}
            style={{ width: `${total ? percent : 0}%` }}
          />
        </div>
        {error && (
          <p className="mt-2 text-xs text-rose-700">{error}</p>
        )}
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

function BatchRunsTable({
  runs,
  varyingFields,
}: {
  runs: Run[];
  varyingFields: string[];
}) {
  if (runs.length === 0) {
    return (
      <p className="px-4 py-3 text-sm text-slate-500">No runs yet.</p>
    );
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
              "border-t border-slate-100 " +
              (run.error ? "bg-rose-50" : "")
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
