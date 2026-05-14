import { useEffect, useRef } from "react";
import type { Data, Layout } from "plotly.js";

import type { TimeSeriesRow } from "../api/client";
import { buildCapacityDeflectionChart } from "./buildTimeseriesChart";

interface Props {
  rows: TimeSeriesRow[];
  factoredHot: number | null;
  timeLimit: number | null;
}

export function RunCapacityDeflectionChart({ rows, factoredHot, timeLimit }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!ref.current || rows.length === 0) return;
    const { traces } = buildCapacityDeflectionChart(rows, { factoredHot, timeLimit });
    let cancelled = false;
    (async () => {
      const Plotly = (await import("plotly.js-dist-min")).default;
      if (cancelled || !ref.current) return;
      const xMax = timeLimit ?? rows[rows.length - 1]?.time_min ?? 60;
      const layout: Partial<Layout> = {
        margin: { t: 20, r: 70, b: 60, l: 60 },
        xaxis: {
          title: { text: "Time (min)" },
          range: [0, xMax],
          dtick: 5,
        },
        yaxis: { title: { text: "Bending capacity (kN/m²)" } },
        yaxis2: {
          title: { text: "Maximum allowable deflection (mm)" },
          overlaying: "y",
          side: "right",
        },
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
  }, [rows, factoredHot, timeLimit]);

  if (rows.length === 0) return null;
  return <div ref={ref} className="h-80 w-full" />;
}
