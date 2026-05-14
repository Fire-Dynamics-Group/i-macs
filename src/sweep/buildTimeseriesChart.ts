import type { TimeSeriesRow } from "../api/client";

export interface TimeseriesTrace {
  x: number[];
  y: number[];
  mode: "lines" | "lines+markers";
  type: "scatter";
  name: string;
  line: { color: string; dash?: "solid" | "dash" | "dot" };
  yaxis?: "y2";
}

export interface BuiltTimeseriesChart {
  traces: TimeseriesTrace[];
}

const TEMP_COLOURS = {
  slabTop: "#1f6feb",
  slabBottom: "#0b3d91",
  unprotectedBeam: "#e83e8c",
  mesh: "#2ecc71",
  fire: "#f1c40f",
} as const;

const CAPACITY_COLOURS = {
  slabCap: "#1f6feb",
  beamCap: "#2ecc71",
  totalCap: "#5dade2",
  factoredLoad: "#6c757d",
  deflection: "#e83e8c",
} as const;

export function buildTemperatureChart(rows: TimeSeriesRow[]): BuiltTimeseriesChart {
  if (rows.length === 0) return { traces: [] };
  const x = rows.map((r) => r.time_min);
  return {
    traces: [
      {
        x, y: rows.map((r) => r.slabtop_temp),
        mode: "lines", type: "scatter", name: "Slab top",
        line: { color: TEMP_COLOURS.slabTop },
      },
      {
        x, y: rows.map((r) => r.slabbot_temp),
        mode: "lines", type: "scatter", name: "Slab bottom",
        line: { color: TEMP_COLOURS.slabBottom },
      },
      {
        x, y: rows.map((r) => r.lofl_temp),
        mode: "lines", type: "scatter", name: "Unprotected beam",
        line: { color: TEMP_COLOURS.unprotectedBeam },
      },
      {
        x, y: rows.map((r) => r.mesh_temp),
        mode: "lines", type: "scatter", name: "Mesh",
        line: { color: TEMP_COLOURS.mesh },
      },
      {
        x, y: rows.map((r) => r.fire_temp),
        mode: "lines", type: "scatter", name: "Fire",
        line: { color: TEMP_COLOURS.fire },
      },
    ],
  };
}

export interface CapacityDeflectionOpts {
  factoredHot: number | null;
  timeLimit: number | null;
}

export function buildCapacityDeflectionChart(
  rows: TimeSeriesRow[],
  opts: CapacityDeflectionOpts,
): BuiltTimeseriesChart {
  if (rows.length === 0) return { traces: [] };
  const x = rows.map((r) => r.time_min);
  const xEnd = opts.timeLimit ?? x[x.length - 1];

  const traces: TimeseriesTrace[] = [
    {
      x, y: rows.map((r) => r.slab_cap),
      mode: "lines", type: "scatter", name: "Slab capacity",
      line: { color: CAPACITY_COLOURS.slabCap },
    },
    {
      x, y: rows.map((r) => r.beam_hot_capacity),
      mode: "lines", type: "scatter", name: "Unprotected beam capacity",
      line: { color: CAPACITY_COLOURS.beamCap },
    },
    {
      x, y: rows.map((r) => r.total_plate_capacity),
      mode: "lines", type: "scatter", name: "Total capacity",
      line: { color: CAPACITY_COLOURS.totalCap },
    },
  ];

  if (opts.factoredHot != null) {
    traces.push({
      x: [0, xEnd],
      y: [opts.factoredHot, opts.factoredHot],
      mode: "lines", type: "scatter", name: "Factored load",
      line: { color: CAPACITY_COLOURS.factoredLoad, dash: "dash" },
    });
  }

  traces.push({
    x, y: rows.map((r) => r.deflection),
    mode: "lines", type: "scatter", name: "Maximum allowable deflection",
    line: { color: CAPACITY_COLOURS.deflection },
    yaxis: "y2",
  });

  return { traces };
}
