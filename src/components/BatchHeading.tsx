/**
 * Batch detail heading: human-friendly name, project, and the .frc the batch
 * was seeded from — with inline rename.
 *
 * Renaming after the fact matters more than naming up front: you rarely know
 * what to call a batch until you've seen its results. The full batch id stays
 * on screen regardless, since it's what report filenames and support requests
 * key on.
 */

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { BatchSummary } from "../api/client";
import { getFrcImport, renameBatch } from "../api/client";
import { batchLabel, frcLabel } from "../lib/batchLabel";

export function BatchHeading({ batch }: { batch: BatchSummary }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(batch.name ?? "");
  const [projectName, setProjectName] = useState(batch.project_name ?? "");
  const [frcError, setFrcError] = useState<string | null>(null);

  const rename = useMutation({
    mutationFn: () =>
      renameBatch(batch.batch_id, {
        name: name.trim(),
        project_name: projectName.trim(),
      }),
    onSuccess: () => {
      setEditing(false);
      void queryClient.invalidateQueries({ queryKey: ["batch", batch.batch_id] });
      void queryClient.invalidateQueries({ queryKey: ["batches"] });
      void queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
  });

  const openEditor = () => {
    // Re-seed from the batch so a cancelled edit doesn't linger.
    setName(batch.name ?? "");
    setProjectName(batch.project_name ?? "");
    rename.reset();
    setEditing(true);
  };

  const heading = useMemo(() => batchLabel(batch), [batch]);

  /** Save the stored .frc to disk. Held in memory (a few KB), so a Blob URL
   *  is simpler than routing the download through the sidecar. */
  const downloadFrc = async () => {
    if (!batch.frc) return;
    setFrcError(null);
    try {
      const stored = await getFrcImport(batch.frc.id);
      const url = URL.createObjectURL(
        new Blob([stored.xml], { type: "application/xml" }),
      );
      const a = document.createElement("a");
      a.href = url;
      a.download = stored.filename ?? "imported.frc";
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setFrcError(
        err instanceof Error ? err.message : "Couldn't fetch the stored .frc",
      );
    }
  };

  return (
    <div>
      {editing ? (
        <div className="flex flex-wrap items-end gap-2">
          <label className="block">
            <span className="text-xs font-medium text-slate-600">
              Batch name
            </span>
            <input
              type="text"
              value={name}
              autoFocus
              onChange={(e) => setName(e.target.value)}
              placeholder="Leave blank to show the id"
              data-testid="rename-name-input"
              className="mt-0.5 block w-64 rounded border border-slate-300 px-2 py-1 text-sm"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-slate-600">Project</span>
            <input
              type="text"
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              data-testid="rename-project-input"
              className="mt-0.5 block w-64 rounded border border-slate-300 px-2 py-1 text-sm"
            />
          </label>
          <button
            type="button"
            onClick={() => rename.mutate()}
            disabled={rename.isPending}
            className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500 disabled:bg-slate-300"
          >
            {rename.isPending ? "Saving…" : "Save"}
          </button>
          <button
            type="button"
            onClick={() => setEditing(false)}
            className="rounded-md bg-slate-200 px-3 py-1.5 text-sm font-medium text-slate-800 hover:bg-slate-300"
          >
            Cancel
          </button>
        </div>
      ) : (
        <div className="flex items-baseline gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">{heading}</h1>
          <button
            type="button"
            onClick={openEditor}
            className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-100"
          >
            Rename
          </button>
        </div>
      )}

      {rename.isError && (
        <p role="alert" className="mt-1 text-xs text-rose-700">
          {rename.error instanceof Error
            ? rename.error.message
            : "Rename failed"}
        </p>
      )}

      <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
        {batch.project_name?.trim() && (
          <>
            <span className="font-medium text-slate-700">
              {batch.project_name}
            </span>
            <span aria-hidden>·</span>
          </>
        )}
        <span className="font-mono">{batch.batch_id}</span>
        {batch.frc && (
          <>
            <span aria-hidden>·</span>
            <span data-testid="frc-source">
              seeded from{" "}
              <button
                type="button"
                onClick={() => void downloadFrc()}
                title="Save a copy of the original .frc"
                className="font-mono text-blue-700 hover:underline"
              >
                {frcLabel(batch.frc)}
              </button>
            </span>
          </>
        )}
      </p>

      {frcError && (
        <p role="alert" className="mt-1 text-xs text-rose-700">
          {frcError}
        </p>
      )}

      <p className="mt-1 text-xs text-slate-500">
        {batch.run_count} runs ·{" "}
        <span className="text-emerald-700">{batch.pass_count} pass</span> ·{" "}
        <span className="text-amber-700">{batch.fail_count} fail</span> ·{" "}
        <span className="text-rose-700">{batch.error_count} error</span>
      </p>
    </div>
  );
}
