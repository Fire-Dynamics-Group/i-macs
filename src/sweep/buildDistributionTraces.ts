/**
 * Pure trace builder for the AnalyticalView's three distribution charts
 * (Total Capacity, Unprotected Beam Temperature, Reinforcement Bar
 * Temperature). Mirrors the MACS+ desktop "Monte Carlo Summary" charts.
 *
 * Inputs come from GET /api/batches/:id/distribution. The server has
 * already computed the exact average and stride-sampled the spaghetti
 * lines — this module just shapes them for Plotly.
 *
 * Spaghetti uses `scattergl` so canvas rendering keeps the page pannable
 * at 10k samples (SVG chokes well before that).
 */

export interface DistributionPoint extends Array<number> {
  0: number; // time_min
  1: number; // value
}

export interface DistributionSpaghetti {
  run_id: number;
  points: DistributionPoint[];
}

export interface DistributionPayload {
  average: DistributionPoint[];
  spaghetti: DistributionSpaghetti[];
  factored_hot_min: number | null;
  factored_hot_max: number | null;
}

export interface DistributionTrace {
  x: number[];
  y: number[];
  mode: "lines";
  type: "scattergl" | "scatter";
  name: string;
  line: { color: string; width?: number; dash?: string };
  legendgroup?: string;
  showlegend?: boolean;
  fill?: "tonexty";
  fillcolor?: string;
  hoverinfo?: "skip" | "all";
}

export interface BuiltDistribution {
  traces: DistributionTrace[];
}

// Brand palette — keep in step with report_docx._render_timeseries_chart so
// the in-browser and DOCX charts stay visually consistent.
const SPAGHETTI_COLOR = "#4798EA"; // mid blue, solid — individual runs
const AVERAGE_COLOR = "coral"; // orange — average curve (matches MACS+ #26)
const FACTORED_COLOR = "#DC2626"; // crimson — factored load
const FACTORED_BAND_FILL = "rgba(220, 38, 38, 0.15)";

// Tolerance for treating `factored_hot_min == factored_hot_max` as a single
// horizontal line. 1e-6 is safe — factored loads are in kN/m² (single-digit
// units), so any real spread will be far larger.
const FACTORED_EPSILON = 1e-6;

export function buildDistributionTraces(
  payload: DistributionPayload,
): BuiltDistribution {
  const traces: DistributionTrace[] = [];

  const hasRuns = payload.spaghetti.length > 0 || payload.average.length > 0;
  if (!hasRuns) {
    return { traces };
  }

  // ── Spaghetti — one scattergl trace per run, all sharing one legend
  // group so the legend stays clean (only the first is visible in the legend).
  payload.spaghetti.forEach((run, idx) => {
    traces.push({
      x: run.points.map((p) => p[0]),
      y: run.points.map((p) => p[1]),
      mode: "lines",
      type: "scattergl",
      name: "Recorded",
      legendgroup: "spaghetti",
      showlegend: idx === 0,
      line: { color: SPAGHETTI_COLOR, width: 1 },
      hoverinfo: "skip",
    });
  });

  // ── Average — exact, computed server-side over all successful runs.
  if (payload.average.length > 0) {
    traces.push({
      x: payload.average.map((p) => p[0]),
      y: payload.average.map((p) => p[1]),
      mode: "lines",
      type: "scatter",
      name: "Average Value",
      line: { color: AVERAGE_COLOR, width: 2 },
    });
  }

  // ── Factored load horizontal line (capacity chart only). The endpoint
  // sends null for non-capacity columns; nothing to draw in that case.
  const fMin = payload.factored_hot_min;
  const fMax = payload.factored_hot_max;
  if (fMin != null && fMax != null && payload.average.length > 0) {
    const xs = payload.average.map((p) => p[0]);
    const x0 = xs[0];
    const x1 = xs[xs.length - 1];
    const xLine = [x0, x1];
    const range = Math.abs(fMax - fMin);
    if (range <= FACTORED_EPSILON) {
      // Single line.
      traces.push({
        x: xLine,
        y: [fMin, fMin],
        mode: "lines",
        type: "scatter",
        name: "Factored load",
        line: { color: FACTORED_COLOR, width: 1.5, dash: "dash" },
      });
    } else {
      // Min/max band — Plotly's fill="tonexty" against the previous trace.
      traces.push({
        x: xLine,
        y: [fMin, fMin],
        mode: "lines",
        type: "scatter",
        name: "Factored load (min)",
        line: { color: FACTORED_COLOR, width: 1 },
        showlegend: false,
        hoverinfo: "skip",
      });
      traces.push({
        x: xLine,
        y: [fMax, fMax],
        mode: "lines",
        type: "scatter",
        name: "Factored load (range)",
        line: { color: FACTORED_COLOR, width: 1 },
        fill: "tonexty",
        fillcolor: FACTORED_BAND_FILL,
      });
    }
  }

  return { traces };
}
