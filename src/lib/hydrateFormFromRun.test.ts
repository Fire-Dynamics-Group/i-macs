import { describe, expect, it } from "vitest";

import { hydrateFormFromRun } from "./hydrateFormFromRun";
import type { Run, RefData } from "../api/client";

/**
 * Build a realistic `Run` row matching the sidecar's SELECT * FROM runs shape.
 * Used as the baseline for every test case — individual tests override fields.
 */
function makeRun(overrides: Partial<Run> = {}): Run {
  return {
    // Identifying
    id: 42,
    // Outputs (present on a successful run)
    uf_max: 0.83,
    duration_ms: 1234.5,
    error: null,
    overall_pass: true,
    checks: [],
    // Geometry
    span1: 9.0,
    span2: 9.0,
    numbeam: 2,
    slab_depth: 130,
    // Slab + deck + mesh
    fck: 25,
    conc_type: "NW",
    mesh_type: "ST15C",
    deck_name: "T14",
    // Centre beam
    u_sec_size: "IPE_500",
    u_sec_fy: 355,
    ush_con: 80,
    // Side A
    side_a_sec: "IPE_500",
    side_a_fy: 355,
    side_a_edge: 1,
    side_a_composite: 0,
    side_a_sh_con: 80,
    // Side B
    side_b_sec: "IPE_500",
    side_b_fy: 355,
    side_b_edge: 0,
    side_b_composite: 1,
    side_b_sh_con: 80,
    // Side C
    side_c_sec: "IPE_500",
    side_c_fy: 355,
    side_c_edge: 0,
    side_c_composite: 1,
    side_c_sh_con: 80,
    // Side D
    side_d_sec: "IPE_500",
    side_d_fy: 355,
    side_d_edge: 1,
    side_d_composite: 0,
    side_d_sh_con: 80,
    // Loading
    slab_weight: 2.47,
    cold_perm: 1.2,
    lead_var_act: 5.0,
    othr_var_act: 0.0,
    lead_var_fac: 0.5,
    othr_var_fac: 0.3,
    // Fire
    method: "iso",
    time_limit: 60,
    qf: 511,
    window_percent: 95,
    Lc: 27,
    Bc: 18,
    Hc: 3.6,
    Hw: 1.8,
    Lw: 30,
    Bfac: 720,
    combustion_factor: 0.8,
    growth_rate: 1,
    ...overrides,
  } as Run;
}

describe("hydrateFormFromRun", () => {
  it("maps all input fields from a complete Run row to FormValues", () => {
    const result = hydrateFormFromRun(makeRun());

    // Geometry
    expect(result.span1).toBe(9.0);
    expect(result.span2).toBe(9.0);
    expect(result.numbeam).toBe(2);
    expect(result.slab_depth).toBe(130);
    // Slab
    expect(result.fck).toBe(25);
    expect(result.conc_type).toBe("NW");
    // Mesh + deck
    expect(result.mesh_type).toBe("ST15C");
    expect(result.deck_id).toBe("T14");
    // Loading
    expect(result.slab_weight).toBe(2.47);
    expect(result.cold_perm).toBe(1.2);
    expect(result.lead_var_act).toBe(5.0);
    expect(result.othr_var_act).toBe(0.0);
    expect(result.lead_var_fac).toBe(0.5);
    expect(result.othr_var_fac).toBe(0.3);
    // Fire
    expect(result.method).toBe("iso");
    expect(result.time_limit).toBe(60);
    expect(result.qf).toBe(511);
    expect(result.window_percent).toBe(95);
    expect(result.Lc).toBe(27);
    expect(result.Bc).toBe(18);
    expect(result.Hc).toBe(3.6);
    expect(result.Hw).toBe(1.8);
    expect(result.Lw).toBe(30);
    expect(result.Bfac).toBe(720);
    expect(result.combustion_factor).toBe(0.8);
    expect(result.growth_rate).toBe(1);
  });

  it("renames ush_con → u_sec_sh_con (DB→form column-name mismatch)", () => {
    const result = hydrateFormFromRun(makeRun({ ush_con: 99 }));
    expect(result.u_sec_sh_con).toBe(99);
  });

  it("converts integer fy fields to strings (DB int → form string)", () => {
    // Steel-grade dropdowns store the value as a string ("355"), but the
    // DB persists it as an int (355). The hydration must stringify.
    const result = hydrateFormFromRun(
      makeRun({
        u_sec_fy: 275,
        side_a_fy: 235,
        side_b_fy: 355,
        side_c_fy: 460,
        side_d_fy: 275,
      }),
    );
    expect(result.u_sec_fy).toBe("275");
    expect(result.side_a_fy).toBe("235");
    expect(result.side_b_fy).toBe("355");
    expect(result.side_c_fy).toBe("460");
    expect(result.side_d_fy).toBe("275");
  });

  it("maps all four perimeter sides (sec / fy / edge / composite / sh_con)", () => {
    const result = hydrateFormFromRun(
      makeRun({
        side_a_sec: "UB457x191x98",
        side_a_edge: 1,
        side_a_composite: 0,
        side_a_sh_con: 75,
        side_b_sec: "UB457x191x67",
        side_b_edge: 0,
        side_b_composite: 1,
        side_b_sh_con: 85,
        side_c_sec: "UB406x178x60",
        side_c_edge: 1,
        side_c_composite: 1,
        side_c_sh_con: 90,
        side_d_sec: "UB356x171x57",
        side_d_edge: 0,
        side_d_composite: 0,
        side_d_sh_con: 95,
      }),
    );
    expect(result.side_a_sec).toBe("UB457x191x98");
    expect(result.side_a_edge).toBe(1);
    expect(result.side_a_composite).toBe(0);
    expect(result.side_a_sh_con).toBe(75);
    expect(result.side_b_sec).toBe("UB457x191x67");
    expect(result.side_b_edge).toBe(0);
    expect(result.side_b_composite).toBe(1);
    expect(result.side_b_sh_con).toBe(85);
    expect(result.side_c_sec).toBe("UB406x178x60");
    expect(result.side_c_edge).toBe(1);
    expect(result.side_c_composite).toBe(1);
    expect(result.side_c_sh_con).toBe(90);
    expect(result.side_d_sec).toBe("UB356x171x57");
    expect(result.side_d_edge).toBe(0);
    expect(result.side_d_composite).toBe(0);
    expect(result.side_d_sh_con).toBe(95);
  });

  it("handles errored-run rows: outputs nullable, but every input field still populated", () => {
    const erroredRun = makeRun({
      // Outputs that the engine zeroes / nulls on failure
      uf_max: null,
      duration_ms: null,
      error: "COMException: insufficient capacity",
      overall_pass: false,
    });
    const result = hydrateFormFromRun(erroredRun);

    // Inputs still recoverable for the retry case
    expect(result.span1).toBe(9.0);
    expect(result.method).toBe("iso");
    expect(result.deck_id).toBe("T14");
    expect(result.u_sec_size).toBe("IPE_500");
    expect(result.side_a_sec).toBe("IPE_500");
  });

  it("reverse-looks-up deck_id from deck_name when refData is supplied", () => {
    // Real-world case: a deck's `name` is a human-friendly label and its
    // dict key (`id`) is what the form's <select> uses. The DB stores
    // deck_name, so hydration needs the refData to recover the id.
    const refData = {
      sections: {},
      decks: {
        T14: { name: "TR 80+ trough deck" },
        T15: { name: "TR 60+ trough deck" },
      },
      meshes: {},
      defaults: {},
      occupancy_presets: [],
    } as unknown as RefData;

    const result = hydrateFormFromRun(
      makeRun({ deck_name: "TR 60+ trough deck" }),
      refData,
    );
    expect(result.deck_id).toBe("T15");
  });

  it("falls back to deck_name when refData is omitted (best-effort hydration)", () => {
    // No refData → use deck_name as the id. For standard decks where
    // id == name this is correct; for custom decks the form will show
    // the placeholder option until the user re-picks.
    const result = hydrateFormFromRun(makeRun({ deck_name: "T14" }));
    expect(result.deck_id).toBe("T14");
  });

  it("uses deck_name as deck_id when refData lookup misses (unknown deck)", () => {
    const refData = {
      sections: {},
      decks: { T14: { name: "TR 80+ trough deck" } },
      meshes: {},
      defaults: {},
      occupancy_presets: [],
    } as unknown as RefData;

    // refData has T14 but not the deck stored on this run.
    const result = hydrateFormFromRun(
      makeRun({ deck_name: "CustomDeckXYZ" }),
      refData,
    );
    expect(result.deck_id).toBe("CustomDeckXYZ");
  });
});
