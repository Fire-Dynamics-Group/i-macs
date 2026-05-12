/**
 * Shape of the ConfigPage form.
 *
 * Lives outside ConfigPage.tsx so the duplicate-run hydration helper
 * (`hydrateFormFromRun`) can produce a value of this exact type.
 */
export interface FormValues {
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
  // Beams — centre / unprotected
  u_sec_size: string;
  u_sec_fy: string;
  u_sec_sh_con: number;
  // Sides A–D
  side_a_sec: string;
  side_a_fy: string;
  side_a_edge: number;
  side_a_composite: number;
  side_a_sh_con: number;
  side_b_sec: string;
  side_b_fy: string;
  side_b_edge: number;
  side_b_composite: number;
  side_b_sh_con: number;
  side_c_sec: string;
  side_c_fy: string;
  side_c_edge: number;
  side_c_composite: number;
  side_c_sh_con: number;
  side_d_sec: string;
  side_d_fy: string;
  side_d_edge: number;
  side_d_composite: number;
  side_d_sh_con: number;
  // Loading
  slab_weight: number;
  cold_perm: number;
  lead_var_act: number;
  othr_var_act: number;
  lead_var_fac: number;
  othr_var_fac: number;
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
