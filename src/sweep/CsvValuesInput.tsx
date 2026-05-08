import { useId, useState } from "react";

import { parseCsvText } from "./parseCsvText";

interface Props {
  onChange: (values: number[] | null) => void;
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
      const values = parseCsvText(text);
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
