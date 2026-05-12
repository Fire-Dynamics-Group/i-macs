import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import type { BatchSummary, Run } from "../api/client";
import {
  fetchStats,
  listBatches,
  listUngroupedRuns,
} from "../api/client";

type RunStatus = "pass" | "fail" | "error";

function runStatus(run: Run): RunStatus {
  if (run.error) return "error";
  return run.overall_pass ? "pass" : "fail";
}

function inflightBatch(b: BatchSummary): boolean {
  return b.run_count < (b.total_expected ?? 0);
}

export default function RunsDashboardPage() {
  const [params, setParams] = useSearchParams();
  const statusFilter = params.get("status") ?? "all";
  const modeFilter = params.get("mode") ?? "all";
  const dateFilter = params.get("date") ?? "all";

  const statsQuery = useQuery({
    queryKey: ["stats"],
    queryFn: fetchStats,
  });

  const batchesQuery = useQuery({
    queryKey: ["batches"],
    queryFn: () => listBatches({ limit: 20, offset: 0 }),
    // Self-healing poll: only while any batch is still in flight. Once every
    // batch's run_count matches total_expected, the interval drops to false
    // and stops the timer.
    refetchInterval: (q) => {
      const data = q.state.data;
      if (!data) return false;
      return data.batches.some(inflightBatch) ? 2000 : false;
    },
  });

  const ungroupedQuery = useQuery({
    queryKey: ["ungrouped"],
    queryFn: () => listUngroupedRuns({ limit: 50, offset: 0 }),
  });

  const stats = statsQuery.data ?? {
    total: 0, successful: 0, errors: 0, pass_count: 0, fail_count: 0,
  };
  const successRate =
    stats.total > 0 ? Math.round((stats.pass_count / stats.total) * 100) : 0;

  const filteredRuns = useMemo(() => {
    const all = ungroupedQuery.data?.runs ?? [];
    return all.filter((r) => {
      if (statusFilter !== "all" && runStatus(r) !== statusFilter) return false;
      if (dateFilter !== "all") {
        const ts = typeof r.run_timestamp === "string" ? Date.parse(r.run_timestamp) : NaN;
        if (Number.isFinite(ts)) {
          const cutoff = dateCutoff(dateFilter);
          if (cutoff !== null && ts < cutoff) return false;
        }
      }
      return true;
    });
  }, [ungroupedQuery.data, statusFilter, dateFilter]);

  const filteredBatches = useMemo(() => {
    const all = batchesQuery.data?.batches ?? [];
    return all.filter((b) => modeFilter === "all" || b.mode === modeFilter);
  }, [batchesQuery.data, modeFilter]);

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value === "all") next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  };

  const noData =
    !statsQuery.isLoading &&
    stats.total === 0 &&
    (batchesQuery.data?.batches.length ?? 0) === 0 &&
    (ungroupedQuery.data?.runs.length ?? 0) === 0;

  return (
    <div className="mx-auto max-w-6xl p-8">
      <header className="mb-6 flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold tracking-tight">History</h1>
        <Link
          to="/"
          className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500"
        >
          New run
        </Link>
      </header>

      {statsQuery.isError ? (
        <section className="mb-4 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
          Couldn't load stats. Other panels still work — try refresh.
        </section>
      ) : (
        <section className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-5">
          <StatCard label="Total" value={stats.total} />
          <StatCard label="Pass" value={stats.pass_count} tone="positive" />
          <StatCard label="Fail" value={stats.fail_count} tone="warning" />
          <StatCard label="Error" value={stats.errors} tone="negative" />
          <StatCard label="Success rate" value={`${successRate}%`} />
        </section>
      )}

      {noData ? (
        <EmptyState />
      ) : (
        <>
          <Filters
            status={statusFilter}
            mode={modeFilter}
            date={dateFilter}
            onChange={setParam}
          />

          <BatchesSection
            isError={batchesQuery.isError}
            batches={filteredBatches}
          />

          <UngroupedSection
            isError={ungroupedQuery.isError}
            runs={filteredRuns}
          />
        </>
      )}
    </div>
  );
}

function dateCutoff(filter: string): number | null {
  const now = Date.now();
  const day = 24 * 60 * 60 * 1000;
  if (filter === "24h") return now - day;
  if (filter === "7d") return now - 7 * day;
  if (filter === "30d") return now - 30 * day;
  return null;
}

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: "positive" | "warning" | "negative";
}) {
  const toneClass =
    tone === "positive"
      ? "text-emerald-700"
      : tone === "warning"
        ? "text-amber-700"
        : tone === "negative"
          ? "text-rose-700"
          : "text-slate-800";
  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2 shadow-sm">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className={`mt-0.5 text-2xl font-semibold tabular-nums ${toneClass}`}>
        {value}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-md border border-dashed border-slate-300 bg-white py-16 text-center">
      <p className="text-base font-medium text-slate-700">No runs yet</p>
      <p className="mt-1 text-sm text-slate-500">
        Once you submit a run or a sweep, it shows up here.
      </p>
      <Link
        to="/"
        className="mt-4 inline-block rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-500"
      >
        Start your first run
      </Link>
    </div>
  );
}

const STATUS_FILTERS: Array<{ key: string; label: string }> = [
  { key: "all", label: "All" },
  { key: "pass", label: "Pass" },
  { key: "fail", label: "Fail" },
  { key: "error", label: "Error" },
];

const MODE_FILTERS: Array<{ key: string; label: string }> = [
  { key: "all", label: "All modes" },
  { key: "sweep", label: "Sweep" },
  { key: "lhs", label: "LHS" },
];

const DATE_FILTERS: Array<{ key: string; label: string }> = [
  { key: "24h", label: "24h" },
  { key: "7d", label: "7d" },
  { key: "30d", label: "30d" },
  { key: "all", label: "All time" },
];

function Filters({
  status,
  mode,
  date,
  onChange,
}: {
  status: string;
  mode: string;
  date: string;
  onChange: (key: string, value: string) => void;
}) {
  return (
    <section className="mb-6 flex flex-wrap items-center gap-2">
      <FilterGroup label="Status" current={status} options={STATUS_FILTERS} onSelect={(v) => onChange("status", v)} />
      <FilterGroup label="Mode" current={mode} options={MODE_FILTERS} onSelect={(v) => onChange("mode", v)} />
      <FilterGroup label="Date" current={date} options={DATE_FILTERS} onSelect={(v) => onChange("date", v)} />
    </section>
  );
}

function FilterGroup({
  label,
  current,
  options,
  onSelect,
}: {
  label: string;
  current: string;
  options: Array<{ key: string; label: string }>;
  onSelect: (v: string) => void;
}) {
  return (
    <div className="flex items-center gap-1">
      <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
        {label}
      </span>
      {options.map((opt) => (
        <button
          key={opt.key}
          type="button"
          onClick={() => onSelect(opt.key)}
          className={
            "rounded-md px-2 py-1 text-xs font-medium " +
            (current === opt.key
              ? "bg-blue-600 text-white"
              : "bg-slate-100 text-slate-700 hover:bg-slate-200")
          }
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

function BatchesSection({
  batches,
  isError,
}: {
  batches: BatchSummary[];
  isError: boolean;
}) {
  return (
    <section className="mb-8 overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm">
      <h2 className="border-b border-slate-100 px-4 py-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Batches
      </h2>
      {isError ? (
        <p className="px-4 py-3 text-sm text-rose-700">
          Couldn't load batches.
        </p>
      ) : batches.length === 0 ? (
        <p className="px-4 py-3 text-sm text-slate-500">No batches.</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-4 py-2 text-left font-medium text-slate-700">Batch</th>
              <th className="px-4 py-2 text-left font-medium text-slate-700">When</th>
              <th className="px-4 py-2 text-left font-medium text-slate-700">Mode</th>
              <th className="px-4 py-2 text-left font-medium text-slate-700">Varying</th>
              <th className="px-4 py-2 text-left font-medium text-slate-700">Progress</th>
              <th className="px-4 py-2 text-left font-medium text-slate-700">Pass / Fail / Error</th>
            </tr>
          </thead>
          <tbody>
            {batches.map((b) => (
              <tr key={b.batch_id} className="border-t border-slate-100">
                <td className="px-4 py-1.5">
                  <Link
                    to={`/batches/${b.batch_id}`}
                    className="font-mono text-xs text-blue-700 hover:underline"
                  >
                    {b.batch_id.slice(0, 8)}
                  </Link>
                </td>
                <td className="px-4 py-1.5 text-slate-600">
                  {formatTimestamp(b.created_at)}
                </td>
                <td className="px-4 py-1.5 text-slate-600">{b.mode ?? "—"}</td>
                <td className="px-4 py-1.5">
                  {Object.keys(b.varying_params ?? {}).length === 0 ? (
                    <span className="text-slate-400">—</span>
                  ) : (
                    <span className="inline-flex flex-wrap gap-1">
                      {Object.keys(b.varying_params).map((k) => (
                        <span
                          key={k}
                          className="rounded bg-blue-50 px-1.5 py-0.5 font-mono text-xs text-blue-800"
                        >
                          {k}
                        </span>
                      ))}
                    </span>
                  )}
                </td>
                <td className="px-4 py-1.5 tabular-nums text-slate-700">
                  {b.run_count} / {b.total_expected}
                </td>
                <td className="px-4 py-1.5 tabular-nums text-slate-700">
                  <span className="text-emerald-700">{b.pass_count}</span>
                  {" / "}
                  <span className="text-amber-700">{b.fail_count}</span>
                  {" / "}
                  <span className="text-rose-700">{b.error_count}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

type SortKey = "timestamp" | "uf_max" | "status";
type SortDir = "asc" | "desc";

function UngroupedSection({ runs, isError }: { runs: Run[]; isError: boolean }) {
  const [sortKey, setSortKey] = useState<SortKey>("timestamp");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const sorted = useMemo(() => {
    const arr = [...runs];
    arr.sort((a, b) => {
      const dir = sortDir === "asc" ? 1 : -1;
      if (sortKey === "uf_max") {
        return ((a.uf_max ?? -Infinity) - (b.uf_max ?? -Infinity)) * dir;
      }
      if (sortKey === "status") {
        return runStatus(a).localeCompare(runStatus(b)) * dir;
      }
      const at = typeof a.run_timestamp === "string" ? Date.parse(a.run_timestamp) : 0;
      const bt = typeof b.run_timestamp === "string" ? Date.parse(b.run_timestamp) : 0;
      return (at - bt) * dir;
    });
    return arr;
  }, [runs, sortKey, sortDir]);

  const handleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "uf_max" ? "asc" : "desc");
    }
  };

  return (
    <section className="overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm">
      <h2 className="border-b border-slate-100 px-4 py-2 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Single runs
      </h2>
      {isError ? (
        <p className="px-4 py-3 text-sm text-rose-700">Couldn't load runs.</p>
      ) : sorted.length === 0 ? (
        <p className="px-4 py-3 text-sm text-slate-500">No single runs.</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="bg-slate-50">
            <tr>
              <th className="px-4 py-2 text-left font-medium text-slate-700">Run</th>
              <th className="px-4 py-2 text-left font-medium text-slate-700">
                <SortButton label="Timestamp" active={sortKey === "timestamp"} dir={sortDir} onClick={() => handleSort("timestamp")} />
              </th>
              <th className="px-4 py-2 text-left font-medium text-slate-700">
                <SortButton label="UF max" active={sortKey === "uf_max"} dir={sortDir} onClick={() => handleSort("uf_max")} />
              </th>
              <th className="px-4 py-2 text-left font-medium text-slate-700">
                <SortButton label="Status" active={sortKey === "status"} dir={sortDir} onClick={() => handleSort("status")} />
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((run) => (
              <tr
                key={run.id}
                className={
                  "border-t border-slate-100 " + (run.error ? "bg-rose-50" : "")
                }
              >
                <td className="px-4 py-1">
                  <Link
                    to={`/runs/${run.id}`}
                    className="text-blue-700 hover:underline"
                  >
                    #{run.id}
                  </Link>
                </td>
                <td className="px-4 py-1 text-slate-600">
                  {formatTimestamp(
                    typeof run.run_timestamp === "string" ? run.run_timestamp : null,
                  )}
                </td>
                <td className="px-4 py-1 tabular-nums">
                  {run.uf_max != null ? run.uf_max.toFixed(3) : "—"}
                </td>
                <td className="px-4 py-1">
                  {run.error ? (
                    <span className="text-rose-700">Error</span>
                  ) : run.overall_pass ? (
                    <span className="text-emerald-700">Pass</span>
                  ) : (
                    <span className="text-amber-700">Fail</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function SortButton({
  label,
  active,
  dir,
  onClick,
}: {
  label: string;
  active: boolean;
  dir: SortDir;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "inline-flex items-center gap-1 text-left font-medium " +
        (active ? "text-blue-700" : "text-slate-700 hover:text-slate-900")
      }
    >
      {label}
      {active && <span aria-hidden="true">{dir === "asc" ? "↑" : "↓"}</span>}
    </button>
  );
}

function formatTimestamp(ts: string | null): string {
  if (!ts) return "—";
  const t = Date.parse(ts);
  if (!Number.isFinite(t)) return ts;
  return new Date(t).toLocaleString();
}
