import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import type {
  BatchSummary,
  ExportMode,
  Run,
  ShearCheckResponse,
} from "../api/client";
import {
  fetchDataExportZip,
  getBatch,
  getReportDocxUrl,
  getShearCheck,
  saveBlob,
} from "../api/client";

const EXPORT_HINTS: Record<ExportMode, string> = {
  data: "Every run as CSVs, plus a script that plots them",
  charts: "The four standard charts as PNGs",
  both: "The CSVs and the rendered charts",
};
import { BatchHeading } from "../components/BatchHeading";
import { BatchSetupPanel } from "../components/BatchSetupPanel";
import PdfEvidencePanel from "../components/PdfEvidencePanel";
import { batchLabel } from "../lib/batchLabel";
import { governingCriticalTemp } from "../lib/governingCriticalTemp";
import { detectVaryingFields } from "../sweep/buildScatterTraces";
import { DistributionChart } from "../sweep/DistributionChart";
import { MacsScatter } from "../sweep/MacsScatter";
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
  // `batch` is null for a still-unknown / legacy id — the live view degrades
  // to the raw id in that case.
  return <LiveProgressView batchId={id} batch={batch ?? null} />;
}

function LiveProgressView({
  batchId,
  batch,
}: {
  batchId: string;
  batch: BatchSummary | null;
}) {
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
        {batch ? batchLabel(batch) : `Batch ${batchId}`}
      </h1>
      <p className="text-xs text-slate-500">
        {batch?.project_name?.trim() && (
          <>
            <span className="font-medium text-slate-700">
              {batch.project_name}
            </span>
            {" · "}
          </>
        )}
        <span className="font-mono">{batchId}</span>
        {" · "}
        {headerStatus}
      </p>

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

      {/* Gated on the first run landing — the setup is derived from stored
          runs, so before then there is nothing to derive it from. The
          "shared across N runs" caption keeps a mid-sweep range honest. */}
      {runs.length > 0 && <BatchSetupPanel batchId={batchId} />}

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

  // The MACS+ scatter (chart 1) is only informative when at least one of
  // its two axes varies across the batch. When the sweep varies neither
  // qf nor window_percent the points collapse to a single cluster — hide
  // it entirely and just show the three distribution charts.
  const scatterAxesVary = useMemo(
    () => detectVaryingFields(runs, ["qf", "window_percent"]).length > 0,
    [runs],
  );

  const [docxUrl, setDocxUrl] = useState<string | null>(null);
  const [exportMode, setExportMode] = useState<ExportMode>("data");
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [savedName, setSavedName] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getReportDocxUrl(batch.batch_id)
      .then((docx) => {
        if (!cancelled) setDocxUrl(docx);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [batch.batch_id]);

  // Tick a visible counter while the sidecar builds the ZIP. There is no
  // server-side progress to report — the work is one long matplotlib render —
  // so elapsed time is the honest signal that something is still happening.
  useEffect(() => {
    if (!exporting) return;
    setElapsed(0);
    const started = Date.now();
    const id = setInterval(
      () => setElapsed(Math.round((Date.now() - started) / 1000)),
      1000,
    );
    return () => clearInterval(id);
  }, [exporting]);

  async function runExport() {
    setExporting(true);
    setExportError(null);
    setSavedName(null);
    try {
      const file = await fetchDataExportZip(batch.batch_id, exportMode);
      saveBlob(file);
      // The webview saves silently — no download bar, no dialog — so say so
      // explicitly or the spinner just disappears and nothing seems to happen.
      setSavedName(file.filename);
    } catch (e) {
      setExportError(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="mx-auto max-w-6xl p-8">
      <Link to="/runs" className="text-sm text-blue-700 hover:underline">
        ← Back to history
      </Link>
      <header className="mt-2 flex flex-wrap items-baseline justify-between gap-3">
        <BatchHeading batch={batch} />
        <div className="flex items-center gap-2">
          <div className="flex items-stretch overflow-hidden rounded-md bg-slate-200">
            <label className="sr-only" htmlFor="export-mode">
              What to download
            </label>
            <select
              id="export-mode"
              value={exportMode}
              disabled={exporting}
              onChange={(e) => setExportMode(e.target.value as ExportMode)}
              className="border-r border-slate-300 bg-slate-200 px-2 py-1.5 text-sm font-medium text-slate-800 hover:bg-slate-300 disabled:text-slate-400"
            >
              <option value="data">Data (CSV)</option>
              <option value="charts">Charts (PNG)</option>
              <option value="both">Data + charts</option>
            </select>
            <button
              type="button"
              onClick={runExport}
              disabled={exporting}
              aria-busy={exporting}
              title={EXPORT_HINTS[exportMode]}
              className="flex items-center gap-2 px-3 py-1.5 text-sm font-medium text-slate-800 hover:bg-slate-300 disabled:text-slate-500"
            >
              {exporting ? (
                <>
                  <span
                    role="status"
                    aria-label="Preparing download"
                    className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-slate-400 border-t-transparent"
                  />
                  Preparing… {elapsed}s
                </>
              ) : (
                "Download"
              )}
            </button>
          </div>
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
          {batch.sampling === "paired" || batch.sampling === "lhs" ? (
            <Link
              to={`/?from_batch=${encodeURIComponent(batch.batch_id)}`}
              className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500"
            >
              Rerun batch
            </Link>
          ) : (
            <span
              title="Grid-mode sweep — rerun unsupported. Re-enter as paired."
              className="cursor-not-allowed rounded-md bg-slate-200 px-3 py-1.5 text-sm font-medium text-slate-400"
            >
              Rerun batch
            </span>
          )}
        </div>
      </header>

      <PdfEvidencePanel
        batchId={batch.batch_id}
        runCount={batch.run_count}
        seedName={batch.frc?.filename ?? null}
      />

      {exportError ? (
        <p
          role="alert"
          className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800"
        >
          Download failed: {exportError}
        </p>
      ) : null}

      {savedName ? (
        <p
          aria-live="polite"
          data-testid="download-saved"
          className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900"
        >
          Saved <span className="font-medium">{savedName}</span> to your
          Downloads folder.
        </p>
      ) : null}

      <BatchSetupPanel batchId={batch.batch_id} />

      <ShearConnectionPanel batchId={batch.batch_id} />

      {/* MACS+ Monte Carlo Simulation Output Summary — 4 charts. */}
      <section className="mt-6 grid gap-4 md:grid-cols-2">
        {scatterAxesVary && (
          <div
            data-chart="macs-scatter"
            className="rounded-md border border-slate-200 bg-white p-4 shadow-sm"
          >
            <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Fire Load Density vs Glazing Breakage
            </h2>
            <MacsScatter runs={runs} />
          </div>
        )}
        <DistributionChart
          batchId={batch.batch_id}
          column="total_plate_capacity"
          title="Total Capacity Distribution"
          yLabel="Total Slab Capacity (kN/m²)"
        />
        <DistributionChart
          batchId={batch.batch_id}
          column="lofl_temp"
          title="Unprotected Beam Temperature Distribution"
          yLabel="Temperature (°C)"
        />
        <DistributionChart
          batchId={batch.batch_id}
          column="mesh_temp"
          title="Reinforcement Bar Temperature Distribution"
          yLabel="Temperature (°C)"
        />
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

/** Mirrors the MACS+ "Beam checks" warning: flags runs whose degree of shear
 *  connection falls below the EN 1994-1-1 minimum. Advisory only — it does not
 *  affect the pass/fail verdict (same as MACS+, which warns and still runs). */
function ShearConnectionPanel({ batchId }: { batchId: string }) {
  const { data } = useQuery<ShearCheckResponse>({
    queryKey: ["shear-check", batchId],
    queryFn: () => getShearCheck(batchId),
    enabled: batchId.length > 0,
  });

  if (!data) return null;

  const flaggedRuns = data.sub_limit_runs;
  if (flaggedRuns.length === 0) {
    return (
      <section className="mt-4 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm text-emerald-800">
        Degree of shear connection: all checked beams meet the EN 1994-1-1
        minimum.
      </section>
    );
  }

  const beamCount = flaggedRuns.reduce((n, r) => n + r.flags.length, 0);
  return (
    <section className="mt-4 rounded-md border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900">
      <h2 className="font-semibold">
        Degree of shear connection below the EN 1994-1-1 minimum
      </h2>
      <p className="mt-1 text-amber-800">
        {flaggedRuns.length} run{flaggedRuns.length === 1 ? "" : "s"} ({beamCount}{" "}
        beam{beamCount === 1 ? "" : "s"}) fall below the minimum. MACS+ raises the
        same warning — it is advisory and does not change the pass/fail verdict.
      </p>
      <ul className="mt-2 space-y-1">
        {flaggedRuns.map((r) => (
          <li key={r.run_id} className="tabular-nums">
            <Link
              to={`/runs/${r.run_id}`}
              className="font-medium text-blue-700 hover:underline"
            >
              #{r.run_id}
            </Link>
            {": "}
            {r.flags
              .map((f) => `${f.beam} ${f.sh_con}% (min ${f.eta_min_pct}%)`)
              .join(", ")}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Governing (lowest) perimeter-beam critical temp with its side, e.g.
 *  "690 (B)" — the per-run value the reliability study's override wants. */
function GoverningTempCell({ run }: { run: Run }) {
  const gov = governingCriticalTemp(run);
  if (!gov) return <>—</>;
  return (
    <>
      {gov.temp.toFixed(0)} ({gov.side})
    </>
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
          <th
            className="px-4 py-2 text-left font-medium text-slate-700"
            title="Governing perimeter-beam critical temperature (side in brackets)"
          >
            Crit. temp (°C)
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
            <td className="px-4 py-1 tabular-nums">
              <GoverningTempCell run={run} />
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
