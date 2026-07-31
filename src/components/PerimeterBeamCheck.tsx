import type { Run } from "../api/client";

interface Props {
  run: Run;
}

interface Side {
  label: string;
  sec: string | null;
  composite: boolean | null;
  edge: boolean | null;
  shCon: number | null;
  loadRatio: number | null;
  criticalTemp: number | null;
  momentReqd: number | null;
  lineLoad: number | null;
}

function num(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function bool(v: unknown): boolean | null {
  const n = num(v);
  return n === null ? null : n === 1;
}

function str(v: unknown): string | null {
  return typeof v === "string" && v.trim() !== "" ? v : null;
}

/** Side A/C share a span (span1) and required moment (Mb2_Reqd_1); Side B/D
 *  share span2 + Mb1_Reqd_1 — mirrors MACS+'s own PrintP.js FillPerim1Beam. */
function lineLoad(momentReqd: number | null, span: number | null): number | null {
  if (momentReqd === null || !span) return null;
  return (8 * momentReqd) / (span * span);
}

export function PerimeterBeamCheck({ run }: Props) {
  const span1 = num(run.span1);
  const span2 = num(run.span2);
  const mb1Reqd = num(run.mb1_reqd);
  const mb2Reqd = num(run.mb2_reqd);

  const sides: Side[] = [
    {
      label: "Side A",
      sec: str(run.side_a_sec),
      composite: bool(run.side_a_composite),
      edge: bool(run.side_a_edge),
      shCon: num(run.side_a_sh_con),
      loadRatio: num(run.side_a_load_ratio),
      criticalTemp: num(run.side_a_critical_temp),
      momentReqd: mb2Reqd,
      lineLoad: lineLoad(mb2Reqd, span1),
    },
    {
      label: "Side B",
      sec: str(run.side_b_sec),
      composite: bool(run.side_b_composite),
      edge: bool(run.side_b_edge),
      shCon: num(run.side_b_sh_con),
      loadRatio: num(run.side_b_load_ratio),
      criticalTemp: num(run.side_b_critical_temp),
      momentReqd: mb1Reqd,
      lineLoad: lineLoad(mb1Reqd, span2),
    },
    {
      label: "Side C",
      sec: str(run.side_c_sec),
      composite: bool(run.side_c_composite),
      edge: bool(run.side_c_edge),
      shCon: num(run.side_c_sh_con),
      loadRatio: num(run.side_c_load_ratio),
      criticalTemp: num(run.side_c_critical_temp),
      momentReqd: mb2Reqd,
      lineLoad: lineLoad(mb2Reqd, span1),
    },
    {
      label: "Side D",
      sec: str(run.side_d_sec),
      composite: bool(run.side_d_composite),
      edge: bool(run.side_d_edge),
      shCon: num(run.side_d_sh_con),
      loadRatio: num(run.side_d_load_ratio),
      criticalTemp: num(run.side_d_critical_temp),
      momentReqd: mb1Reqd,
      lineLoad: lineLoad(mb1Reqd, span2),
    },
  ].filter((s) => s.sec !== null);

  if (sides.length === 0) return null;

  return (
    <section className="mt-6 overflow-hidden rounded-md border border-slate-200 bg-white shadow-sm">
      <h2 className="border-b border-slate-100 px-6 py-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Perimeter beam check
      </h2>
      <div className="divide-y divide-slate-100">
        {sides.map((side) => (
          <div key={side.label} className="grid grid-cols-2 gap-x-6 gap-y-1 px-6 py-4 text-sm sm:grid-cols-4">
            <div className="col-span-2 font-medium text-slate-800 sm:col-span-4">
              {side.label}
            </div>
            <Field label="Beam type">
              <span>
                {side.composite === null ? "—" : side.composite ? "Composite" : "Non-composite"}
              </span>
              {" · "}
              <span>
                {side.edge === null ? "—" : side.edge ? "Edge beam" : "Internal beam"}
              </span>
            </Field>
            <Field label="Section size">{side.sec}</Field>
            <Field label="Required moment resistance in fire situation">
              {side.momentReqd === null ? "—" : `${side.momentReqd.toFixed(2)} kNm`}
            </Field>
            <Field label="Line load in fire situation">
              {side.lineLoad === null ? "—" : `${side.lineLoad.toFixed(2)} kN/m`}
            </Field>
            <Field label="Shear connection">
              {side.shCon === null ? "—" : `${side.shCon.toFixed(0)} %`}
            </Field>
            <Field label="Degree of utilization">
              {side.loadRatio === null ? "—" : side.loadRatio.toFixed(2)}
            </Field>
            <Field label="Critical temperature">
              {side.criticalTemp === null ? "—" : `${side.criticalTemp.toFixed(0)} °C`}
            </Field>
          </div>
        ))}
      </div>
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div className="tabular-nums text-slate-800">{children}</div>
    </div>
  );
}
