import { describe, expect, it } from "vitest";

import {
  hydrateFormFromFrcParams,
  type FrcHydrationResult,
} from "./hydrateFormFromFrcParams";
import type { RefData } from "../api/client";

const REF_DATA: RefData = {
  sections: {
    UB: [
      { id: "UB_457x152x60", name: "UB 457 x 152 x 60", h: 454.6, b: 152.9 },
      { id: "UB_533x210x101", name: "UB 533 x 210 x 101", h: 536.7, b: 210 },
      { id: "UB_610x229x101", name: "UB 610 x 229 x 101", h: 602.6, b: 227.6 },
    ],
  },
  decks: {
    T10: { name: "Metflor 60", deck_type: "T", deck_depth: 60 },
  },
  meshes: {
    A193: { name: "A193", mainArea: 193, transArea: 193 },
  },
  defaults: {},
  occupancy_presets: [],
};

// Mirrors the engine-keyed shape returned by /api/import-frc for sample.frc.
const SAMPLE_PARAMS: Record<string, unknown> = {
  span1: 11.2,
  span2: 9.2,
  numbeam: 2,
  DeckId: "T10",
  conc_type: "NW",
  fck: 30,
  slab_depth: 150,
  mesh_type: "A193",
  mesh_axis: 52,
  uSecSize: "UB_457x152x60",
  fy5: "355",
  ush_con: 80,
  SideASecSize: "UB_457x152x60",
  fy1: "355",
  SideAEdgeFlag: 0,
  SideACompoFlag: 1,
  SideAsh_con: 80,
  SideBSecSize: "UB_533x210x101",
  fy2: "355",
  SideBEdgeFlag: 1,
  SideBCompoFlag: 0,
  SideBsh_con: 80,
  SideCSecSize: "UB_457x152x60",
  fy3: "355",
  SideCEdgeFlag: 0,
  SideCCompoFlag: 1,
  SideCsh_con: 80,
  SideDSecSize: "UB_610x229x101",
  fy4: "355",
  SideDEdgeFlag: 1,
  SideDCompoFlag: 0,
  SideDsh_con: 80,
  slab_weight: 2.83,
  cold_perm: 2,
  lead_var_act: 5,
  othr_var_act: 0,
  lead_var_fac: 0.5,
  othr_var_fac: 0.3,
  method: "parametric",
  time_limit: 120,
  qf: 511,
  window_percent: 95,
  Lc: 63,
  Bc: 12,
  Hc: 3.6,
  Hw: 3.6,
  Lw: 63,
  Bfac: 1400,
  combustion_factor: 0.8,
  growth_rate: 1,
};

describe("hydrateFormFromFrcParams", () => {
  it("maps engine keys → FormValues keys for geometry + slab + deck + mesh", () => {
    const { values, unknownFields }: FrcHydrationResult =
      hydrateFormFromFrcParams(SAMPLE_PARAMS, REF_DATA);

    expect(values.span1).toBe(11.2);
    expect(values.span2).toBe(9.2);
    expect(values.numbeam).toBe(2);
    expect(values.slab_depth).toBe(150);
    expect(values.fck).toBe(30);
    expect(values.conc_type).toBe("NW");
    expect(values.deck_id).toBe("T10");
    expect(values.mesh_type).toBe("A193");
    expect(values.mesh_axis).toBe(52);
    expect(unknownFields).toEqual({});
  });

  it("maps centre + per-side beam params, stringifying fy* and coercing flags", () => {
    const { values } = hydrateFormFromFrcParams(SAMPLE_PARAMS, REF_DATA);

    expect(values.u_sec_size).toBe("UB_457x152x60");
    expect(values.u_sec_fy).toBe("355");
    expect(values.u_sec_sh_con).toBe(80);

    expect(values.side_a_sec).toBe("UB_457x152x60");
    expect(values.side_a_fy).toBe("355");
    expect(values.side_a_edge).toBe(0);
    expect(values.side_a_composite).toBe(1);
    expect(values.side_a_sh_con).toBe(80);

    expect(values.side_b_sec).toBe("UB_533x210x101");
    expect(values.side_b_edge).toBe(1);
    expect(values.side_b_composite).toBe(0);

    expect(values.side_d_sec).toBe("UB_610x229x101");
    expect(values.side_d_edge).toBe(1);
    expect(values.side_d_composite).toBe(0);
  });

  it("maps loading + fire + compartment params", () => {
    const { values } = hydrateFormFromFrcParams(SAMPLE_PARAMS, REF_DATA);

    expect(values.slab_weight).toBe(2.83);
    expect(values.cold_perm).toBe(2);
    expect(values.lead_var_act).toBe(5);
    expect(values.othr_var_act).toBe(0);
    expect(values.lead_var_fac).toBe(0.5);
    expect(values.othr_var_fac).toBe(0.3);

    expect(values.method).toBe("parametric");
    expect(values.time_limit).toBe(120);
    expect(values.qf).toBe(511);
    expect(values.window_percent).toBe(95);
    expect(values.Lc).toBe(63);
    expect(values.Bc).toBe(12);
    expect(values.Hc).toBe(3.6);
    expect(values.Hw).toBe(3.6);
    expect(values.Lw).toBe(63);
    expect(values.Bfac).toBe(1400);
    expect(values.combustion_factor).toBe(0.8);
    expect(values.growth_rate).toBe(1);
  });

  it("flags an unknown side section id and leaves the field blank", () => {
    const params = { ...SAMPLE_PARAMS, SideASecSize: "UB_FAKE_999" };
    const { values, unknownFields } = hydrateFormFromFrcParams(params, REF_DATA);

    expect(values.side_a_sec).toBe("");
    expect(unknownFields.side_a_sec).toBe("UB_FAKE_999");
    // Other sides are unaffected.
    expect(unknownFields.side_b_sec).toBeUndefined();
    expect(values.side_b_sec).toBe("UB_533x210x101");
  });

  it("flags an unknown unprotected centre section", () => {
    const params = { ...SAMPLE_PARAMS, uSecSize: "UB_FAKE_999" };
    const { values, unknownFields } = hydrateFormFromFrcParams(params, REF_DATA);

    expect(values.u_sec_size).toBe("");
    expect(unknownFields.u_sec_size).toBe("UB_FAKE_999");
  });

  it("flags an unknown deck id", () => {
    const params = { ...SAMPLE_PARAMS, DeckId: "T_FAKE_999" };
    const { values, unknownFields } = hydrateFormFromFrcParams(params, REF_DATA);

    expect(values.deck_id).toBe("");
    expect(unknownFields.deck_id).toBe("T_FAKE_999");
  });

  it("flags an unknown mesh id", () => {
    const params = { ...SAMPLE_PARAMS, mesh_type: "X_FAKE_999" };
    const { values, unknownFields } = hydrateFormFromFrcParams(params, REF_DATA);

    expect(values.mesh_type).toBe("");
    expect(unknownFields.mesh_type).toBe("X_FAKE_999");
  });

  it("ISO method passes through and parametric compartment fields still populate", () => {
    const params = { ...SAMPLE_PARAMS, method: "iso" };
    const { values } = hydrateFormFromFrcParams(params, REF_DATA);
    expect(values.method).toBe("iso");
    expect(values.Lc).toBe(63);
  });

  it("importedKeys flags only form fields whose source engine key was present", () => {
    // Drop a handful of source keys so we can prove they're excluded.
    const partial: Record<string, unknown> = { ...SAMPLE_PARAMS };
    delete partial.Lc;
    delete partial.Bc;
    delete partial.qf;
    delete partial.side_b_sh_con;
    delete (partial as Record<string, unknown>).SideBsh_con;

    const { importedKeys, values } = hydrateFormFromFrcParams(partial, REF_DATA);

    // Present keys → imported.
    expect(importedKeys.has("span1")).toBe(true);
    expect(importedKeys.has("deck_id")).toBe(true);
    expect(importedKeys.has("u_sec_size")).toBe(true);
    expect(importedKeys.has("side_a_sec")).toBe(true);

    // Absent keys → NOT imported, even though FormValues still has a
    // default value (0) for them.
    expect(importedKeys.has("Lc")).toBe(false);
    expect(importedKeys.has("Bc")).toBe(false);
    expect(importedKeys.has("qf")).toBe(false);
    expect(importedKeys.has("side_b_sh_con")).toBe(false);

    // FormValues fields still carry a numeric zero for the absent keys —
    // important so react-hook-form's reset() doesn't see undefined.
    expect(values.Lc).toBe(0);
    expect(values.qf).toBe(0);
  });

  it("importedKeys is empty when params is empty", () => {
    const { importedKeys } = hydrateFormFromFrcParams({}, REF_DATA);
    expect(importedKeys.size).toBe(0);
  });

  it("importedKeys excludes a field whose source key is explicitly null", () => {
    const params = { ...SAMPLE_PARAMS, Lc: null };
    const { importedKeys } = hydrateFormFromFrcParams(params, REF_DATA);
    expect(importedKeys.has("Lc")).toBe(false);
    // Sibling field unaffected.
    expect(importedKeys.has("Bc")).toBe(true);
  });
});
