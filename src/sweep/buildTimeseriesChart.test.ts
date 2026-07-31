import { describe, expect, it } from "vitest";

import {
  buildTemperatureChart,
  buildCapacityDeflectionChart,
} from "./buildTimeseriesChart";
import type { TimeSeriesRow } from "../api/client";

const tempRow = (overrides: Partial<TimeSeriesRow> = {}): TimeSeriesRow => ({
  time_step: 1,
  time_min: 0,
  fire_temp: 20,
  lofl_temp: 20,
  mesh_temp: 20,
  slabtop_temp: 20,
  slabbot_temp: 20,
  beam_hot_capacity: 0,
  deflection: 0,
  slab_yield: 0,
  enhancement: 0,
  slab_cap: 0,
  total_plate_capacity: 0,
  utilization_factor: 0,
  ...overrides,
});

describe("buildTemperatureChart", () => {
  it("produces the five MACS+ temperature traces in the expected order", () => {
    const rows = [
      tempRow({
        time_step: 1, time_min: 0,
        slabtop_temp: 20, slabbot_temp: 20, lofl_temp: 20, mesh_temp: 20, fire_temp: 20,
      }),
      tempRow({
        time_step: 2, time_min: 30,
        slabtop_temp: 200, slabbot_temp: 400, lofl_temp: 700, mesh_temp: 300, fire_temp: 800,
      }),
      tempRow({
        time_step: 3, time_min: 60,
        slabtop_temp: 400, slabbot_temp: 600, lofl_temp: 900, mesh_temp: 500, fire_temp: 950,
      }),
    ];

    const { traces } = buildTemperatureChart(rows);

    expect(traces.map((t) => t.name)).toEqual([
      "Slab top",
      "Slab bottom",
      "Unprotected beam",
      "Mesh",
      "Fire",
    ]);

    const x = [0, 30, 60];
    expect(traces[0].x).toEqual(x);
    expect(traces[0].y).toEqual([20, 200, 400]);
    expect(traces[1].y).toEqual([20, 400, 600]);
    expect(traces[2].y).toEqual([20, 700, 900]);
    expect(traces[3].y).toEqual([20, 300, 500]);
    expect(traces[4].y).toEqual([20, 800, 950]);

    for (const t of traces) {
      expect(t.type).toBe("scatter");
      expect(t.mode).toBe("lines");
      expect(t.yaxis).toBeUndefined();
    }
  });

  it("returns no traces when rows is empty", () => {
    expect(buildTemperatureChart([]).traces).toEqual([]);
  });
});

describe("buildCapacityDeflectionChart", () => {
  it("produces three left-axis capacity traces, a horizontal factored-load line, and a right-axis deflection trace", () => {
    const rows = [
      tempRow({
        time_step: 1, time_min: 0,
        slab_cap: 10, beam_hot_capacity: 8, total_plate_capacity: 12, deflection: 0,
      }),
      tempRow({
        time_step: 2, time_min: 30,
        slab_cap: 9, beam_hot_capacity: 4, total_plate_capacity: 10, deflection: 200,
      }),
      tempRow({
        time_step: 3, time_min: 60,
        slab_cap: 7, beam_hot_capacity: 2, total_plate_capacity: 8, deflection: 480,
      }),
    ];

    const { traces } = buildCapacityDeflectionChart(rows, {
      factoredHot: 5,
      timeLimit: 60,
    });

    expect(traces.map((t) => t.name)).toEqual([
      "Slab capacity",
      "Unprotected beam capacity",
      "Total capacity",
      "Factored load",
      "Maximum allowable deflection",
    ]);

    const x = [0, 30, 60];
    expect(traces[0].x).toEqual(x);
    expect(traces[0].y).toEqual([10, 9, 7]);
    expect(traces[1].y).toEqual([8, 4, 2]);
    expect(traces[2].y).toEqual([12, 10, 8]);

    // Factored load: flat horizontal at y=5 spanning 0..time_limit.
    expect(traces[3].x).toEqual([0, 60]);
    expect(traces[3].y).toEqual([5, 5]);

    // Deflection on the right axis.
    expect(traces[4].x).toEqual(x);
    expect(traces[4].y).toEqual([0, 200, 480]);
    expect(traces[4].yaxis).toBe("y2");

    // Capacity traces and factored load live on the left axis.
    expect(traces[0].yaxis).toBeUndefined();
    expect(traces[1].yaxis).toBeUndefined();
    expect(traces[2].yaxis).toBeUndefined();
    expect(traces[3].yaxis).toBeUndefined();
  });

  it("falls back to the last time_min when timeLimit is missing", () => {
    const rows = [
      tempRow({ time_step: 1, time_min: 0, deflection: 0 }),
      tempRow({ time_step: 2, time_min: 45, deflection: 100 }),
    ];
    const { traces } = buildCapacityDeflectionChart(rows, {
      factoredHot: 3,
      timeLimit: null,
    });
    const factored = traces.find((t) => t.name === "Factored load");
    expect(factored?.x).toEqual([0, 45]);
    expect(factored?.y).toEqual([3, 3]);
  });

  it("omits the factored load trace when factoredHot is null", () => {
    const rows = [tempRow({ time_step: 1, time_min: 0 })];
    const { traces } = buildCapacityDeflectionChart(rows, {
      factoredHot: null,
      timeLimit: 60,
    });
    expect(traces.find((t) => t.name === "Factored load")).toBeUndefined();
    expect(traces.find((t) => t.name === "Maximum allowable deflection")).toBeDefined();
  });

  it("returns no traces when rows is empty", () => {
    expect(
      buildCapacityDeflectionChart([], { factoredHot: 5, timeLimit: 60 }).traces,
    ).toEqual([]);
  });
});
