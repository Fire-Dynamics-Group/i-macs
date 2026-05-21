import { describe, expect, it } from "vitest";
import { buildSweepPayload } from "./buildSweepPayload";

describe("buildSweepPayload", () => {
  it("builds a single-varying-param payload from a parsed list", () => {
    const payload = buildSweepPayload({
      analysisMethod: "iso",
      fixed: { span1: 9, span2: 9 },
      varying: {
        qf: { list: [400, 510, 720] },
      },
    });
    expect(payload).toEqual({
      analysis_method: "iso",
      sampling: "paired",
      sweep: { qf: [400, 510, 720] },
      fixed: { span1: 9, span2: 9 },
      totalRuns: 3,
    });
  });

  it("expands min/max/step into a range", () => {
    const payload = buildSweepPayload({
      analysisMethod: "iso",
      fixed: { span1: 9 },
      varying: {
        qf: { range: { min: 100, max: 500, step: 100 } },
      },
    });
    expect(payload.sweep.qf).toEqual([100, 200, 300, 400, 500]);
  });

  it("handles non-integer steps without floating-point drift", () => {
    const payload = buildSweepPayload({
      analysisMethod: "iso",
      fixed: {},
      varying: {
        qf: { range: { min: 0.1, max: 0.5, step: 0.1 } },
      },
    });
    expect(payload.sweep.qf).toEqual([0.1, 0.2, 0.3, 0.4, 0.5]);
  });

  it("prefers CSV values over list values over range when multiple sources are present", () => {
    const payload = buildSweepPayload({
      analysisMethod: "iso",
      fixed: {},
      varying: {
        qf: {
          csv: [1, 2, 3],
          list: [10, 20, 30],
          range: { min: 100, max: 500, step: 100 },
        },
      },
    });
    expect(payload.sweep.qf).toEqual([1, 2, 3]);
  });

  it("falls back from CSV to list when CSV is empty", () => {
    const payload = buildSweepPayload({
      analysisMethod: "iso",
      fixed: {},
      varying: {
        qf: {
          csv: [],
          list: [10, 20],
          range: { min: 1, max: 9, step: 1 },
        },
      },
    });
    expect(payload.sweep.qf).toEqual([10, 20]);
  });

  it("falls back from list to range when list is empty", () => {
    const payload = buildSweepPayload({
      analysisMethod: "iso",
      fixed: {},
      varying: {
        qf: { list: [], range: { min: 1, max: 3, step: 1 } },
      },
    });
    expect(payload.sweep.qf).toEqual([1, 2, 3]);
  });

  it("encodes multiple varying parameters in submit-payload order", () => {
    const payload = buildSweepPayload({
      analysisMethod: "parametric",
      fixed: { span1: 9 },
      varying: {
        qf: { list: [400, 500] },
        window_percent: { list: [50, 80] },
      },
    });
    expect(payload.sweep).toEqual({
      qf: [400, 500],
      window_percent: [50, 80],
    });
    expect(Object.keys(payload.sweep)).toEqual(["qf", "window_percent"]);
  });

  it("omits a varying entry whose source has no usable values", () => {
    const payload = buildSweepPayload({
      analysisMethod: "iso",
      fixed: {},
      varying: {
        qf: { list: [400, 500] },
        window_percent: { list: [], range: undefined },
      },
    });
    expect(payload.sweep).toEqual({ qf: [400, 500] });
    expect("window_percent" in payload.sweep).toBe(false);
  });

  it("passes analysis_method and fixed through unchanged", () => {
    const payload = buildSweepPayload({
      analysisMethod: "parametric",
      fixed: { span1: 9, span2: 9, fck: 25, slab_depth: 130 },
      varying: { qf: { list: [400] } },
    });
    expect(payload.analysis_method).toBe("parametric");
    expect(payload.fixed).toEqual({ span1: 9, span2: 9, fck: 25, slab_depth: 130 });
  });

  it("returns an empty range when step is zero or negative", () => {
    expect(
      buildSweepPayload({
        analysisMethod: "iso",
        fixed: {},
        varying: { qf: { range: { min: 1, max: 5, step: 0 } } },
      }).sweep,
    ).toEqual({});
    expect(
      buildSweepPayload({
        analysisMethod: "iso",
        fixed: {},
        varying: { qf: { range: { min: 5, max: 1, step: 1 } } },
      }).sweep,
    ).toEqual({});
  });

  it("paired total is min of resolved lengths, not a cartesian product", () => {
    const payload = buildSweepPayload({
      analysisMethod: "iso",
      fixed: {},
      varying: {
        qf: { list: [400, 500, 600] },
        window_percent: { list: [50, 80] },
      },
    });
    // paired iterates row-wise — min(3, 2) = 2, not 3 * 2 = 6
    expect(payload.totalRuns).toBe(2);
  });

  it("paired total equals N when both arrays are equal length", () => {
    const payload = buildSweepPayload({
      analysisMethod: "parametric",
      fixed: {},
      varying: {
        qf: { list: [300, 500, 700] },
        window_percent: { list: [50, 80, 95] },
      },
    });
    expect(payload.totalRuns).toBe(3);
  });

  it("reports zero runs when no varying entry has usable values", () => {
    const payload = buildSweepPayload({
      analysisMethod: "iso",
      fixed: { span1: 9 },
      varying: {
        qf: { list: [] },
      },
    });
    expect(payload.totalRuns).toBe(0);
  });

  it("includes sampling: 'paired' in the request body", () => {
    const payload = buildSweepPayload({
      analysisMethod: "iso",
      fixed: {},
      varying: { qf: { list: [1, 2, 3] } },
    });
    expect(payload.sampling).toBe("paired");
  });
});
