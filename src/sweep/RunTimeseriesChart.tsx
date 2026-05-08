import { useEffect, useRef } from "react";
import type { Data, Layout } from "plotly.js";

import type { TimeSeriesRow } from "../api/client";
import { buildTimeseriesChart } from "./buildTimeseriesChart";

interface Props {
  rows: TimeSeriesRow[];
}

export function RunTimeseriesChart({ rows }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!ref.current || rows.length === 0) return;
    const { traces } = buildTimeseriesChart(rows);
    let cancelled = false;
    (async () => {
      const Plotly = (await import("plotly.js-dist-min")).default;
      if (cancelled || !ref.current) return;
      const layout: Partial<Layout> = {
        margin: { t: 20, r: 60, b: 50, l: 60 },
        xaxis: { title: { text: "Time (min)" } },
        yaxis: { title: { text: "Utilisation factor" } },
        yaxis2: {
          title: { text: "Fire temperature (°C)" },
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
  }, [rows]);

  if (rows.length === 0) return null;
  return <div ref={ref} className="h-72 w-full" />;
}
