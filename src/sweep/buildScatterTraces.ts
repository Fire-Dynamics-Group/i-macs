/**
 * Pure-function trace builder for the batch dashboard's Plotly scatter.
 *
 * Inputs are the dashboard's current snapshot of runs plus the names of the
 * varying parameters; outputs are Plotly-shaped data series and axis labels.
 * Kept separate from the Plotly DOM wrapper so it can be vitest-tested in
 * isolation — Plotly itself is hard to drive in jsdom.
 */
import type { Run } from "../api/client";

export interface ScatterTrace {
  x: number[];
  y: number[];
  mode: "markers";
  type: "scatter";
  name: string;
  marker: { color: string; symbol?: string };
  text?: string[];
}

export interface BuiltScatter {
  traces: ScatterTrace[];
  xLabel: string;
  yLabel: string;
}

const COLOR_PALETTE = [
  "#2563eb",
  "#10b981",
  "#f59e0b",
  "#a855f7",
  "#0ea5e9",
  "#84cc16",
  "#ec4899",
];

const ERROR_COLOR = "#dc2626";

export function detectVaryingFields(
  runs: Array<Record<string, unknown>>,
  candidates: string[],
): string[] {
  if (runs.length === 0) return [];
  const out: string[] = [];
  for (const field of candidates) {
    const values = runs
      .map((r) => r[field])
      .filter((v) => v !== undefined && v !== null);
    if (values.length === 0) continue;
    const uniq = new Set(values);
    if (uniq.size > 1) out.push(field);
  }
  return out;
}

export function buildScatterTraces(
  runs: Run[],
  varyingX: string,
  varyingColor?: string,
): BuiltScatter {
  const successful = runs.filter((r) => !r.error);
  const errored = runs.filter((r) => !!r.error);
  const traces: ScatterTrace[] = [];

  if (successful.length > 0) {
    if (varyingColor) {
      const groups = new Map<string, Run[]>();
      for (const run of successful) {
        const key = String((run as Record<string, unknown>)[varyingColor] ?? "—");
        const list = groups.get(key) ?? [];
        list.push(run);
        groups.set(key, list);
      }
      let colorIdx = 0;
      for (const [colorValue, rows] of groups) {
        traces.push({
          x: rows.map((r) => Number((r as Record<string, unknown>)[varyingX])),
          y: rows.map((r) => Number(r.uf_max ?? 0)),
          mode: "markers",
          type: "scatter",
          name: `${varyingColor} = ${colorValue}`,
          marker: { color: COLOR_PALETTE[colorIdx % COLOR_PALETTE.length] },
        });
        colorIdx += 1;
      }
    } else {
      traces.push({
        x: successful.map((r) => Number((r as Record<string, unknown>)[varyingX])),
        y: successful.map((r) => Number(r.uf_max ?? 0)),
        mode: "markers",
        type: "scatter",
        name: "Runs",
        marker: { color: COLOR_PALETTE[0] },
      });
    }
  }

  if (errored.length > 0) {
    traces.push({
      x: errored.map((r) => Number((r as Record<string, unknown>)[varyingX])),
      y: errored.map(() => 0),
      mode: "markers",
      type: "scatter",
      name: "Errored",
      marker: { color: ERROR_COLOR, symbol: "x" },
    });
  }

  return { traces, xLabel: varyingX, yLabel: "uf_max" };
}
