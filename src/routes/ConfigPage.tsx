import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useForm, Controller, type SubmitHandler } from "react-hook-form";
import { useMutation, useQuery } from "@tanstack/react-query";

import {
  fetchRefData,
  getBatch,
  getRun,
  submitRun,
  submitSweep,
  type BatchSummary,
  type RefData,
  type Run,
  type SubmitRunResponse,
  type SubmitSweepResponse,
} from "../api/client";
import { checkForUpdates } from "../lib/updater";
import { hydrateFormFromRun } from "../lib/hydrateFormFromRun";
import { SweepConfigSection } from "../sweep/SweepConfigSection";
import { VARYABLE_PARAMS } from "../sweep/varyableParams";
import {
  buildSweepPayload,
  toRequestBody,
  type ValueSource,
} from "../sweep/buildSweepPayload";
import type { FormValues } from "../types/formValues";

const FY_OPTIONS = ["235", "275", "355", "460"];

const numberField = (
  label: string,
  name: keyof FormValues,
  register: ReturnType<typeof useForm<FormValues>>["register"],
  errors: ReturnType<typeof useForm<FormValues>>["formState"]["errors"],
) => (
  <label className="block">
    <span className="text-sm font-medium text-slate-700">{label}</span>
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

function flattenSections(refData: RefData): Array<{ id: string; label: string }> {
  const out: Array<{ id: string; label: string }> = [];
  for (const family of Object.keys(refData.sections)) {
    for (const sec of refData.sections[family]) {
      out.push({ id: sec.id, label: `${sec.name} (${family})` });
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
        method: "iso",
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
      method: ((d.method as string) ?? "iso") as "iso" | "parametric",
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

  const dismissBanner = () => {
    setHydrationSource(null);
    const next = new URLSearchParams(searchParams);
    next.delete("from_run");
    next.delete("from_batch");
    setSearchParams(next, { replace: true });
  };

  const submit = useMutation<SubmitRunResponse, Error, FormValues>({
    mutationFn: (values) => submitRun(values as unknown as Record<string, unknown>),
    onSuccess: (data) => navigate(`/runs/${data.id}`),
  });

  const sweepSubmit = useMutation<SubmitSweepResponse, Error, Record<string, unknown>>({
    mutationFn: (body) => submitSweep(body),
    onSuccess: (data) => navigate(`/batches/${data.batch_id}`),
    onError: (err) => setSweepError(err.message),
  });

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

    if (result.totalCombinations === 0) {
      setSweepError("Pick at least one parameter to vary and give it values.");
      return;
    }
    if (
      result.totalCombinations > 10000 &&
      !window.confirm(
        `This sweep will run ${result.totalCombinations} calculations. Continue?`,
      )
    ) {
      return;
    }

    sweepSubmit.mutate(toRequestBody(result) as unknown as Record<string, unknown>);
  };

  const method = watch("method");
  const errors = formState.errors;

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
            onClick={() => checkForUpdates({ silent: false })}
            className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100"
          >
            Check for updates
          </button>
        </div>
      </header>

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
                Projected total:{" "}
                <span className="font-semibold text-slate-700">
                  {sweepPreview.totalCombinations}
                </span>{" "}
                calculation{sweepPreview.totalCombinations === 1 ? "" : "s"}
              </p>
            )}
          </>
        )}

        <Section title="Geometry">
          <Grid>
            {numberField("Span 1 (m)", "span1", register, errors)}
            {numberField("Span 2 (m)", "span2", register, errors)}
            {numberField("Number of beams", "numbeam", register, errors)}
            {numberField("Slab depth (mm)", "slab_depth", register, errors)}
          </Grid>
        </Section>

        <Section title="Slab + deck + mesh">
          <Grid>
            {numberField("fck (MPa)", "fck", register, errors)}
            <SelectField
              label="Concrete type"
              name="conc_type"
              control={control}
              options={[
                { id: "NW", label: "Normal weight" },
                { id: "LW", label: "Lightweight" },
              ]}
            />
            <SelectField
              label="Deck"
              name="deck_id"
              control={control}
              options={deckOptions}
            />
            <SelectField
              label="Mesh"
              name="mesh_type"
              control={control}
              options={meshOptions}
            />
          </Grid>
        </Section>

        <Section title="Beams">
          <SubLegend>Centre (unprotected)</SubLegend>
          <Grid>
            <SelectField
              label="Unprotected (centre) section"
              name="u_sec_size"
              control={control}
              options={sectionOptions}
            />
            <SelectField
              label="Steel grade"
              name="u_sec_fy"
              control={control}
              options={FY_OPTIONS.map((v) => ({ id: v, label: `S${v}` }))}
            />
            {numberField("Shear conn. spacing (mm)", "u_sec_sh_con", register, errors)}
          </Grid>
          {(["a", "b", "c", "d"] as const).map((side) => (
            <BeamSideRow
              key={side}
              side={side}
              sectionOptions={sectionOptions}
              control={control}
              register={register}
              errors={errors}
            />
          ))}
        </Section>

        <Section title="Loading">
          <Grid>
            {numberField("Slab self-weight (kN/m²)", "slab_weight", register, errors)}
            {numberField("Cold permanent excl. slab (kN/m²)", "cold_perm", register, errors)}
            {numberField("Leading variable (kN/m²)", "lead_var_act", register, errors)}
            {numberField("Other variable (kN/m²)", "othr_var_act", register, errors)}
            {numberField("Leading factor (ψ)", "lead_var_fac", register, errors)}
            {numberField("Other factor (ψ)", "othr_var_fac", register, errors)}
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
            />
            {numberField("Time limit (min)", "time_limit", register, errors)}
            {numberField("Fire load qf (MJ/m²)", "qf", register, errors)}
            {numberField("Window opening (%)", "window_percent", register, errors)}
          </Grid>
          {method === "parametric" && (
            <Grid>
              {numberField("Compartment Lc (m)", "Lc", register, errors)}
              {numberField("Compartment Bc (m)", "Bc", register, errors)}
              {numberField("Compartment Hc (m)", "Hc", register, errors)}
              {numberField("Window Hw (m)", "Hw", register, errors)}
              {numberField("Window Lw (m)", "Lw", register, errors)}
              {numberField("Bfac (J/m²s½K)", "Bfac", register, errors)}
              {numberField("Combustion factor", "combustion_factor", register, errors)}
              {numberField("Growth rate", "growth_rate", register, errors)}
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
            disabled={submit.isPending || sweepSubmit.isPending}
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
}: {
  label: string;
  name: keyof FormValues;
  control: ReturnType<typeof useForm<FormValues>>["control"];
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
      <span className="text-sm font-medium text-slate-700">{label}</span>
    </label>
  );
}

function BeamSideRow({
  side,
  sectionOptions,
  control,
  register,
  errors,
}: {
  side: "a" | "b" | "c" | "d";
  sectionOptions: Array<{ id: string; label: string }>;
  control: ReturnType<typeof useForm<FormValues>>["control"];
  register: ReturnType<typeof useForm<FormValues>>["register"];
  errors: ReturnType<typeof useForm<FormValues>>["formState"]["errors"];
}) {
  return (
    <>
      <SubLegend>Side {side.toUpperCase()}</SubLegend>
      <Grid>
        <SelectField
          label="Section"
          name={`side_${side}_sec` as keyof FormValues}
          control={control}
          options={sectionOptions}
        />
        <SelectField
          label="Steel grade"
          name={`side_${side}_fy` as keyof FormValues}
          control={control}
          options={FY_OPTIONS.map((v) => ({ id: v, label: `S${v}` }))}
        />
        <CheckboxField
          label="Edge beam"
          name={`side_${side}_edge` as keyof FormValues}
          control={control}
        />
        <CheckboxField
          label="Composite"
          name={`side_${side}_composite` as keyof FormValues}
          control={control}
        />
        {numberField(
          "Shear conn. spacing (mm)",
          `side_${side}_sh_con` as keyof FormValues,
          register,
          errors,
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
}: {
  label: string;
  name: keyof FormValues;
  control: ReturnType<typeof useForm<FormValues>>["control"];
  options: Array<{ id: string; label: string }>;
}) {
  return (
    <label className="block">
      <span className="text-sm font-medium text-slate-700">{label}</span>
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
