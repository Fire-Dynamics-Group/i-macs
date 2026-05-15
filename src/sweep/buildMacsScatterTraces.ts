/**
 * Pure trace builder for the AnalyticalView's MACS+ scatter (chart 1):
 * Fire Load Density (qf) vs Glazing Breakage (window_percent), with marker
 * colour split by Unity Factor 1.0 threshold. Mirrors the matplotlib
 * `_render_scatter_chart` in report_docx but stays in-browser for the
 * dashboard.
 *
 * Errored runs are excluded — they have no uf_max to bucket and no chart
 * value either (matches the desktop MACS+ scatter).
 */
import type { Run } from "../api/client";

export interface MacsScatterTrace {
  x: number[];
  y: number[];
  mode: "markers";
  type: "scatter";
  name: string;
  marker: { color: string; size?: number };
}

export interface BuiltMacsScatter {
  traces: MacsScatterTrace[];
  xLabel: string;
  yLabel: string;
}

// Brand palette — keep in step with report_docx._render_scatter_chart.
const PASS_COLOR = "#4798EA"; // mid blue — UF < 1.0
const FAIL_COLOR = "coral"; // coral — UF >= 1.0

export function buildMacsScatterTraces(runs: Run[]): BuiltMacsScatter {
  const passX: number[] = [];
  const passY: number[] = [];
  const failX: number[] = [];
  const failY: number[] = [];

  for (const run of runs) {
    if (run.error) continue;
    const qf = (run as Record<string, unknown>).qf;
    const wp = (run as Record<string, unknown>).window_percent;
    const uf = run.uf_max;
    if (qf == null || wp == null) continue;
    if (uf != null && uf <= 1.0) {
      passX.push(Number(qf));
      passY.push(Number(wp));
    } else {
      failX.push(Number(qf));
      failY.push(Number(wp));
    }
  }

  const traces: MacsScatterTrace[] = [];
  if (passX.length > 0) {
    traces.push({
      x: passX,
      y: passY,
      mode: "markers",
      type: "scatter",
      name: "Unity factor < 1.0",
      marker: { color: PASS_COLOR, size: 6 },
    });
  }
  if (failX.length > 0) {
    traces.push({
      x: failX,
      y: failY,
      mode: "markers",
      type: "scatter",
      name: "Unity factor >= 1.0",
      marker: { color: FAIL_COLOR, size: 6 },
    });
  }

  return {
    traces,
    xLabel: "Fire Load Density (MJ/m²)",
    yLabel: "Glazing Breakage (%)",
  };
}
