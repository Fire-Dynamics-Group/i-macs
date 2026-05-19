import type { Check } from "../api/client";

interface Props {
  checks: Check[];
}

export function CheckBreakdown({ checks }: Props) {
  if (!checks || checks.length === 0) return null;
  return (
    <section className="mt-6 overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm">
      <h2 className="border-b border-slate-100 px-6 py-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Pass / fail breakdown
      </h2>
      <table className="w-full text-sm">
        <thead className="bg-slate-50">
          <tr>
            <th className="px-4 py-2 text-left font-medium text-slate-700">Check</th>
            <th className="px-4 py-2 text-left font-medium text-slate-700">Value</th>
            <th className="px-4 py-2 text-left font-medium text-slate-700">Limit</th>
            <th className="px-4 py-2 text-left font-medium text-slate-700">Status</th>
          </tr>
        </thead>
        <tbody>
          {checks.map((c) => (
            <tr
              key={c.name}
              className={
                "border-t border-slate-100 " +
                (c.pass ? "" : "bg-rose-50")
              }
            >
              <td className="px-4 py-1.5">{c.name}</td>
              <td className="px-4 py-1.5 tabular-nums">{formatValue(c.value)}</td>
              <td className="px-4 py-1.5 tabular-nums">{formatLimit(c)}</td>
              <td className="px-4 py-1.5">
                <span
                  className={
                    "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium " +
                    (c.pass
                      ? "bg-emerald-100 text-emerald-800"
                      : "bg-rose-100 text-rose-800")
                  }
                >
                  {c.pass ? "Pass" : "Fail"}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function formatValue(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(3);
}

function formatLimit(check: Check): string {
  return `≤ ${check.limit.toFixed(2)}`;
}
