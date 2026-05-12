/**
 * Translate sweep-mode form state into a /api/sweeps POST payload.
 *
 * Each varying parameter has up to three input sources — a CSV-loaded number
 * array, a parsed list (from the comma-separated text field), and a
 * min/max/step range. CSV wins, then list, then range. A varying entry whose
 * resolved value list is empty is omitted from the payload entirely (so a
 * half-filled "vary" chip doesn't accidentally pin a parameter to []).
 *
 * Pure function — no React imports, no fetch — so it can be tested in
 * isolation and reused by both the form submit handler and the e2e tests.
 */

export type ValueSource = {
  csv?: number[];
  list?: number[];
  range?: { min: number; max: number; step: number };
};

export interface SweepFormInput {
  analysisMethod: "iso" | "parametric";
  fixed: Record<string, unknown>;
  varying: Record<string, ValueSource>;
}

export interface SweepRequestBody {
  analysis_method: "iso" | "parametric";
  sweep: Record<string, number[]>;
  fixed: Record<string, unknown>;
}

export interface BuildSweepResult extends SweepRequestBody {
  /** Cartesian product size — for the 10k-soft-cap dialog before submit.
   *  Not sent to the backend; consumed by the form's submit handler. */
  totalCombinations: number;
}

export function buildSweepPayload(input: SweepFormInput): BuildSweepResult {
  const sweep: Record<string, number[]> = {};
  for (const [param, source] of Object.entries(input.varying)) {
    const values = pickValues(source);
    if (values.length > 0) {
      sweep[param] = values;
    }
  }
  const totalCombinations = Object.values(sweep).reduce(
    (acc, vals) => acc * vals.length,
    Object.keys(sweep).length === 0 ? 0 : 1,
  );
  return {
    analysis_method: input.analysisMethod,
    sweep,
    fixed: input.fixed,
    totalCombinations,
  };
}

/** Strip the test-only `totalCombinations` field before POST. */
export function toRequestBody(result: BuildSweepResult): SweepRequestBody {
  const { totalCombinations: _t, ...body } = result;
  return body;
}

function pickValues(source: ValueSource): number[] {
  if (source.csv && source.csv.length > 0) return source.csv;
  if (source.list && source.list.length > 0) return source.list;
  if (source.range) return generateRange(source.range);
  return [];
}

function generateRange({
  min,
  max,
  step,
}: {
  min: number;
  max: number;
  step: number;
}): number[] {
  if (step <= 0 || max < min) return [];
  const out: number[] = [];
  const tolerance = Math.abs(step) * 1e-9;
  for (let i = 0; ; i++) {
    const raw = min + i * step;
    if (raw > max + tolerance) break;
    out.push(roundFloatDrift(raw));
    if (out.length > 1_000_000) break;
  }
  return out;
}

function roundFloatDrift(v: number): number {
  return Number(v.toPrecision(12));
}
