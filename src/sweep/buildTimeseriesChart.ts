import type { TimeSeriesRow } from "../api/client";

export interface TimeseriesTrace {
  x: number[];
  y: number[];
  mode: "lines" | "lines+markers";
  type: "scatter";
  name: string;
  line: { color: string };
  yaxis?: "y2";
}

export interface BuiltTimeseriesChart {
  traces: TimeseriesTrace[];
}

export function buildTimeseriesChart(rows: TimeSeriesRow[]): BuiltTimeseriesChart {
  if (rows.length === 0) return { traces: [] };
  const x = rows.map((r) => r.time_min);
  return {
    traces: [
      {
        x,
        y: rows.map((r) => r.utilization_factor),
        mode: "lines",
        type: "scatter",
        name: "Utilisation factor",
        line: { color: "#2563eb" },
      },
      {
        x,
        y: rows.map((r) => r.fire_temp),
        mode: "lines",
        type: "scatter",
        name: "Fire temperature",
        line: { color: "#f97316" },
        yaxis: "y2",
      },
    ],
  };
}
