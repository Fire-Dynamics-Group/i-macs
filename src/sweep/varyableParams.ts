import type { VaryableParam } from "./SweepConfigSection";

/** Parameters that can be varied in a sweep batch. Per-side beam fields are
 *  intentionally excluded — section choices stay fixed across the batch
 *  (matches archived UX-plan decision #4). */
export const VARYABLE_PARAMS: VaryableParam[] = [
  { name: "qf", label: "Fire load qf (MJ/m²)", isInteger: false },
  { name: "window_percent", label: "Window opening (%)", isInteger: false },
  { name: "slab_depth", label: "Slab depth (mm)", isInteger: false },
  { name: "fck", label: "fck (MPa)", isInteger: false },
  { name: "span1", label: "Span 1 (m)", isInteger: false },
  { name: "span2", label: "Span 2 (m)", isInteger: false },
  { name: "Lc", label: "Compartment Lc (m)", isInteger: false },
  { name: "Bc", label: "Compartment Bc (m)", isInteger: false },
  { name: "Hc", label: "Compartment Hc (m)", isInteger: false },
  { name: "Hw", label: "Window Hw (m)", isInteger: false },
  { name: "Lw", label: "Window Lw (m)", isInteger: false },
  { name: "Bfac", label: "Bfac (J/m²s½K)", isInteger: false },
  { name: "combustion_factor", label: "Combustion factor", isInteger: false },
  { name: "growth_rate", label: "Growth rate", isInteger: false },
  { name: "numbeam", label: "Number of beams", isInteger: true },
  { name: "time_limit", label: "Time limit (min)", isInteger: true },
];
