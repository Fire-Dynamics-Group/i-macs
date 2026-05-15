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
 *
 * The mapper always returns a complete FormValues (zero / "" for missing
 * keys so react-hook-form's reset() doesn't see undefined). `importedKeys`
 * separately records which form fields actually had a source key present
 * in the .frc — used by the UI to dot only those labels, not every input.
 */
import type { RefData } from "../api/client";
import type { FormValues } from "../types/formValues";

export interface FrcHydrationResult {
  values: FormValues;
  /** FormValues field → the unrecognised engine ID that was dropped. */
  unknownFields: Partial<Record<keyof FormValues, string>>;
  /** Form fields whose value came from an engine key actually present in
   *  the .frc payload. Drives the per-label "●" provenance dot. */
  importedKeys: Set<keyof FormValues>;
}

/** Map of FormValues field → the engine key (or keys) that populate it.
 *  If any listed engine key is present in the .frc params, the form field
 *  counts as imported. Listed in the same order as the FormValues struct
 *  for readability. */
const SOURCE_KEYS: Record<keyof FormValues, readonly string[]> = {
  span1: ["span1"],
  span2: ["span2"],
  numbeam: ["numbeam"],
  slab_depth: ["slab_depth"],
  fck: ["fck"],
  conc_type: ["conc_type"],
  mesh_type: ["mesh_type"],
  deck_id: ["DeckId"],
  u_sec_size: ["uSecSize"],
  u_sec_fy: ["fy5"],
  u_sec_sh_con: ["ush_con"],
  side_a_sec: ["SideASecSize"],
  side_a_fy: ["fy1"],
  side_a_edge: ["SideAEdgeFlag"],
  side_a_composite: ["SideACompoFlag"],
  side_a_sh_con: ["SideAsh_con"],
  side_b_sec: ["SideBSecSize"],
  side_b_fy: ["fy2"],
  side_b_edge: ["SideBEdgeFlag"],
  side_b_composite: ["SideBCompoFlag"],
  side_b_sh_con: ["SideBsh_con"],
  side_c_sec: ["SideCSecSize"],
  side_c_fy: ["fy3"],
  side_c_edge: ["SideCEdgeFlag"],
  side_c_composite: ["SideCCompoFlag"],
  side_c_sh_con: ["SideCsh_con"],
  side_d_sec: ["SideDSecSize"],
  side_d_fy: ["fy4"],
  side_d_edge: ["SideDEdgeFlag"],
  side_d_composite: ["SideDCompoFlag"],
  side_d_sh_con: ["SideDsh_con"],
  slab_weight: ["slab_weight"],
  cold_perm: ["cold_perm"],
  lead_var_act: ["lead_var_act"],
  othr_var_act: ["othr_var_act"],
  lead_var_fac: ["lead_var_fac"],
  othr_var_fac: ["othr_var_fac"],
  method: ["method"],
  time_limit: ["time_limit"],
  qf: ["qf"],
  window_percent: ["window_percent"],
  Lc: ["Lc"],
  Bc: ["Bc"],
  Hc: ["Hc"],
  Hw: ["Hw"],
  Lw: ["Lw"],
  Bfac: ["Bfac"],
  combustion_factor: ["combustion_factor"],
  growth_rate: ["growth_rate"],
};

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

  const importedKeys = new Set<keyof FormValues>();
  for (const formKey of Object.keys(SOURCE_KEYS) as Array<keyof FormValues>) {
    for (const engineKey of SOURCE_KEYS[formKey]) {
      if (engineKey in params && params[engineKey] != null) {
        importedKeys.add(formKey);
        break;
      }
    }
  }

  return { values, unknownFields, importedKeys };
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
