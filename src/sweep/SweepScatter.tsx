import { useEffect, useRef } from "react";
import type { Data } from "plotly.js";

import type { Run } from "../api/client";
import { buildScatterTraces } from "./buildScatterTraces";

interface Props {
  runs: Run[];
  varyingX: string | null;
  varyingColor?: string | null;
}

export function SweepScatter({ runs, varyingX, varyingColor }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!ref.current || !varyingX) return;
    const { traces, xLabel, yLabel } = buildScatterTraces(
      runs,
      varyingX,
      varyingColor ?? undefined,
    );
    let cancelled = false;
    (async () => {
      const Plotly = (await import("plotly.js-dist-min")).default;
      if (cancelled || !ref.current) return;
      Plotly.react(
        ref.current,
        traces as unknown as Data[],
        {
          margin: { t: 20, r: 20, b: 50, l: 60 },
          xaxis: { title: { text: xLabel } },
          yaxis: { title: { text: yLabel } },
          showlegend: traces.length > 1,
        },
        { responsive: true, displaylogo: false },
      );
    })();
    return () => {
      cancelled = true;
    };
  }, [runs, varyingX, varyingColor]);

  if (!varyingX) {
    return (
      <div className="flex h-64 items-center justify-center rounded border border-dashed border-slate-300 text-sm text-slate-500">
        Waiting for data — the scatter will appear once at least two runs
        differ on a varying parameter.
      </div>
    );
  }
  return <div ref={ref} className="h-64 w-full" />;
}
