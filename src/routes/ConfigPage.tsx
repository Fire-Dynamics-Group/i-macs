import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useForm, Controller, type SubmitHandler } from "react-hook-form";
import { useMutation, useQuery } from "@tanstack/react-query";

import {
  fetchHealth,
  fetchRefData,
  getBatch,
  getRun,
  importFrc,
  setInstallLocation,
  submitRun,
  submitSweep,
  type BatchSummary,
  type HealthResponse,
  type ImportFrcResponse,
  type RefData,
  type Run,
  type SubmitRunResponse,
  type SubmitSweepResponse,
} from "../api/client";
import { open as openDialog, message as showMessage } from "@tauri-apps/plugin-dialog";
import { checkForUpdates } from "../lib/updater";
import { hydrateFormFromRun } from "../lib/hydrateFormFromRun";
import { hydrateFormFromFrcParams } from "../lib/hydrateFormFromFrcParams";
import type { FrcHydrationResult } from "../lib/hydrateFormFromFrcParams";
import {
  SearchableSelect,
  type SearchableSelectOption,
} from "../components/SearchableSelect";
import { SweepConfigSection } from "../sweep/SweepConfigSection";
import { VARYABLE_PARAMS } from "../sweep/varyableParams";
import {
  buildSweepPayload,
  pairedValidation,
  toRequestBody,
  type ValueSource,
} from "../sweep/buildSweepPayload";
import type { FormValues } from "../types/formValues";

const FY_OPTIONS = ["235", "275", "355", "460"];

/** Label text with an optional "● Imported from .frc" blue dot. */
function FieldLabel({
  children,
  imported,
}: {
  children: React.ReactNode;
  imported?: boolean;
}) {
  return (
    <span className="text-sm font-medium text-slate-700">
      {imported && (
        <span
          aria-hidden
          title="Imported from .frc"
          className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-blue-500 align-middle"
          data-testid="frc-imported-dot"
        />
      )}
      {children}
      {imported && <span className="sr-only"> (imported from .frc)</span>}
    </span>
  );
}

const numberField = (
  label: string,
  name: keyof FormValues,
  register: ReturnType<typeof useForm<FormValues>>["register"],
  errors: ReturnType<typeof useForm<FormValues>>["formState"]["errors"],
  imported?: boolean,
) => (
  <label className="block">
    <FieldLabel imported={imported}>{label}</FieldLabel>
    <input
      type="number"
      step="any"
      {...register(name as never, { required: true, valueAsNumber: true })}
      className="mt-1 w-full rounded border border-slate-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
    />
    {errors[name] && (
      <span className="mt-1 block text-xs text-rose-600">Required</span>
    )}
  </label>
);

function flattenSections(refData: RefData): SearchableSelectOption[] {
  const out: SearchableSelectOption[] = [];
  for (const family of Object.keys(refData.sections)) {
    for (const sec of refData.sections[family]) {
      const depthStr = String(sec.h);
      const widthStr = String(sec.b);
      out.push({
        id: sec.id,
        label: `${sec.name} (${family})`,
        secondary: `${depthStr} × ${widthStr}`,
        searchTerms: [family, depthStr, widthStr],
      });
    }
  }
  return out;
}

export default function ConfigPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const fromRunParam = searchParams.get("from_run");
  const fromBatchParam = searchParams.get("from_batch");
  const fromRunId = fromRunParam ? Number(fromRunParam) : null;
  const fromBatchId = fromBatchParam || null;
  const refDataQuery = useQuery({
    queryKey: ["ref-data"],
    queryFn: fetchRefData,
  });

  // Issue #23: if Data.xml didn't resolve, show a banner offering to
  // locate the install manually. The native dialog at startup is the
  // primary surface; this banner is the in-app fallback for the
  // "Continue" path through that dialog.
  const healthQuery = useQuery<HealthResponse>({
    queryKey: ["healthz"],
    queryFn: fetchHealth,
    refetchOnWindowFocus: false,
  });
  const macsDetected =
    healthQuery.data === undefined ? true : healthQuery.data.macs_installed;
  const comRegistered =
    healthQuery.data === undefined ? true : healthQuery.data.com !== false;

  const locateMacs = async () => {
    try {
      const picked = await openDialog({
        directory: true,
        multiple: false,
        title: "Locate your MACS+ install folder (e.g. MACS+_304)",
      });
      if (!picked || typeof picked !== "string") return;
      const resp = await setInstallLocation(picked);
      if (resp.ok) {
        await showMessage(
          "MACS+ install location saved.\n\nPlease restart i-macs so the calculation engine picks up the new path.",
          { title: "MACS+ located", kind: "info" },
        );
        await healthQuery.refetch();
      } else {
        await showMessage(
          `That folder doesn't look like a MACS+ install:\n\n${resp.error ?? "unknown error"}\n\nA valid install contains EN\\Data\\Data.xml directly under it (e.g. C:\\Program Files (x86)\\MACS+_304\\).`,
          { title: "MACS+ folder not valid", kind: "warning" },
        );
      }
    } catch (err) {
      await showMessage(`Locate failed: ${err}`, {
        title: "MACS+ locate failed",
        kind: "error",
      });
    }
  };

  const fromRunQuery = useQuery<Run>({
    queryKey: ["run", fromRunId],
    queryFn: () => getRun(fromRunId as number),
    enabled: fromRunId !== null && Number.isFinite(fromRunId),
  });

  const fromBatchQuery = useQuery<BatchSummary>({
    queryKey: ["batch", fromBatchId],
    queryFn: () => getBatch(fromBatchId as string),
    enabled: fromBatchId !== null,
  });

  const sectionOptions = useMemo(
    () => (refDataQuery.data ? flattenSections(refDataQuery.data) : []),
    [refDataQuery.data],
  );
  const deckOptions = useMemo(
    () =>
      refDataQuery.data
        ? Object.entries(refDataQuery.data.decks).map(([id, d]) => ({
            id,
            label: (d as { name?: string }).name ?? id,
          }))
        : [],
    [refDataQuery.data],
  );
  const meshOptions = useMemo(
    () =>
      refDataQuery.data
        ? Object.entries(refDataQuery.data.meshes).map(([id, m]) => ({
            id,
            label: (m as { name?: string }).name ?? id,
          }))
        : [],
    [refDataQuery.data],
  );

  const { register, handleSubmit, control, watch, reset, formState } =
    useForm<FormValues>({
      defaultValues: {
        method: "parametric",
        time_limit: 60,
      },
    });

  // Track which seed we last applied so the defaults effect doesn't clobber
  // values hydrated from `?from_run` / `?from_batch`. The duplicate-run
  // hydration effect (below) writes its own key once it runs.
  const seededRef = useRef<string | null>(null);

  // Once ref-data lands, seed the form with the sidecar's DEFAULTS so the
  // user can hit Submit and get a known-good calc on first run. Skipped
  // when a duplicate-run param is in the URL — that path runs its own
  // hydration effect once the source run/batch lands.
  useEffect(() => {
    if (!refDataQuery.data) return;
    if (fromRunId !== null || fromBatchId !== null) return;
    if (seededRef.current === "defaults") return;
    seededRef.current = "defaults";
    const d = refDataQuery.data.defaults as Record<string, unknown>;
    reset({
      span1: Number(d.span1 ?? 9),
      span2: Number(d.span2 ?? 9),
      numbeam: Number(d.numbeam ?? 2),
      slab_depth: Number(d.slab_depth ?? 130),
      fck: Number(d.fck ?? 25),
      conc_type: (d.conc_type as "NW" | "LW") ?? "NW",
      mesh_type: String(d.mesh_type ?? "ST15C"),
      mesh_axis: Number(d.mesh_axis ?? 40),
      deck_id: String(d.DeckId ?? "T14"),
      u_sec_size: String(d.uSecSize ?? "IPE_500"),
      u_sec_fy: String(d.fy5 ?? "355"),
      u_sec_sh_con: Number(d.ush_con ?? 80),
      side_a_sec: String(d.SideASecSize ?? "IPE_500"),
      side_a_fy: String(d.fy1 ?? "355"),
      side_a_edge: Number(d.SideAEdgeFlag ?? 1),
      side_a_composite: Number(d.SideACompoFlag ?? 0),
      side_a_sh_con: Number(d.SideAsh_con ?? 80),
      side_b_sec: String(d.SideBSecSize ?? "IPE_500"),
      side_b_fy: String(d.fy2 ?? "355"),
      side_b_edge: Number(d.SideBEdgeFlag ?? 0),
      side_b_composite: Number(d.SideBCompoFlag ?? 1),
      side_b_sh_con: Number(d.SideBsh_con ?? 80),
      side_c_sec: String(d.SideCSecSize ?? "IPE_500"),
      side_c_fy: String(d.fy3 ?? "355"),
      side_c_edge: Number(d.SideCEdgeFlag ?? 0),
      side_c_composite: Number(d.SideCCompoFlag ?? 1),
      side_c_sh_con: Number(d.SideCsh_con ?? 80),
      side_d_sec: String(d.SideDSecSize ?? "IPE_500"),
      side_d_fy: String(d.fy4 ?? "355"),
      side_d_edge: Number(d.SideDEdgeFlag ?? 1),
      side_d_composite: Number(d.SideDCompoFlag ?? 0),
      side_d_sh_con: Number(d.SideDsh_con ?? 80),
      slab_weight: Number(d.slab_weight ?? 2.47),
      cold_perm: Number(d.cold_perm ?? 1.2),
      lead_var_act: Number(d.lead_var_act ?? 5.0),
      othr_var_act: Number(d.othr_var_act ?? 0.0),
      lead_var_fac: Number(d.lead_var_fac ?? 0.5),
      othr_var_fac: Number(d.othr_var_fac ?? 0.3),
      method: ((d.method as string) ?? "parametric") as "iso" | "parametric",
      time_limit: Number(d.time_limit ?? 60),
      qf: Number(d.qf ?? 511),
      window_percent: Number(d.window_percent ?? 95),
      Lc: Number(d.Lc ?? 27),
      Bc: Number(d.Bc ?? 18),
      Hc: Number(d.Hc ?? 3.6),
      Hw: Number(d.Hw ?? 1.8),
      Lw: Number(d.Lw ?? 30),
      Bfac: Number(d.Bfac ?? 720),
      combustion_factor: Number(d.combustion_factor ?? 0.8),
      growth_rate: Number(d.growth_rate ?? 1),
    });
  }, [refDataQuery.data, reset, fromRunId, fromBatchId]);

  const [mode, setMode] = useState<"single" | "sweep">("single");
  const [varying, setVarying] = useState<Record<string, ValueSource>>({});
  const [sweepError, setSweepError] = useState<string | null>(null);

  // Duplicate-run hydration: when ?from_run or ?from_batch is set and the
  // upstream data lands, fill the form and (for batches) switch to sweep
  // mode + populate the varying spec. Banner-text state ("source label")
  // captures the displayed source so the banner persists past a refetch.
  const [hydrationSource, setHydrationSource] = useState<string | null>(null);

  useEffect(() => {
    if (!refDataQuery.data) return;
    if (fromRunId === null || !fromRunQuery.data) return;
    if (seededRef.current === `run:${fromRunId}`) return;
    seededRef.current = `run:${fromRunId}`;
    const values = hydrateFormFromRun(fromRunQuery.data, refDataQuery.data);
    reset(values);
    setMode("single");
    setVarying({});
    setHydrationSource(`run #${fromRunId}`);
  }, [fromRunId, fromRunQuery.data, refDataQuery.data, reset]);

  useEffect(() => {
    if (!refDataQuery.data) return;
    if (fromBatchId === null || !fromBatchQuery.data) return;
    if (seededRef.current === `batch:${fromBatchId}`) return;
    seededRef.current = `batch:${fromBatchId}`;
    hydrateFormFromBatch(fromBatchQuery.data, refDataQuery.data, {
      reset,
      setVarying,
      setMode,
    });
    setHydrationSource(`batch ${fromBatchId}`);
  }, [fromBatchId, fromBatchQuery.data, refDataQuery.data, reset]);

  // FRC import state. `frcImportSource` drives the post-import banner;
  // `frcUnknownFields` carries the yellow-hint payload from the mapper —
  // populated when a `.frc` references a section/deck/mesh ID not in this
  // device's catalogue. The user picks a replacement; we just flag.
  const [frcImportSource, setFrcImportSource] = useState<{
    filename: string;
    projectName: string;
    clientName: string;
  } | null>(null);
  const [frcUnknownFields, setFrcUnknownFields] = useState<
    FrcHydrationResult["unknownFields"]
  >({});
  // Names of fields whose value came from the most recent .frc import.
  // Drives the "●" dot on each field's label so the user can see at a
  // glance which inputs are still in the as-imported state vs. which
  // they've reviewed and overridden. Cleared per-field via the dirty-
  // fields signal as the user touches inputs.
  const [importedFields, setImportedFields] = useState<Set<keyof FormValues>>(
    new Set(),
  );
  const [frcError, setFrcError] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const dismissBanner = () => {
    setHydrationSource(null);
    setFrcImportSource(null);
    setFrcUnknownFields({});
    setImportedFields(new Set());
    const next = new URLSearchParams(searchParams);
    next.delete("from_run");
    next.delete("from_batch");
    setSearchParams(next, { replace: true });
  };

  // Apply a parsed FRC payload — refData must be loaded so the mapper can
  // run its catalogue lookups. Caller is responsible for the dirty-form
  // confirm and reading the File.name → filename for the banner.
  const applyFrcImport = (data: ImportFrcResponse, filename: string) => {
    if (!refDataQuery.data) return;
    const result = hydrateFormFromFrcParams(data.params, refDataQuery.data);
    seededRef.current = `frc:${filename}`;
    reset(result.values);
    setMode("single");
    setVarying({});
    setHydrationSource(null);
    setFrcImportSource({
      filename,
      projectName: data.project?.ProjectName ?? "",
      clientName: data.project?.ClientName ?? "",
    });
    setFrcUnknownFields(result.unknownFields);
    setImportedFields(result.importedKeys);
    setFrcError(null);
    // Import beats ?from_run / ?from_batch — clear those so a refresh
    // doesn't re-hydrate from a stale URL.
    const next = new URLSearchParams(searchParams);
    if (next.has("from_run") || next.has("from_batch")) {
      next.delete("from_run");
      next.delete("from_batch");
      setSearchParams(next, { replace: true });
    }
  };

  const handleFrcFile = async (file: File) => {
    if (!file) return;
    if (formState.isDirty || hydrationSource || frcImportSource) {
      const ok = window.confirm(
        "Replace current form contents with the imported .frc?",
      );
      if (!ok) return;
    }
    try {
      const data = await importFrc(file);
      applyFrcImport(data, file.name);
    } catch (err) {
      setFrcError(
        err instanceof Error ? err.message : "Failed to import .frc file",
      );
    }
  };

  // Window-level drag-and-drop. dragenter/over set the overlay; dragleave
  // only clears when we leave the window (relatedTarget === null) so the
  // overlay doesn't flicker as the pointer crosses child elements.
  useEffect(() => {
    function onDragEnter(e: DragEvent) {
      if (e.dataTransfer?.types?.includes("Files")) {
        e.preventDefault();
        setIsDragOver(true);
      }
    }
    function onDragOver(e: DragEvent) {
      if (e.dataTransfer?.types?.includes("Files")) {
        e.preventDefault();
      }
    }
    function onDragLeave(e: DragEvent) {
      if (e.relatedTarget === null) setIsDragOver(false);
    }
    function onDrop(e: DragEvent) {
      if (!e.dataTransfer?.files?.length) return;
      e.preventDefault();
      setIsDragOver(false);
      const file = e.dataTransfer.files[0];
      if (!file.name.toLowerCase().endsWith(".frc")) {
        setFrcError(`Only .frc files can be imported (got "${file.name}")`);
        return;
      }
      void handleFrcFile(file);
    }
    window.addEventListener("dragenter", onDragEnter);
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("dragleave", onDragLeave);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragenter", onDragEnter);
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("dragleave", onDragLeave);
      window.removeEventListener("drop", onDrop);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refDataQuery.data, formState.isDirty, hydrationSource, frcImportSource]);

  // Ctrl+O / Cmd+O — open the file picker. Same handler the header button
  // wires to, so the entry points share one input element.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "o") {
        e.preventDefault();
        fileInputRef.current?.click();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const submit = useMutation<SubmitRunResponse, Error, FormValues>({
    mutationFn: (values) => submitRun(values as unknown as Record<string, unknown>),
    onSuccess: (data) => navigate(`/runs/${data.id}`),
  });

  const sweepSubmit = useMutation<SubmitSweepResponse, Error, Record<string, unknown>>({
    mutationFn: (body) => submitSweep(body),
    onSuccess: (data) => navigate(`/batches/${data.batch_id}`),
    onError: (err) => setSweepError(err.message),
  });

  const pairedErrors = useMemo(() => {
    if (mode !== "sweep") return {};
    return pairedValidation(varying).errors;
  }, [mode, varying]);
  const pairedErrorCount = Object.keys(pairedErrors).length;

  const sweepPreview = useMemo(() => {
    if (mode !== "sweep") return null;
    return buildSweepPayload({
      analysisMethod: "iso",
      fixed: {},
      varying,
    });
  }, [mode, varying]);

  const onSubmit: SubmitHandler<FormValues> = (values) => {
    setSweepError(null);
    if (mode === "single") {
      submit.mutate(values);
      return;
    }

    // Sweep mode: separate fixed values from varying ones, hand the result
    // off to /api/sweeps and navigate to the dashboard on success.
    const fixed: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(values)) {
      if (k === "method") continue;
      if (k in varying) continue;
      fixed[k] = v;
    }

    const result = buildSweepPayload({
      analysisMethod: values.method,
      fixed,
      varying,
    });

    if (pairedErrorCount > 0) {
      setSweepError(
        `Fix ${pairedErrorCount} parameter${pairedErrorCount === 1 ? "" : "s"} with mismatched or empty values.`,
      );
      return;
    }
    if (result.totalRuns === 0) {
      setSweepError("Pick at least one parameter to vary and give it values.");
      return;
    }
    if (
      result.totalRuns > 10000 &&
      !window.confirm(
        `This sweep will run ${result.totalRuns} calculations. Continue?`,
      )
    ) {
      return;
    }

    sweepSubmit.mutate(toRequestBody(result) as unknown as Record<string, unknown>);
  };

  const method = watch("method");
  const errors = formState.errors;
  // `dirtyFields` is a react-hook-form proxy — accessing it here registers
  // the subscription so the highlight clears as the user edits a field.
  const dirtyFields = formState.dirtyFields as Partial<
    Record<keyof FormValues, boolean>
  >;
  const isImported = (name: keyof FormValues): boolean =>
    importedFields.has(name) && !dirtyFields[name];

  if (refDataQuery.isLoading) {
    return <div className="p-8 text-slate-600">Loading reference data…</div>;
  }
  if (refDataQuery.isError) {
    throw refDataQuery.error;
  }

  return (
    <div className="mx-auto max-w-5xl p-8">
      <header className="mb-6 flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">MACS+ Automation</h1>
        <div className="flex items-center gap-3 text-sm text-slate-500">
          <div className="inline-flex overflow-hidden rounded border border-slate-300 text-xs">
            {(["single", "sweep"] as const).map((m) => (
              <button
                key={m}
                type="button"
                aria-pressed={mode === m}
                onClick={() => setMode(m)}
                className={`px-3 py-1 ${
                  mode === m
                    ? "bg-blue-700 text-white"
                    : "bg-white text-slate-700 hover:bg-slate-100"
                }`}
              >
                {m === "single" ? "Single run" : "Sweep"}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100"
            data-testid="import-frc-button"
            title="Import settings from a .frc file (Ctrl+O)"
          >
            Import .frc
          </button>
          <button
            type="button"
            onClick={() => checkForUpdates({ silent: false })}
            className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100"
          >
            Check for updates
          </button>
        </div>
      </header>

      {!macsDetected && (
        <div
          data-testid="macs-missing-banner"
          className="mb-4 flex items-start justify-between gap-3 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900"
        >
          <span>
            <strong>MACS+ not detected.</strong> Pickers will be empty and
            runs will fail. If MACS+ is installed in a non-standard location,
            click <em>Locate MACS+</em> to point i-macs at the install folder.
          </span>
          <button
            type="button"
            onClick={locateMacs}
            className="rounded border border-amber-400 bg-white px-3 py-1 text-xs font-semibold text-amber-900 hover:bg-amber-100"
          >
            Locate MACS+
          </button>
        </div>
      )}
      {macsDetected && !comRegistered && (
        <div
          data-testid="macs-com-missing-banner"
          className="mb-4 rounded-md border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-900"
        >
          <strong>FRACOF COM not registered.</strong> MACS+ Data.xml was
          found but its COM component isn't registered, so calculations
          will fail. Re-run the MACS+ installer (it registers SCTI11.FRACOF
          / SCTI9.FRACOF on first install).
        </div>
      )}

      <input
        ref={fileInputRef}
        type="file"
        accept=".frc"
        className="hidden"
        data-testid="frc-file-input"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) void handleFrcFile(file);
          // Reset so picking the same filename twice still fires onChange.
          e.target.value = "";
        }}
      />

      {isDragOver && (
        <div
          data-testid="frc-drop-overlay"
          className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center bg-blue-900/30"
        >
          <div className="rounded-md border-2 border-dashed border-blue-300 bg-white/90 px-8 py-6 text-center shadow-lg">
            <p className="text-lg font-semibold text-blue-900">
              Drop .frc to import
            </p>
            <p className="mt-1 text-sm text-blue-700">
              Settings will replace the current form contents.
            </p>
          </div>
        </div>
      )}

      {frcError && (
        <div
          role="alert"
          data-testid="frc-import-error"
          className="mb-4 flex items-start justify-between gap-3 rounded-md border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-900"
        >
          <span>{frcError}</span>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={() => setFrcError(null)}
            className="rounded p-0.5 text-rose-700 hover:bg-rose-100"
          >
            ×
          </button>
        </div>
      )}

      {frcImportSource && (
        <div
          data-testid="frc-import-banner"
          className="mb-4 flex items-start justify-between gap-3 rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900"
        >
          <span>
            Imported from <code className="font-mono">{frcImportSource.filename}</code>
            {frcImportSource.projectName && (
              <>
                {" "}— Project: <code className="font-mono">{frcImportSource.projectName}</code>
              </>
            )}
            {frcImportSource.clientName && (
              <>
                {" "}(Client: <code className="font-mono">{frcImportSource.clientName}</code>)
              </>
            )}
            {importedFields.size > 0 && (
              <span className="ml-1 text-blue-700">
                — fields with <span className="mx-0.5 inline-block h-1.5 w-1.5 rounded-full bg-blue-500 align-middle" aria-hidden /> are still set to the imported value.
              </span>
            )}
          </span>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={dismissBanner}
            className="rounded p-0.5 text-blue-700 hover:bg-blue-100"
          >
            ×
          </button>
        </div>
      )}

      {hydrationSource && (
        <div
          data-testid="duplicate-run-banner"
          className="mb-4 flex items-start justify-between gap-3 rounded-md border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900"
        >
          <span>
            Duplicated from {hydrationSource} — edit any field and run.
          </span>
          <button
            type="button"
            aria-label="Dismiss"
            onClick={dismissBanner}
            className="rounded p-0.5 text-blue-700 hover:bg-blue-100"
          >
            ×
          </button>
        </div>
      )}

      <form
        onSubmit={handleSubmit(onSubmit)}
        className="space-y-6 rounded-md border border-slate-200 bg-white p-6 shadow-sm"
      >
        {mode === "sweep" && (
          <>
            <SweepConfigSection
              varying={varying}
              onChange={setVarying}
              varyableParams={VARYABLE_PARAMS}
            />
            {sweepPreview && (
              <p className="text-xs text-slate-500">
                Total runs:{" "}
                <span className="font-semibold text-slate-700">
                  {sweepPreview.totalRuns}
                </span>
              </p>
            )}
          </>
        )}

        <Section title="Geometry">
          <Grid>
            {numberField("Span 1 (m)", "span1", register, errors, isImported("span1"))}
            {numberField("Span 2 (m)", "span2", register, errors, isImported("span2"))}
            {numberField("Number of beams", "numbeam", register, errors, isImported("numbeam"))}
            {numberField("Slab depth (mm)", "slab_depth", register, errors, isImported("slab_depth"))}
          </Grid>
        </Section>

        <Section title="Slab + deck + mesh">
          <Grid>
            {numberField("fck (MPa)", "fck", register, errors, isImported("fck"))}
            <SelectField
              label="Concrete type"
              name="conc_type"
              control={control}
              options={[
                { id: "NW", label: "Normal weight" },
                { id: "LW", label: "Lightweight" },
              ]}
              imported={isImported("conc_type")}
            />
            <SearchableSelectField
              label="Deck"
              name="deck_id"
              control={control}
              options={deckOptions}
              imported={isImported("deck_id")}
              hint={
                frcUnknownFields.deck_id
                  ? `Deck \`${frcUnknownFields.deck_id}\` not in catalogue — pick a replacement`
                  : undefined
              }
            />
            <SearchableSelectField
              label="Mesh"
              name="mesh_type"
              control={control}
              options={meshOptions}
              imported={isImported("mesh_type")}
              hint={
                frcUnknownFields.mesh_type
                  ? `Mesh \`${frcUnknownFields.mesh_type}\` not in catalogue — pick a replacement`
                  : undefined
              }
            />
            {numberField(
              "Mesh axis distance (mm)",
              "mesh_axis",
              register,
              errors,
              isImported("mesh_axis"),
            )}
          </Grid>
        </Section>

        <Section title="Beams">
          <SubLegend>Centre (unprotected)</SubLegend>
          <Grid>
            <SearchableSelectField
              label="Unprotected (centre) section"
              name="u_sec_size"
              control={control}
              options={sectionOptions}
              imported={isImported("u_sec_size")}
              hint={
                frcUnknownFields.u_sec_size
                  ? `Section \`${frcUnknownFields.u_sec_size}\` not in catalogue — pick a replacement`
                  : undefined
              }
            />
            <SelectField
              label="Steel grade"
              name="u_sec_fy"
              control={control}
              options={FY_OPTIONS.map((v) => ({ id: v, label: `S${v}` }))}
              imported={isImported("u_sec_fy")}
            />
            {numberField(
              "Shear conn. spacing (mm)",
              "u_sec_sh_con",
              register,
              errors,
              isImported("u_sec_sh_con"),
            )}
          </Grid>
          {(["a", "b", "c", "d"] as const).map((side) => {
            const secKey = `side_${side}_sec` as keyof FormValues;
            const unknown = frcUnknownFields[secKey];
            return (
              <BeamSideRow
                key={side}
                side={side}
                sectionOptions={sectionOptions}
                control={control}
                register={register}
                errors={errors}
                isImported={isImported}
                sectionHint={
                  unknown
                    ? `Section \`${unknown}\` not in catalogue — pick a replacement`
                    : undefined
                }
              />
            );
          })}
        </Section>

        <Section title="Loading">
          <Grid>
            {numberField("Slab self-weight (kN/m²)", "slab_weight", register, errors, isImported("slab_weight"))}
            {numberField("Cold permanent excl. slab (kN/m²)", "cold_perm", register, errors, isImported("cold_perm"))}
            {numberField("Leading variable (kN/m²)", "lead_var_act", register, errors, isImported("lead_var_act"))}
            {numberField("Other variable (kN/m²)", "othr_var_act", register, errors, isImported("othr_var_act"))}
            {numberField("Leading factor (ψ)", "lead_var_fac", register, errors, isImported("lead_var_fac"))}
            {numberField("Other factor (ψ)", "othr_var_fac", register, errors, isImported("othr_var_fac"))}
          </Grid>
        </Section>

        <Section title="Fire">
          <Grid>
            <SelectField
              label="Analysis method"
              name="method"
              control={control}
              options={[
                { id: "iso", label: "ISO standard fire" },
                { id: "parametric", label: "Parametric (EN 1991-1-2)" },
              ]}
              imported={isImported("method")}
            />
            {numberField("Time limit (min)", "time_limit", register, errors, isImported("time_limit"))}
            {numberField("Fire load qf (MJ/m²)", "qf", register, errors, isImported("qf"))}
            {numberField("Window opening (%)", "window_percent", register, errors, isImported("window_percent"))}
          </Grid>
          {method === "parametric" && (
            <Grid>
              {numberField("Compartment Lc (m)", "Lc", register, errors, isImported("Lc"))}
              {numberField("Compartment Bc (m)", "Bc", register, errors, isImported("Bc"))}
              {numberField("Compartment Hc (m)", "Hc", register, errors, isImported("Hc"))}
              {numberField("Window Hw (m)", "Hw", register, errors, isImported("Hw"))}
              {numberField("Window Lw (m)", "Lw", register, errors, isImported("Lw"))}
              {numberField("Bfac (J/m²s½K)", "Bfac", register, errors, isImported("Bfac"))}
              {numberField("Combustion factor", "combustion_factor", register, errors, isImported("combustion_factor"))}
              {numberField("Growth rate", "growth_rate", register, errors, isImported("growth_rate"))}
            </Grid>
          )}
        </Section>

        <div className="flex items-center justify-between border-t border-slate-100 pt-4">
          {mode === "single" && submit.isError && (
            <span className="text-sm text-rose-700">{submit.error.message}</span>
          )}
          {mode === "sweep" && sweepError && (
            <span className="text-sm text-rose-700">{sweepError}</span>
          )}
          <button
            type="submit"
            disabled={
              submit.isPending ||
              sweepSubmit.isPending ||
              (mode === "sweep" && pairedErrorCount > 0)
            }
            title={
              mode === "sweep" && pairedErrorCount > 0
                ? `Fix ${pairedErrorCount} parameter${pairedErrorCount === 1 ? "" : "s"} with mismatched or empty values`
                : undefined
            }
            className="ml-auto rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800 disabled:opacity-50"
          >
            {mode === "single"
              ? submit.isPending
                ? "Running…"
                : "Submit calculation"
              : sweepSubmit.isPending
                ? "Submitting sweep…"
                : "Run sweep"}
          </button>
        </div>
      </form>
    </div>
  );
}

/**
 * Hydrate the form from a stored batch's `varying_params` + `fixed_params`.
 *
 * The fixed map already carries the form-shaped field names (the sweep-submit
 * handler stores `request_body` verbatim), so we use it as the override on top
 * of defaults via a synthesized Run row + `hydrateFormFromRun`. The varying
 * map (`{name: values[]}` for grid sweeps) goes straight into the form's
 * `varying` ValueSource state as a `list` entry.
 */
function hydrateFormFromBatch(
  batch: BatchSummary,
  refData: RefData,
  api: {
    reset: ReturnType<typeof useForm<FormValues>>["reset"];
    setVarying: React.Dispatch<React.SetStateAction<Record<string, ValueSource>>>;
    setMode: React.Dispatch<React.SetStateAction<"single" | "sweep">>;
  },
) {
  // Fixed params from the stored config are form-shaped already (the
  // sweep-submit handler stores request_body verbatim). Merge them on top
  // of the sidecar defaults via the standard FormValues seed.
  const defaults = refData.defaults as Record<string, unknown>;
  const fixed = batch.fixed_params ?? {};
  const synthesizedRun = {
    ...defaults,
    ...fixed,
    // Defaults are keyed for the engine (e.g. fy5, SideASecSize), but the
    // run-shaped hydration helper expects DB column names. We seed the
    // helper with whatever overlap exists in `fixed` (form column names)
    // and rely on it to coerce types / fall back on zero where columns
    // are absent.
    deck_name: fixed.deck_id ?? (defaults.DeckId as string | undefined) ?? "",
    ush_con: fixed.u_sec_sh_con ?? defaults.ush_con ?? 80,
  } as unknown as Run;
  const values = hydrateFormFromRun(synthesizedRun, refData);
  // The hydration helper can't recover the steel grades from defaults
  // because the engine keys are fy1..fy5, not side_*_fy. Patch them back
  // in from `fixed` if present.
  const fy = (key: string, fallback: string) =>
    (fixed[key] as string | number | undefined)?.toString() ?? fallback;
  api.reset({
    ...values,
    u_sec_fy: fy("u_sec_fy", String(defaults.fy5 ?? "355")),
    side_a_fy: fy("side_a_fy", String(defaults.fy1 ?? "355")),
    side_b_fy: fy("side_b_fy", String(defaults.fy2 ?? "355")),
    side_c_fy: fy("side_c_fy", String(defaults.fy3 ?? "355")),
    side_d_fy: fy("side_d_fy", String(defaults.fy4 ?? "355")),
  });

  // Varying spec: convert each `name: values[]` entry into a `list` ValueSource.
  const next: Record<string, ValueSource> = {};
  for (const [name, raw] of Object.entries(batch.varying_params ?? {})) {
    if (Array.isArray(raw) && raw.every((v) => typeof v === "number")) {
      next[name] = { list: raw as number[] };
    }
  }
  api.setVarying(next);
  api.setMode("sweep");
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <fieldset className="space-y-3 border-t border-slate-100 pt-4 first:border-t-0 first:pt-0">
      <legend className="text-sm font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </legend>
      {children}
    </fieldset>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">{children}</div>;
}

function SubLegend({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">
      {children}
    </h3>
  );
}

function CheckboxField({
  label,
  name,
  control,
  imported,
}: {
  label: string;
  name: keyof FormValues;
  control: ReturnType<typeof useForm<FormValues>>["control"];
  imported?: boolean;
}) {
  return (
    <label className="flex items-center gap-2 self-end pb-2">
      <Controller
        control={control}
        name={name as never}
        render={({ field }) => (
          <input
            type="checkbox"
            checked={(field.value as number) === 1}
            onChange={(e) => field.onChange(e.target.checked ? 1 : 0)}
            className="h-4 w-4 rounded border-slate-300 text-blue-700 focus:ring-blue-500"
          />
        )}
      />
      <FieldLabel imported={imported}>{label}</FieldLabel>
    </label>
  );
}

function BeamSideRow({
  side,
  sectionOptions,
  control,
  register,
  errors,
  sectionHint,
  isImported,
}: {
  side: "a" | "b" | "c" | "d";
  sectionOptions: SearchableSelectOption[];
  control: ReturnType<typeof useForm<FormValues>>["control"];
  register: ReturnType<typeof useForm<FormValues>>["register"];
  errors: ReturnType<typeof useForm<FormValues>>["formState"]["errors"];
  sectionHint?: string;
  isImported: (name: keyof FormValues) => boolean;
}) {
  const secKey = `side_${side}_sec` as keyof FormValues;
  const fyKey = `side_${side}_fy` as keyof FormValues;
  const edgeKey = `side_${side}_edge` as keyof FormValues;
  const compoKey = `side_${side}_composite` as keyof FormValues;
  const shConKey = `side_${side}_sh_con` as keyof FormValues;
  return (
    <>
      <SubLegend>Side {side.toUpperCase()}</SubLegend>
      <Grid>
        <SearchableSelectField
          label={`Side ${side.toUpperCase()} section`}
          name={secKey}
          control={control}
          options={sectionOptions}
          hint={sectionHint}
          imported={isImported(secKey)}
        />
        <SelectField
          label="Steel grade"
          name={fyKey}
          control={control}
          options={FY_OPTIONS.map((v) => ({ id: v, label: `S${v}` }))}
          imported={isImported(fyKey)}
        />
        <CheckboxField
          label="Edge beam"
          name={edgeKey}
          control={control}
          imported={isImported(edgeKey)}
        />
        <CheckboxField
          label="Composite"
          name={compoKey}
          control={control}
          imported={isImported(compoKey)}
        />
        {numberField(
          "Shear conn. spacing (mm)",
          shConKey,
          register,
          errors,
          isImported(shConKey),
        )}
      </Grid>
    </>
  );
}

function SelectField({
  label,
  name,
  control,
  options,
  imported,
}: {
  label: string;
  name: keyof FormValues;
  control: ReturnType<typeof useForm<FormValues>>["control"];
  options: Array<{ id: string; label: string }>;
  imported?: boolean;
}) {
  return (
    <label className="block">
      <FieldLabel imported={imported}>{label}</FieldLabel>
      <Controller
        control={control}
        name={name as never}
        render={({ field }) => (
          <select
            {...field}
            value={(field.value as string) ?? ""}
            className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
          >
            <option value="" disabled>
              Choose…
            </option>
            {options.map((o) => (
              <option key={o.id} value={o.id}>
                {o.label}
              </option>
            ))}
          </select>
        )}
      />
    </label>
  );
}

function SearchableSelectField({
  label,
  name,
  control,
  options,
  hint,
  imported,
}: {
  label: string;
  name: keyof FormValues;
  control: ReturnType<typeof useForm<FormValues>>["control"];
  options: SearchableSelectOption[];
  hint?: string;
  imported?: boolean;
}) {
  const triggerId = `picker-${String(name)}`;
  return (
    <div className="block">
      <label htmlFor={triggerId} className="block">
        <FieldLabel imported={imported}>{label}</FieldLabel>
      </label>
      <Controller
        control={control}
        name={name as never}
        render={({ field }) => (
          <SearchableSelect
            id={triggerId}
            value={(field.value as string) ?? ""}
            onChange={field.onChange}
            options={options}
            ariaLabel={label}
            placeholder="Choose…"
          />
        )}
      />
      {hint && (
        <p
          data-testid={`frc-hint-${String(name)}`}
          className="mt-1 text-xs text-amber-700"
        >
          {hint}
        </p>
      )}
    </div>
  );
}
