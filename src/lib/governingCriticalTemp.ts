import type { Run } from "../api/client";

export interface GoverningCriticalTemp {
  /** Which perimeter beam governs (lowest critical temperature). */
  side: "A" | "B" | "C" | "D";
  temp: number;
}

const SIDES = ["a", "b", "c", "d"] as const;

function num(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/** The governing perimeter-beam critical temperature: the lowest across the
 *  sides present (ties go to the first side in A→D order). This is the value
 *  an engineer carries into the time-eq reliability study's critical-temperature
 *  override. Errored runs yield null — never a misleading zero. */
export function governingCriticalTemp(run: Run): GoverningCriticalTemp | null {
  if (run.error) return null;
  let best: GoverningCriticalTemp | null = null;
  for (const s of SIDES) {
    const temp = num((run as Record<string, unknown>)[`side_${s}_critical_temp`]);
    if (temp === null) continue;
    if (best === null || temp < best.temp) {
      best = { side: s.toUpperCase() as GoverningCriticalTemp["side"], temp };
    }
  }
  return best;
}
