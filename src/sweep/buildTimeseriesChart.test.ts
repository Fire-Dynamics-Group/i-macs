import { describe, expect, it } from "vitest";

import { buildTimeseriesChart } from "./buildTimeseriesChart";
import type { TimeSeriesRow } from "../api/client";

const row = (t: number, fire: number, uf: number): TimeSeriesRow => ({
  time_step: t * 10,
  time_min: t,
  fire_temp: fire,
  utilization_factor: uf,
  total_plate_capacity: 0,
});

describe("buildTimeseriesChart", () => {
  it("produces two traces — UF on the left axis, fire_temp on the right", () => {
    const rows = [
      row(0, 20, 0),
      row(10, 600, 0.3),
      row(30, 900, 0.7),
      row(60, 700, 0.5),
    ];
    const { traces } = buildTimeseriesChart(rows);
    expect(traces.length).toBe(2);
    const uf = traces.find((t) => t.name === "Utilisation factor");
    const fire = traces.find((t) => t.name === "Fire temperature");
    expect(uf).toBeDefined();
    expect(fire).toBeDefined();
    expect(uf!.x).toEqual([0, 10, 30, 60]);
    expect(uf!.y).toEqual([0, 0.3, 0.7, 0.5]);
    expect(fire!.y).toEqual([20, 600, 900, 700]);
    expect(fire!.yaxis).toBe("y2");
    expect(uf!.yaxis).toBeUndefined();
  });

  it("returns empty traces when given no rows", () => {
    const { traces } = buildTimeseriesChart([]);
    expect(traces).toEqual([]);
  });
});
