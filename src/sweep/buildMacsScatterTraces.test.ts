import { describe, expect, it } from "vitest";

import { buildMacsScatterTraces } from "./buildMacsScatterTraces";

function r(props: Record<string, unknown>) {
  return {
    id: 1,
    uf_max: 0.5,
    duration_ms: 100,
    error: null,
    overall_pass: true,
    checks: [],
    ...props,
  };
}

describe("buildMacsScatterTraces", () => {
  it("plots qf vs window_percent on X/Y axes", () => {
    const runs = [
      r({ id: 1, qf: 400, window_percent: 50, uf_max: 0.4 }),
      r({ id: 2, qf: 500, window_percent: 80, uf_max: 0.6 }),
    ];
    const { xLabel, yLabel } = buildMacsScatterTraces(runs);
    expect(xLabel).toMatch(/Fire ?load|Fire Load Density|MJ\/m/i);
    expect(yLabel).toMatch(/Glazing Breakage|window/i);
  });

  it("splits runs by UF threshold 1.0 into two traces (pass blue, fail orange/red)", () => {
    const runs = [
      r({ id: 1, qf: 400, window_percent: 50, uf_max: 0.4 }),
      r({ id: 2, qf: 500, window_percent: 80, uf_max: 0.9 }),
      r({ id: 3, qf: 700, window_percent: 95, uf_max: 1.2 }),
      r({ id: 4, qf: 600, window_percent: 90, uf_max: 1.05 }),
    ];
    const { traces } = buildMacsScatterTraces(runs);
    // Two non-error traces (one per UF bucket).
    expect(traces.length).toBe(2);
    const passing = traces.find((t) => /< ?1.0/.test(t.name));
    const failing = traces.find((t) => />=? ?1.0/.test(t.name));
    expect(passing).toBeDefined();
    expect(failing).toBeDefined();
    // qf=400 (uf 0.4) and qf=500 (uf 0.9) are pass.
    expect(passing!.x).toEqual([400, 500]);
    expect(passing!.y).toEqual([50, 80]);
    // qf=700 (uf 1.2) and qf=600 (uf 1.05) are fail.
    expect(failing!.x).toEqual([700, 600]);
    expect(failing!.y).toEqual([95, 90]);
  });

  it("excludes errored runs entirely", () => {
    const runs = [
      r({ id: 1, qf: 400, window_percent: 50, uf_max: 0.4, error: null }),
      r({ id: 2, qf: 500, window_percent: 80, uf_max: null, error: "COM error" }),
    ];
    const { traces } = buildMacsScatterTraces(runs);
    const allX = traces.flatMap((t) => t.x as number[]);
    expect(allX).not.toContain(500);
    expect(allX).toContain(400);
  });

  it("returns no traces when no successful runs exist", () => {
    const runs = [
      r({ id: 1, qf: 400, window_percent: 50, uf_max: null, error: "boom" }),
    ];
    const { traces } = buildMacsScatterTraces(runs);
    expect(traces).toEqual([]);
  });

  it("uses MACS+ marker colours (blue for pass, coral/orange/red for fail)", () => {
    const runs = [
      r({ id: 1, qf: 400, window_percent: 50, uf_max: 0.4 }),
      r({ id: 2, qf: 700, window_percent: 95, uf_max: 1.2 }),
    ];
    const { traces } = buildMacsScatterTraces(runs);
    const passing = traces.find((t) => /< ?1.0/.test(t.name));
    const failing = traces.find((t) => />=? ?1.0/.test(t.name));
    // Blue family for pass (anything with hex starting #2 / #4 / referencing blue).
    expect(passing!.marker.color.toLowerCase()).toMatch(/#[2-4][0-9a-f]{5}|blue/i);
    // Orange/coral/red for fail.
    expect(failing!.marker.color.toLowerCase()).toMatch(/coral|orange|#f|#e|#d|red/i);
  });
});
