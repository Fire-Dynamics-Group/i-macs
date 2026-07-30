/**
 * Replay a completed batch through MACS+ itself, producing one genuine vendor
 * PDF per run.
 *
 * The host check is shown up front rather than on failure: the display-scaling
 * trap produces correct numbers with silently squashed charts, so a run can
 * "succeed" and still be worthless. Better to see it before committing hours.
 */
import { useCallback, useEffect, useState } from "react";
import {
  getPdfEvidenceStatus,
  getReplayHostCheck,
  startPdfEvidence,
  stopPdfEvidence,
  type HostCheck,
  type PdfEvidenceStatus,
} from "../api/client";

const SECONDS_PER_RUN = 4.5;

function humanDuration(seconds: number): string {
  if (seconds < 90) return `${Math.round(seconds)}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

export default function PdfEvidencePanel({
  batchId,
  runCount,
}: {
  batchId: string;
  runCount: number;
}) {
  const [open, setOpen] = useState(false);
  const [host, setHost] = useState<HostCheck | null>(null);
  const [hostError, setHostError] = useState<string | null>(null);
  const [status, setStatus] = useState<PdfEvidenceStatus | null>(null);
  const [scope, setScope] = useState<"all" | "sample">("all");
  // Kept as text so an emptied box stays empty rather than reading as 0.
  const [sampleText, setSampleText] = useState("200");
  const [outDir, setOutDir] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setStatus(await getPdfEvidenceStatus(batchId));
    } catch {
      /* transient - the poll will retry */
    }
  }, [batchId]);

  useEffect(() => {
    if (!open) return;
    if (host === null && hostError === null) {
      getReplayHostCheck()
        .then(setHost)
        .catch((e) => setHostError(e instanceof Error ? e.message : String(e)));
    }
    void refresh();
  }, [open, host, hostError, refresh]);

  // Poll only while a job is live; an 11-hour run must not depend on this page
  // staying open, so the backend owns the state and this is just a view of it.
  useEffect(() => {
    if (!open || !status?.active) return;
    const id = setInterval(refresh, 3000);
    return () => clearInterval(id);
  }, [open, status?.active, refresh]);

  // A sample bigger than the batch is a typo, not a request for extra runs.
  const typedSample = Number(sampleText);
  const sampleValid =
    sampleText.trim() !== "" && Number.isFinite(typedSample) && typedSample >= 1;
  const sampleSize = Math.min(Math.floor(typedSample), runCount);
  const planned = scope === "all" ? runCount : sampleValid ? sampleSize : 0;
  const running = status?.active === true;
  // An unanswered host check is not a passing one, so anything short of a
  // confirmed pass blocks: the scaling trap yields correct numbers with
  // silently squashed charts, which is worse than an outright failure.
  const blocked = host?.ok !== true || (scope === "sample" && !sampleValid);

  // The PDFs are the deliverable and they land outside the app, so the path
  // needs to be reachable rather than a string to retype into Explorer.
  async function openFolder() {
    if (!status?.output_dir) return;
    try {
      const { revealItemInDir } = await import("@tauri-apps/plugin-opener");
      await revealItemInDir(status.output_dir);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function chooseFolder() {
    try {
      const { open: openPicker } = await import("@tauri-apps/plugin-dialog");
      const picked = await openPicker({ directory: true, multiple: false });
      if (typeof picked === "string") setOutDir(picked);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function run(sample: number | undefined) {
    setError(null);
    try {
      const res = await startPdfEvidence(batchId, sample, outDir ?? undefined);
      if (res.error) setError(res.error);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const begin = () => run(scope === "all" ? undefined : sampleSize);
  // Resume over the same runs the paused job covered: a different sample would
  // export a different set, and the PDFs already on disk would not line up.
  const resume = () => run(status?.sample ?? undefined);

  async function pause() {
    setError(null);
    try {
      const res = await stopPdfEvidence(batchId);
      if (res.error) setError(res.error);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-md bg-slate-200 px-3 py-1.5 text-sm font-medium text-slate-800 hover:bg-slate-300"
      >
        MACS+ PDF evidence
      </button>
    );
  }

  return (
    <section className="mt-6 rounded-lg border border-slate-300 bg-white p-4">
      <div className="flex items-baseline justify-between">
        <h2 className="text-base font-semibold text-slate-900">MACS+ PDF evidence</h2>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="text-sm text-slate-500 hover:underline"
        >
          Hide
        </button>
      </div>
      <p className="mt-1 text-sm text-slate-600">
        Replays each run through MACS+ itself and saves the report it prints, so the batch
        has vendor PDFs on file. The numbers already come from MACS's engine — this adds
        its presentation and an audit trail.
      </p>

      {hostError && (
        <div className="mt-3 rounded-md border border-red-300 bg-red-50 p-3 text-sm">
          <p className="font-medium">Could not check this machine.</p>
          <p className="mt-1 text-slate-700">{hostError}</p>
        </div>
      )}

      {host && (
        <div
          className={`mt-3 rounded-md border p-3 text-sm ${
            host.ok ? "border-green-300 bg-green-50" : "border-red-300 bg-red-50"
          }`}
        >
          <p className="font-medium">
            {host.ok ? "This machine is set up correctly." : "This machine is not ready."}
          </p>
          {!host.ok && (
            <pre className="mt-2 overflow-x-auto whitespace-pre-wrap text-xs text-slate-700">
              {host.lines.join("\n")}
            </pre>
          )}
        </div>
      )}

      {running ? (
        <div className="mt-3">
          <div className="h-2 w-full overflow-hidden rounded bg-slate-200">
            <div
              className="h-full bg-blue-600 transition-all"
              style={{
                width: `${status.total ? (status.completed / status.total) * 100 : 0}%`,
              }}
            />
          </div>
          <p className="mt-2 text-sm text-slate-700">
            {status.completed} of {status.total} PDFs
            {status.eta_s !== null && ` — about ${humanDuration(status.eta_s)} remaining`}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Leave the app running and signed in. MACS+ windows will open and close; you can
            keep working, they do not take focus.
          </p>
          <div className="mt-2 flex items-center gap-3">
            <button
              type="button"
              onClick={pause}
              disabled={status.stopping}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:text-slate-400"
            >
              {status.stopping ? "Pausing…" : "Pause"}
            </button>
            {status.stopping && (
              <span className="text-sm text-slate-600">
                Finishing the current run, then stopping — this frees MACS+ and puts your
                default printer back.
              </span>
            )}
          </div>
        </div>
      ) : status?.resumable ? (
        <div className="mt-3">
          <div className="h-2 w-full overflow-hidden rounded bg-slate-200">
            <div
              className="h-full bg-amber-500"
              style={{ width: `${(status.completed / status.total) * 100}%` }}
            />
          </div>
          <p className="mt-2 text-sm text-slate-700">
            Paused — {status.completed} of {status.total} PDFs done.
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={resume}
              disabled={host?.ok !== true}
              className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-slate-300 disabled:text-slate-500"
            >
              Resume
            </button>
            <span className="text-sm text-slate-500">
              Picks up where it stopped; ~
              {humanDuration((status.total - status.completed) * SECONDS_PER_RUN)} left.
            </span>
          </div>
        </div>
      ) : (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              checked={scope === "all"}
              onChange={() => setScope("all")}
            />
            All {runCount.toLocaleString()} runs
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              checked={scope === "sample"}
              onChange={() => setScope("sample")}
            />
            Auditable sample of
            <input
              type="number"
              min={1}
              max={runCount}
              value={sampleText}
              onChange={(e) => setSampleText(e.target.value)}
              className="w-20 rounded border border-slate-300 px-2 py-1 text-sm"
            />
          </label>
          <button
            type="button"
            onClick={begin}
            disabled={blocked}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:bg-slate-300 disabled:text-slate-500"
          >
            Generate
          </button>
          {planned > 0 && (
            <span className="text-sm text-slate-500">
              ~{humanDuration(planned * SECONDS_PER_RUN)}, ~
              {((planned * 0.45) / 1024).toFixed(1)} GB
            </span>
          )}
          {/* A 10k batch is ~4.2 GB, which often wants a drive other than C:. */}
          <div className="flex w-full items-center gap-2 text-sm text-slate-600">
            <span>Save to</span>
            <code className="rounded bg-slate-100 px-1 text-xs">
              {outDir ?? "the app's own folder"}
            </code>
            <button
              type="button"
              onClick={chooseFolder}
              className="rounded border border-slate-300 px-2 py-0.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
            >
              Choose folder
            </button>
            {outDir && (
              <button
                type="button"
                onClick={() => setOutDir(null)}
                className="text-xs text-slate-500 hover:underline"
              >
                Reset
              </button>
            )}
          </div>
        </div>
      )}

      {status?.error && (
        <p className="mt-3 rounded-md border border-red-300 bg-red-50 p-2 text-sm text-red-800">
          {status.error}
        </p>
      )}
      {error && (
        <p className="mt-3 rounded-md border border-red-300 bg-red-50 p-2 text-sm text-red-800">
          {error}
        </p>
      )}
      {status?.output_dir && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-slate-600">
          <span>
            {running
              ? "Saving to"
              : `${status.completed} PDF${status.completed === 1 ? "" : "s"} in`}
          </span>
          <code className="rounded bg-slate-100 px-1 text-xs">{status.output_dir}</code>
          <button
            type="button"
            onClick={openFolder}
            className="rounded border border-slate-300 px-2 py-0.5 text-xs font-medium text-slate-700 hover:bg-slate-100"
          >
            Open folder
          </button>
        </div>
      )}
    </section>
  );
}
