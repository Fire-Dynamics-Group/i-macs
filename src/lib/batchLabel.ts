/**
 * Display labels for batches and their .frc provenance.
 *
 * Batches were previously identified in the UI by a raw 32-char hex id. They
 * now carry an optional user-supplied name; everything that renders a batch
 * goes through `batchLabel` so the fallback to the short id stays consistent
 * (and legacy batches, which have no name at all, keep working).
 *
 * Pure functions — no React, no fetch — so they're unit-testable and shared by
 * the dashboard table, the batch detail header, and the run detail page.
 */

import type { FrcRef } from "../api/client";

/** First 8 chars of a batch id — the long-standing compact form. */
export function shortBatchId(batchId: string | undefined | null): string {
  return (batchId ?? "").slice(0, 8);
}

/** What to call a batch: its name, else its short id. */
export function batchLabel(batch: {
  batch_id: string;
  name?: string | null;
}): string {
  const name = batch.name?.trim();
  return name || shortBatchId(batch.batch_id);
}

/** What to call an imported .frc: its filename, else its project name. */
export function frcLabel(frc: FrcRef | null | undefined): string {
  if (!frc) return "";
  const filename = frc.filename?.trim();
  if (filename) return filename;
  const project = frc.project?.ProjectName?.trim();
  if (project) return project;
  return "imported .frc";
}

/** Placeholder text for the batch-name input — a hint at a useful name, not a
 *  value. Auto-filling would silently attach a machine-written label to work
 *  the user may well want to name themselves. */
export function suggestBatchName(
  varyingParams: string[],
  totalRuns: number,
): string {
  if (varyingParams.length === 0) return "";
  const shown = varyingParams.slice(0, 3).join(", ");
  const extra = varyingParams.length - 3;
  const params = extra > 0 ? `${shown} +${extra} more` : shown;
  return `${params} — ${totalRuns} run${totalRuns === 1 ? "" : "s"}`;
}
