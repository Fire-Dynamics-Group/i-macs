/**
 * In-browser Plotly chart that mirrors the MACS+ desktop "Monte Carlo
 * Summary" distribution panels (capacity / lofl / mesh temperature).
 *
 * Fetches /api/batches/:id/distribution once per chart (mounted only on
 * completed batches, so no refetch). Renders spaghetti via scattergl
 * (canvas) for perf at 10k samples.
 *
 * Empty-state contract: when the server returns no spaghetti AND no
 * average (every run errored), render a non-collapsing placeholder so the
 * 4-chart grid stays visually anchored.
 */
import { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Data, Layout } from "plotly.js";

import { fetchDistribution } from "../api/client";
import {
  buildDistributionTraces,
  type DistributionPayload,
} from "./buildDistributionTraces";

interface Props {
  batchId: string;
  column: "total_plate_capacity" | "lofl_temp" | "mesh_temp";
  title: string;
  yLabel: string;
  /** Stride-sample down to this many spaghetti runs server-side. */
  spaghettiN?: number;
}

export function DistributionChart({
  batchId,
  column,
  title,
  yLabel,
  spaghettiN = 500,
}: Props) {
  const ref = useRef<HTMLDivElement | null>(null);

  const query = useQuery<DistributionPayload>({
    queryKey: ["batch-distribution", batchId, column, spaghettiN],
    queryFn: () => fetchDistribution(batchId, column, spaghettiN),
    enabled: batchId.length > 0,
    // AnalyticalView only mounts for completed batches → the data is
    // immutable once fetched. No refetch on focus / mount.
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    if (!ref.current || !query.data) return;
    const { traces } = buildDistributionTraces(query.data);
    if (traces.length === 0) return;
    let cancelled = false;
    (async () => {
      const Plotly = (await import("plotly.js-dist-min")).default;
      if (cancelled || !ref.current) return;
      const layout: Partial<Layout> = {
        margin: { t: 10, r: 20, b: 50, l: 60 },
        xaxis: { title: { text: "Time (min)" }, rangemode: "tozero" },
        yaxis: { title: { text: yLabel }, rangemode: "tozero" },
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
  }, [query.data, yLabel]);

  const hasData =
    !!query.data &&
    ((query.data.spaghetti?.length ?? 0) > 0 ||
      (query.data.average?.length ?? 0) > 0);

  return (
    <section
      data-chart={column}
      className="rounded-md border border-slate-200 bg-white p-4 shadow-sm"
    >
      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h2>
      {query.isLoading ? (
        <div className="flex h-64 items-center justify-center text-sm text-slate-400">
          Loading…
        </div>
      ) : query.isError ? (
        <div className="flex h-64 items-center justify-center text-sm text-rose-600">
          Failed to load chart data.
        </div>
      ) : !hasData ? (
        <div className="flex h-64 items-center justify-center rounded border border-dashed border-slate-300 text-sm text-slate-500">
          No successful runs in this batch
        </div>
      ) : (
        <div ref={ref} className="h-72 w-full" />
      )}
    </section>
  );
}
