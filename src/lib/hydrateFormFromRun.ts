/**
 * Map a stored `Run` row (sidecar DB shape) → `FormValues` for the
 * ConfigPage.
 *
 * Used by the duplicate-run flow: ConfigPage reads `?from_run=<id>`,
 * fetches `/api/runs/{id}`, calls this function, and calls form `reset()`
 * with the result. Works for errored runs too — the inputs are persisted
 * before the calc fires, so they survive a failure even though the
 * output columns are null.
 *
 * Two DB→form mismatches the function papers over:
 *   - `ush_con` (DB) → `u_sec_sh_con` (form)
 *   - `*_fy` columns are integers in SQLite but strings in the form's
 *     `<select>` options ("355"). Stringified here.
 *   - `deck_name` (DB) → `deck_id` (form). The DB stores the deck's
 *     display name; the form wants its dict key. Optional `refData`
 *     enables the reverse lookup; without it we use `deck_name`
 *     verbatim (works when id == name, which is the common case).
 */
import type { Run, RefData } from "../api/client";
import type { FormValues } from "../types/formValues";

export function hydrateFormFromRun(run: Run, refData?: RefData): FormValues {
  const r = run as Record<string, unknown>;

  return {
    // Geometry
    span1: asNumber(r.span1),
    span2: asNumber(r.span2),
    numbeam: asNumber(r.numbeam),
    slab_depth: asNumber(r.slab_depth),
    // Slab
    fck: asNumber(r.fck),
    conc_type: (r.conc_type as "NW" | "LW") ?? "NW",
    // Mesh + deck
    mesh_type: asString(r.mesh_type),
    deck_id: resolveDeckId(asString(r.deck_name), refData),
    // Centre / unprotected
    u_sec_size: asString(r.u_sec_size),
    u_sec_fy: asString(r.u_sec_fy),
    u_sec_sh_con: asNumber(r.ush_con),
    // Sides A–D
    side_a_sec: asString(r.side_a_sec),
    side_a_fy: asString(r.side_a_fy),
    side_a_edge: asNumber(r.side_a_edge),
    side_a_composite: asNumber(r.side_a_composite),
    side_a_sh_con: asNumber(r.side_a_sh_con),
    side_b_sec: asString(r.side_b_sec),
    side_b_fy: asString(r.side_b_fy),
    side_b_edge: asNumber(r.side_b_edge),
    side_b_composite: asNumber(r.side_b_composite),
    side_b_sh_con: asNumber(r.side_b_sh_con),
    side_c_sec: asString(r.side_c_sec),
    side_c_fy: asString(r.side_c_fy),
    side_c_edge: asNumber(r.side_c_edge),
    side_c_composite: asNumber(r.side_c_composite),
    side_c_sh_con: asNumber(r.side_c_sh_con),
    side_d_sec: asString(r.side_d_sec),
    side_d_fy: asString(r.side_d_fy),
    side_d_edge: asNumber(r.side_d_edge),
    side_d_composite: asNumber(r.side_d_composite),
    side_d_sh_con: asNumber(r.side_d_sh_con),
    // Loading
    slab_weight: asNumber(r.slab_weight),
    cold_perm: asNumber(r.cold_perm),
    lead_var_act: asNumber(r.lead_var_act),
    othr_var_act: asNumber(r.othr_var_act),
    lead_var_fac: asNumber(r.lead_var_fac),
    othr_var_fac: asNumber(r.othr_var_fac),
    // Fire
    method: (r.method as "iso" | "parametric") ?? "iso",
    time_limit: asNumber(r.time_limit),
    qf: asNumber(r.qf),
    window_percent: asNumber(r.window_percent),
    Lc: asNumber(r.Lc),
    Bc: asNumber(r.Bc),
    Hc: asNumber(r.Hc),
    Hw: asNumber(r.Hw),
    Lw: asNumber(r.Lw),
    Bfac: asNumber(r.Bfac),
    combustion_factor: asNumber(r.combustion_factor),
    growth_rate: asNumber(r.growth_rate),
  };
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

function resolveDeckId(deckName: string, refData?: RefData): string {
  if (!deckName) return "";
  if (!refData) return deckName;
  // refData.decks is keyed by id; each entry may carry a `name` field.
  for (const [id, deck] of Object.entries(refData.decks)) {
    const name = (deck as { name?: string }).name;
    if (name === deckName || id === deckName) return id;
  }
  return deckName;
}
