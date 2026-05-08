import { useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useForm, Controller, type SubmitHandler } from "react-hook-form";
import { useMutation, useQuery } from "@tanstack/react-query";

import {
  fetchRefData,
  submitRun,
  type RefData,
  type SubmitRunResponse,
} from "../api/client";
import { checkForUpdates } from "../lib/updater";

interface FormValues {
  // Geometry
  span1: number;
  span2: number;
  numbeam: number;
  slab_depth: number;
  // Slab
  fck: number;
  conc_type: "NW" | "LW";
  // Mesh + deck
  mesh_type: string;
  deck_id: string;
  // Beams
  u_sec_size: string;
  u_sec_fy: string;
  // Sides A–D (sec + fy + edge/composite)
  side_a_sec: string;
  side_b_sec: string;
  side_c_sec: string;
  side_d_sec: string;
  // Fire
  method: "iso" | "parametric";
  time_limit: number;
  qf: number;
  window_percent: number;
  // Compartment (only used if method=parametric)
  Lc: number;
  Bc: number;
  Hc: number;
  Hw: number;
  Lw: number;
  Bfac: number;
  combustion_factor: number;
  growth_rate: number;
}

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
  const refDataQuery = useQuery({
    queryKey: ["ref-data"],
    queryFn: fetchRefData,
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

  // Once ref-data lands, seed the form with the sidecar's DEFAULTS so the
  // user can hit Submit and get a known-good calc on first run.
  useEffect(() => {
    if (!refDataQuery.data) return;
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
      side_a_sec: String(d.SideASecSize ?? "IPE_500"),
      side_b_sec: String(d.SideBSecSize ?? "IPE_500"),
      side_c_sec: String(d.SideCSecSize ?? "IPE_500"),
      side_d_sec: String(d.SideDSecSize ?? "IPE_500"),
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
  }, [refDataQuery.data, reset]);

  const submit = useMutation<SubmitRunResponse, Error, FormValues>({
    mutationFn: (values) => submitRun(values as unknown as Record<string, unknown>),
    onSuccess: (data) => navigate(`/runs/${data.id}`),
  });

  const onSubmit: SubmitHandler<FormValues> = (values) => {
    submit.mutate(values);
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
          <span>v0.1.0-rc.1 — single-run</span>
          <button
            type="button"
            onClick={() => checkForUpdates({ silent: false })}
            className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-100"
          >
            Check for updates
          </button>
        </div>
      </header>

      <form
        onSubmit={handleSubmit(onSubmit)}
        className="space-y-6 rounded-md border border-slate-200 bg-white p-6 shadow-sm"
      >
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
          <Grid>
            <SelectField
              label="Unprotected (centre) section"
              name="u_sec_size"
              control={control}
              options={sectionOptions}
            />
            <SelectField
              label="Unprotected fy"
              name="u_sec_fy"
              control={control}
              options={FY_OPTIONS.map((v) => ({ id: v, label: `S${v}` }))}
            />
          </Grid>
          <Grid>
            <SelectField
              label="Side A section"
              name="side_a_sec"
              control={control}
              options={sectionOptions}
            />
            <SelectField
              label="Side B section"
              name="side_b_sec"
              control={control}
              options={sectionOptions}
            />
            <SelectField
              label="Side C section"
              name="side_c_sec"
              control={control}
              options={sectionOptions}
            />
            <SelectField
              label="Side D section"
              name="side_d_sec"
              control={control}
              options={sectionOptions}
            />
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
          {submit.isError && (
            <span className="text-sm text-rose-700">{submit.error.message}</span>
          )}
          <button
            type="submit"
            disabled={submit.isPending}
            className="ml-auto rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800 disabled:opacity-50"
          >
            {submit.isPending ? "Running…" : "Submit calculation"}
          </button>
        </div>
      </form>
    </div>
  );
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
