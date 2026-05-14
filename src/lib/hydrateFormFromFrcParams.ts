/**
 * Map a parsed `.frc` params dict (engine-keyed, as returned by
 * `/api/import-frc`) → `FormValues` for the ConfigPage.
 *
 * Three things this helper takes care of that callers shouldn't:
 *   - Engine-key → form-key renaming (DeckId → deck_id, uSecSize → u_sec_size,
 *     SideASecSize → side_a_sec, fy1..fy5 → side_*_fy/u_sec_fy, etc.).
 *   - Stringifying the steel grades (fy* are strings in the form's <select>
 *     but parsed as numbers by the engine sometimes).
 *   - Catalogue validation: section / deck / mesh IDs from the .frc may not
 *     exist on this device (custom user definitions live in per-device SQLite).
 *     Unknown IDs land in `unknownFields` so the UI can yellow-hint the field
 *     and the user can pick a replacement. The mapped value is "" so the
 *     dropdown reads as "Choose…" rather than holding a phantom ID.
 */
import type { RefData } from "../api/client";
import type { FormValues } from "../types/formValues";

export interface FrcHydrationResult {
  values: FormValues;
  /** FormValues field → the unrecognised engine ID that was dropped. */
  unknownFields: Partial<Record<keyof FormValues, string>>;
}

export function hydrateFormFromFrcParams(
  params: Record<string, unknown>,
  refData: RefData,
): FrcHydrationResult {
  const unknownFields: Partial<Record<keyof FormValues, string>> = {};

  const knownSectionIds = new Set<string>();
  for (const family of Object.keys(refData.sections)) {
    for (const s of refData.sections[family]) knownSectionIds.add(s.id);
  }
  const knownDeckIds = new Set(Object.keys(refData.decks));
  const knownMeshIds = new Set(Object.keys(refData.meshes));

  const resolveSection = (formKey: keyof FormValues, raw: unknown): string => {
    const id = asString(raw);
    if (!id) return "";
    if (knownSectionIds.has(id)) return id;
    unknownFields[formKey] = id;
    return "";
  };

  const resolveDeck = (raw: unknown): string => {
    const id = asString(raw);
    if (!id) return "";
    if (knownDeckIds.has(id)) return id;
    unknownFields.deck_id = id;
    return "";
  };

  const resolveMesh = (raw: unknown): string => {
    const id = asString(raw);
    if (!id) return "";
    if (knownMeshIds.has(id)) return id;
    unknownFields.mesh_type = id;
    return "";
  };

  const values: FormValues = {
    span1: asNumber(params.span1),
    span2: asNumber(params.span2),
    numbeam: asNumber(params.numbeam),
    slab_depth: asNumber(params.slab_depth),
    fck: asNumber(params.fck),
    conc_type: (params.conc_type as "NW" | "LW") ?? "NW",
    mesh_type: resolveMesh(params.mesh_type),
    deck_id: resolveDeck(params.DeckId),
    u_sec_size: resolveSection("u_sec_size", params.uSecSize),
    u_sec_fy: asString(params.fy5),
    u_sec_sh_con: asNumber(params.ush_con),
    side_a_sec: resolveSection("side_a_sec", params.SideASecSize),
    side_a_fy: asString(params.fy1),
    side_a_edge: asNumber(params.SideAEdgeFlag),
    side_a_composite: asNumber(params.SideACompoFlag),
    side_a_sh_con: asNumber(params.SideAsh_con),
    side_b_sec: resolveSection("side_b_sec", params.SideBSecSize),
    side_b_fy: asString(params.fy2),
    side_b_edge: asNumber(params.SideBEdgeFlag),
    side_b_composite: asNumber(params.SideBCompoFlag),
    side_b_sh_con: asNumber(params.SideBsh_con),
    side_c_sec: resolveSection("side_c_sec", params.SideCSecSize),
    side_c_fy: asString(params.fy3),
    side_c_edge: asNumber(params.SideCEdgeFlag),
    side_c_composite: asNumber(params.SideCCompoFlag),
    side_c_sh_con: asNumber(params.SideCsh_con),
    side_d_sec: resolveSection("side_d_sec", params.SideDSecSize),
    side_d_fy: asString(params.fy4),
    side_d_edge: asNumber(params.SideDEdgeFlag),
    side_d_composite: asNumber(params.SideDCompoFlag),
    side_d_sh_con: asNumber(params.SideDsh_con),
    slab_weight: asNumber(params.slab_weight),
    cold_perm: asNumber(params.cold_perm),
    lead_var_act: asNumber(params.lead_var_act),
    othr_var_act: asNumber(params.othr_var_act),
    lead_var_fac: asNumber(params.lead_var_fac),
    othr_var_fac: asNumber(params.othr_var_fac),
    method: params.method === "parametric" ? "parametric" : "iso",
    time_limit: asNumber(params.time_limit),
    qf: asNumber(params.qf),
    window_percent: asNumber(params.window_percent),
    Lc: asNumber(params.Lc),
    Bc: asNumber(params.Bc),
    Hc: asNumber(params.Hc),
    Hw: asNumber(params.Hw),
    Lw: asNumber(params.Lw),
    Bfac: asNumber(params.Bfac),
    combustion_factor: asNumber(params.combustion_factor),
    growth_rate: asNumber(params.growth_rate),
  };

  return { values, unknownFields };
}

function asNumber(v: unknown): number {
  if (typeof v === "number") return v;
  if (v == null) return 0;
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

function asString(v: unknown): string {
  if (v == null) return "";
  return String(v);
}
