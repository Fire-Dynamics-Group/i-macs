import { describe, expect, it } from "vitest";

import { governingCriticalTemp } from "./governingCriticalTemp";
import type { Run } from "../api/client";

function makeRun(overrides: Partial<Run> = {}): Run {
  return {
    id: 1,
    uf_max: 0.42,
    duration_ms: 120,
    error: null,
    overall_pass: true,
    checks: [],
    side_a_critical_temp: 706,
    side_b_critical_temp: 728,
    side_c_critical_temp: 650,
    side_d_critical_temp: 728,
    ...overrides,
  } as Run;
}

describe("governingCriticalTemp", () => {
  it("returns the lowest critical temperature across sides and which side governs", () => {
    expect(governingCriticalTemp(makeRun())).toEqual({ side: "C", temp: 650 });
  });

  it("breaks ties in favour of the first side in A→D order", () => {
    const run = makeRun({
      side_a_critical_temp: 706,
      side_b_critical_temp: 706,
      side_c_critical_temp: 728,
      side_d_critical_temp: 728,
    });
    expect(governingCriticalTemp(run)).toEqual({ side: "A", temp: 706 });
  });

  it("coerces string values from the API", () => {
    const run = makeRun({
      side_a_critical_temp: "706.4",
      side_b_critical_temp: "690.2",
      side_c_critical_temp: null,
      side_d_critical_temp: null,
    });
    expect(governingCriticalTemp(run)).toEqual({ side: "B", temp: 690.2 });
  });

  it("skips sides with no critical temperature", () => {
    const run = makeRun({
      side_a_critical_temp: null,
      side_c_critical_temp: undefined,
    });
    expect(governingCriticalTemp(run)).toEqual({ side: "B", temp: 728 });
  });

  it("returns null when no side has a critical temperature", () => {
    const run = makeRun({
      side_a_critical_temp: null,
      side_b_critical_temp: null,
      side_c_critical_temp: null,
      side_d_critical_temp: null,
    });
    expect(governingCriticalTemp(run)).toBeNull();
  });

  it("returns null for an errored run even if stale side values are present", () => {
    expect(governingCriticalTemp(makeRun({ error: "COMError: boom" }))).toBeNull();
  });
});
