/**
 * The configuration shared by every run in a batch.
 *
 * Answers "what setup produced these results?" — the question you ask when
 * reviewing someone else's batch, or your own months later. It reads from the
 * stored runs rather than the submitted spec, so a batch configured by hand in
 * the form is as legible as one seeded from a .frc, and batches predating
 * `config_json` still have a setup to show.
 *
 * Inputs that varied across the batch are listed alongside the shared ones,
 * marked and summarised as a range — leaving them out would imply the batch is
 * more uniform than it is.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import type { SetupField } from "../api/client";
import { getBatchSetup } from "../api/client";

/** Trim float noise without hiding genuine precision (9.0 → "9", 0.85 → "0.85"). */
function formatValue(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return String(Number(v.toPrecision(6)));
  return String(v);
}

function withUnit(text: string, unit: string): string {
  return unit ? `${text} ${unit}` : text;
}

function FieldRow({ field }: { field: SetupField }) {
  let detail: string;
  if (!field.varies) {
    detail = withUnit(formatValue(field.value), field.unit);
  } else if (field.min !== undefined && field.max !== undefined) {
    detail = withUnit(
      `${formatValue(field.min)}–${formatValue(field.max)}`,
      field.unit,
    );
  } else {
    detail = (field.values ?? []).map(formatValue).join(", ");
  }

  return (
    <div
      data-testid={`setup-${field.key}`}
      data-varies={String(field.varies)}
      className="flex items-baseline justify-between gap-3 border-b border-slate-50 py-1 last:border-0"
    >
      <span className="text-slate-600">{field.label}</span>
      <span className="text-right">
        <span
          className={
            field.varies
              ? "font-medium tabular-nums text-blue-800"
              : "font-medium tabular-nums text-slate-800"
          }
        >
          {detail}
        </span>
        {field.varies && field.distinct !== undefined && (
          <span className="ml-2 rounded bg-blue-50 px-1.5 py-0.5 text-xs text-blue-800">
            {field.distinct} values
          </span>
        )}
      </span>
    </div>
  );
}

export function BatchSetupPanel({ batchId }: { batchId: string }) {
  const [open, setOpen] = useState(true);
  const setupQuery = useQuery({
    queryKey: ["batch-setup", batchId],
    queryFn: () => getBatchSetup(batchId),
    enabled: batchId.length > 0,
  });

  // Tolerate a payload without `groups` rather than letting one unexpected
  // response take down the whole batch page with it.
  const setup = setupQuery.data;
  const groups = setup?.groups ?? [];

  return (
    <section className="mt-6 overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between border-b border-slate-100 px-4 py-2 text-left"
      >
        <span className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Setup
          {setup && (setup.run_count ?? 0) > 0 && (
            <span className="ml-2 font-normal normal-case tracking-normal text-slate-400">
              shared across {setup.run_count} run
              {setup.run_count === 1 ? "" : "s"}
            </span>
          )}
        </span>
        <span aria-hidden className="text-slate-400">
          {open ? "▾" : "▸"}
        </span>
      </button>

      {open && (
        <div className="px-4 py-3 text-sm">
          {setupQuery.isLoading && (
            <p className="text-slate-500">Loading setup…</p>
          )}
          {setupQuery.isError && (
            <p role="alert" className="text-rose-700">
              {(setupQuery.error as Error).message}
            </p>
          )}
          {setup && groups.length === 0 && (
            <p className="text-slate-500">
              No runs recorded yet — the setup appears once the first run lands.
            </p>
          )}
          {setup && groups.length > 0 && (
            <div className="grid gap-x-8 gap-y-4 md:grid-cols-2">
              {groups.map((group) => (
                <div key={group.title}>
                  <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-400">
                    {group.title}
                  </h3>
                  {group.fields.map((f) => (
                    <FieldRow key={f.key} field={f} />
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
