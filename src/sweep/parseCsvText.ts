/**
 * Parse a CSV-style text into an array of finite numbers.
 *
 * Splits on commas AND newlines, strips whitespace, drops empty tokens. Every
 * remaining token must parse to a finite number — the first non-numeric token
 * aborts with the bad token included in the error message.
 *
 * Used by the sweep config form's CSV upload and "list of values" inputs.
 */
export function parseCsvText(input: string): number[] {
  if (!input) return [];
  const tokens = input
    .split(/[,\n\r]+/)
    .map((t) => t.trim())
    .filter((t) => t.length > 0);

  const out: number[] = [];
  for (const token of tokens) {
    const n = Number(token);
    if (!Number.isFinite(n)) {
      throw new Error(`Could not parse "${token}" as a number`);
    }
    out.push(n);
  }
  return out;
}
