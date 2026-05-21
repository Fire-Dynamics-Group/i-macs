import { useId, useState } from "react";

interface Props {
  onChange: (values: number[] | null) => void;
}

/**
 * Parse a single-column numeric CSV. One value per line, no header, no commas
 * inside any row. A row with a comma (multi-column) or a non-numeric token is
 * rejected with a `Row N: ...` error so the user can locate the offender.
 * Empty lines are skipped.
 */
function parseSingleColumnCsv(text: string): number[] {
  const lines = text.split(/\r?\n/);
  const out: number[] = [];
  let rowNumber = 0;
  for (const raw of lines) {
    const trimmed = raw.trim();
    if (trimmed === "") continue;
    rowNumber++;
    if (trimmed.includes(",")) {
      throw new Error(`Row ${rowNumber}: expected one numeric value, got "${trimmed}"`);
    }
    const n = Number(trimmed);
    if (!Number.isFinite(n)) {
      throw new Error(`Row ${rowNumber}: expected one numeric value, got "${trimmed}"`);
    }
    out.push(n);
  }
  return out;
}

export function CsvValuesInput({ onChange }: Props) {
  const inputId = useId();
  const [summary, setSummary] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  async function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) {
      setSummary(null);
      setErrorMsg(null);
      onChange(null);
      return;
    }
    const text = await file.text();
    try {
      const values = parseSingleColumnCsv(text);
      if (values.length === 0) {
        setSummary(null);
        setErrorMsg("CSV is empty");
        onChange(null);
        return;
      }
      const min = Math.min(...values);
      const max = Math.max(...values);
      setSummary(`${values.length} values · ${min}–${max}`);
      setErrorMsg(null);
      onChange(values);
    } catch (err) {
      setSummary(null);
      setErrorMsg(err instanceof Error ? err.message : String(err));
      onChange(null);
    }
  }

  return (
    <div className="text-sm">
      <label htmlFor={inputId} className="block">
        <span className="text-slate-700">CSV file</span>
        <input
          id={inputId}
          type="file"
          accept=".csv,text/csv,text/plain"
          onChange={handleChange}
          className="mt-1 block w-full text-xs"
        />
      </label>
      {summary && (
        <p className="mt-1 text-xs text-emerald-700">{summary}</p>
      )}
      {errorMsg && (
        <p className="mt-1 text-xs text-rose-600">{errorMsg}</p>
      )}
    </div>
  );
}
