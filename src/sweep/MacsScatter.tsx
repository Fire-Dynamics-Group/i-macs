/**
 * Chart 1 of the AnalyticalView's MACS+ Monte Carlo Summary:
 * Fire Load Density (qf) vs Glazing Breakage (window_percent), coloured
 * by Unity Factor 1.0 threshold. Mirrors the matplotlib chart that the
 * MACS+ desktop app produces.
 *
 * Hidden by caller when neither qf nor window_percent varies across the
 * batch — a single-point cluster carries no information.
 */
import { useEffect, useRef } from "react";
import type { Data, Layout } from "plotly.js";

import type { Run } from "../api/client";
import { buildMacsScatterTraces } from "./buildMacsScatterTraces";

interface Props {
  runs: Run[];
}

export function MacsScatter({ runs }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  const { traces, xLabel, yLabel } = buildMacsScatterTraces(runs);

  useEffect(() => {
    if (!ref.current) return;
    if (traces.length === 0) return;
    let cancelled = false;
    (async () => {
      const Plotly = (await import("plotly.js-dist-min")).default;
      if (cancelled || !ref.current) return;
      const layout: Partial<Layout> = {
        margin: { t: 10, r: 20, b: 50, l: 60 },
        xaxis: { title: { text: xLabel } },
        yaxis: { title: { text: yLabel } },
        showlegend: true,
        legend: { orientation: "h", y: -0.25 },
      };
      Plotly.react(
        ref.current,
        traces as unknown as Data[],
        layout,
        { responsive: true, displaylogo: false },
      );
    })();
    return () => {
      cancelled = true;
    };
  }, [runs, traces, xLabel, yLabel]);

  if (traces.length === 0) {
    return (
      <div
        data-testid="macs-scatter-empty"
        className="flex h-64 items-center justify-center rounded border border-dashed border-slate-300 text-sm text-slate-500"
      >
        No successful runs in this batch
      </div>
    );
  }
  return <div ref={ref} className="h-72 w-full" />;
}
