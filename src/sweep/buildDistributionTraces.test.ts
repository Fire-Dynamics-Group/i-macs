import { describe, expect, it } from "vitest";

import {
  buildDistributionTraces,
  type DistributionPayload,
} from "./buildDistributionTraces";

const SPAGHETTI_TWO: DistributionPayload = {
  average: [
    [0, 0],
    [5, 100],
    [10, 200],
  ],
  spaghetti: [
    {
      run_id: 1,
      points: [
        [0, 0],
        [5, 80],
        [10, 160],
      ],
    },
    {
      run_id: 2,
      points: [
        [0, 0],
        [5, 120],
        [10, 240],
      ],
    },
  ],
  factored_hot_min: null,
  factored_hot_max: null,
};

describe("buildDistributionTraces", () => {
  it("emits one spaghetti trace per run plus an Average Value trace", () => {
    const { traces } = buildDistributionTraces(SPAGHETTI_TWO);
    // Two run traces + one average trace = 3
    expect(traces.length).toBe(3);
    const names = traces.map((t) => t.name);
    expect(names).toContain("Average Value");
    // Spaghetti runs are not in the legend (showlegend is false on them);
    // they share one legend group label "Recorded Temperature".
    const legendNames = traces.filter((t) => t.showlegend !== false).map((t) => t.name);
    expect(legendNames).toContain("Average Value");
  });

  it("groups the spaghetti traces under a single legend entry called 'Recorded'", () => {
    const { traces } = buildDistributionTraces(SPAGHETTI_TWO);
    const spaghettiTraces = traces.filter((t) => t.name === "Recorded");
    // All run traces share the same legend group name, but only one shows in the legend.
    expect(spaghettiTraces.length).toBeGreaterThan(0);
    const visibleInLegend = spaghettiTraces.filter((t) => t.showlegend !== false);
    expect(visibleInLegend.length).toBe(1);
  });

  it("uses scattergl for spaghetti traces (canvas, not SVG) for perf", () => {
    const { traces } = buildDistributionTraces(SPAGHETTI_TWO);
    const spaghettiTraces = traces.filter((t) => t.name === "Recorded");
    for (const t of spaghettiTraces) {
      expect(t.type).toBe("scattergl");
    }
  });

  it("renders the average in the WebGL layer (scattergl) so it's not hidden by spaghetti", () => {
    // Plotly always draws the WebGL layer on top of the SVG layer regardless of
    // trace order. If the average were plain `scatter` (SVG) it would sit *under*
    // the scattergl spaghetti and be invisible. Keeping it scattergl puts it in
    // the same layer, drawn last → on top.
    const { traces } = buildDistributionTraces(SPAGHETTI_TWO);
    const avg = traces.find((t) => t.name === "Average Value");
    expect(avg!.type).toBe("scattergl");
  });

  it("plots the server-computed average exactly (no client-side recompute)", () => {
    const { traces } = buildDistributionTraces(SPAGHETTI_TWO);
    const avg = traces.find((t) => t.name === "Average Value");
    expect(avg).toBeDefined();
    expect(avg!.x).toEqual([0, 5, 10]);
    expect(avg!.y).toEqual([0, 100, 200]);
  });

  it("emits a single horizontal 'Factored load' line when min == max", () => {
    const { traces } = buildDistributionTraces({
      ...SPAGHETTI_TWO,
      factored_hot_min: 5.6,
      factored_hot_max: 5.6,
    });
    const factored = traces.filter((t) => /factored load/i.test(t.name));
    expect(factored.length).toBe(1);
    expect(factored[0].name).toMatch(/Factored load/i);
    // Horizontal line: same y everywhere.
    const ys = factored[0].y as number[];
    expect(new Set(ys).size).toBe(1);
    expect(ys[0]).toBeCloseTo(5.6);
  });

  it("emits a Factored load (range) band when min < max", () => {
    const { traces } = buildDistributionTraces({
      ...SPAGHETTI_TWO,
      factored_hot_min: 4.0,
      factored_hot_max: 6.0,
    });
    const factored = traces.filter((t) => /factored load/i.test(t.name));
    // Two traces (min line + max line with fill) to form a shaded band.
    expect(factored.length).toBeGreaterThanOrEqual(1);
    const labelled = factored.find((t) => /range/i.test(t.name));
    expect(labelled).toBeDefined();
  });

  it("omits the factored-load trace when both min and max are null", () => {
    const { traces } = buildDistributionTraces(SPAGHETTI_TWO);
    const factored = traces.filter((t) => /factored load/i.test(t.name));
    expect(factored.length).toBe(0);
  });

  it("returns no traces when there are no successful runs (empty payload)", () => {
    const { traces } = buildDistributionTraces({
      average: [],
      spaghetti: [],
      factored_hot_min: null,
      factored_hot_max: null,
    });
    expect(traces).toEqual([]);
  });
});
