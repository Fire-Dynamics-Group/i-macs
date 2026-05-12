import { describe, expect, it } from "vitest";

import {
  buildScatterTraces,
  detectVaryingFields,
} from "./buildScatterTraces";

const VARYABLE = ["qf", "window_percent", "slab_depth", "span1"];

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

describe("detectVaryingFields", () => {
  it("returns the candidate fields whose values differ across runs", () => {
    const runs = [
      r({ qf: 400, window_percent: 50, slab_depth: 130 }),
      r({ qf: 500, window_percent: 50, slab_depth: 130 }),
      r({ qf: 600, window_percent: 50, slab_depth: 130 }),
    ];
    expect(detectVaryingFields(runs, VARYABLE)).toEqual(["qf"]);
  });

  it("preserves the order of the candidate list when multiple fields vary", () => {
    const runs = [
      r({ qf: 400, window_percent: 50, span1: 9 }),
      r({ qf: 500, window_percent: 80, span1: 12 }),
    ];
    expect(detectVaryingFields(runs, VARYABLE)).toEqual(["qf", "window_percent", "span1"]);
  });

  it("ignores fields that are constant or all undefined", () => {
    const runs = [r({ qf: 400 }), r({ qf: 400 }), r({ qf: 400 })];
    expect(detectVaryingFields(runs, VARYABLE)).toEqual([]);
  });

  it("returns empty when given no runs", () => {
    expect(detectVaryingFields([], VARYABLE)).toEqual([]);
  });
});

describe("buildScatterTraces", () => {
  it("returns one successful-runs trace when only one parameter varies", () => {
    const runs = [
      r({ id: 1, qf: 400, uf_max: 0.4 }),
      r({ id: 2, qf: 500, uf_max: 0.6 }),
      r({ id: 3, qf: 600, uf_max: 0.8 }),
    ];
    const { traces, xLabel, yLabel } = buildScatterTraces(runs, "qf");
    expect(xLabel).toBe("qf");
    expect(yLabel).toBe("uf_max");
    expect(traces.length).toBe(1);
    expect(traces[0].x).toEqual([400, 500, 600]);
    expect(traces[0].y).toEqual([0.4, 0.6, 0.8]);
  });

  it("groups successful runs into one trace per second-varying value when colorBy is set", () => {
    const runs = [
      r({ id: 1, qf: 400, window_percent: 50, uf_max: 0.4 }),
      r({ id: 2, qf: 500, window_percent: 50, uf_max: 0.6 }),
      r({ id: 3, qf: 400, window_percent: 80, uf_max: 0.5 }),
      r({ id: 4, qf: 500, window_percent: 80, uf_max: 0.7 }),
    ];
    const { traces } = buildScatterTraces(runs, "qf", "window_percent");
    // Two non-error traces (one per window_percent value), no error trace.
    expect(traces.length).toBe(2);
    const groupNames = traces.map((t) => t.name).sort();
    expect(groupNames).toEqual(["window_percent = 50", "window_percent = 80"]);
  });

  it("emits a separate red 'Errored' trace for runs with errors", () => {
    const runs = [
      r({ id: 1, qf: 400, uf_max: 0.4, error: null }),
      r({ id: 2, qf: 500, uf_max: null, error: "COM error" }),
    ];
    const { traces } = buildScatterTraces(runs, "qf");
    expect(traces.length).toBe(2);
    const errored = traces.find((t) => t.name === "Errored");
    expect(errored).toBeDefined();
    expect(errored!.x).toEqual([500]);
  });

  it("returns no traces when runs list is empty", () => {
    const { traces } = buildScatterTraces([], "qf");
    expect(traces).toEqual([]);
  });
});
