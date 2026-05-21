import { useId, useState } from "react";

import { CsvValuesInput } from "./CsvValuesInput";
import { parseCsvText } from "./parseCsvText";
import {
  pairedValidation,
  rangeLength,
  type ValueSource,
} from "./buildSweepPayload";

export interface VaryableParam {
  name: string;
  label: string;
  isInteger: boolean;
}

interface Props {
  varying: Record<string, ValueSource>;
  onChange: (next: Record<string, ValueSource>) => void;
  varyableParams: VaryableParam[];
}

export function SweepConfigSection({ varying, onChange, varyableParams }: Props) {
  function toggle(param: string) {
    const next = { ...varying };
    if (param in next) delete next[param];
    else next[param] = {};
    onChange(next);
  }

  function updateSource(param: string, source: ValueSource) {
    onChange({ ...varying, [param]: source });
  }

  const enabled = Object.keys(varying);
  const { errors } = pairedValidation(varying);

  return (
    <section className="rounded-md border border-blue-200 bg-blue-50/40 p-4">
      <h3 className="text-sm font-semibold text-slate-800">Parameters to vary</h3>
      <div className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-3">
        {varyableParams.map((p) => (
          <label key={p.name} className="flex items-center gap-2 text-sm text-slate-700">
            <input
              type="checkbox"
              checked={p.name in varying}
              onChange={() => toggle(p.name)}
            />
            {p.label}
          </label>
        ))}
      </div>
      {enabled.length > 0 && (
        <div className="mt-4 space-y-3 border-t border-blue-200 pt-3">
          {enabled.map((name) => {
            const param = varyableParams.find((p) => p.name === name);
            if (!param) return null;
            return (
              <ParamValueEntry
                key={name}
                param={param}
                source={varying[name]}
                error={errors[name]}
                onChange={(src) => updateSource(name, src)}
              />
            );
          })}
        </div>
      )}
    </section>
  );
}

interface EntryProps {
  param: VaryableParam;
  source: ValueSource;
  error?: string;
  onChange: (next: ValueSource) => void;
}

function ParamValueEntry({ param, source, error, onChange }: EntryProps) {
  const minId = useId();
  const maxId = useId();
  const stepId = useId();
  const [listText, setListText] = useState<string>(
    (source.list ?? []).join(", "),
  );
  const [rangeText, setRangeText] = useState<{ min: string; max: string; step: string }>({
    min: source.range ? String(source.range.min) : "",
    max: source.range ? String(source.range.max) : "",
    step: source.range ? String(source.range.step) : "",
  });

  function commitList(text: string) {
    setListText(text);
    let list: number[] | undefined;
    try {
      const parsed = parseCsvText(text);
      list = parsed.length > 0 ? parsed : undefined;
    } catch {
      list = undefined;
    }
    const next: ValueSource = { ...source, list };
    onChange(next);
  }

  function commitRange(field: "min" | "max" | "step", value: string) {
    const next = { ...rangeText, [field]: value };
    setRangeText(next);
    const min = Number(next.min);
    const max = Number(next.max);
    const step = Number(next.step);
    if ([min, max, step].every((n) => Number.isFinite(n)) && next.min !== "" && next.max !== "" && next.step !== "") {
      onChange({ ...source, range: { min, max, step } });
    } else {
      onChange({ ...source, range: undefined });
    }
  }

  function commitCsv(values: number[] | null) {
    onChange({ ...source, csv: values ?? undefined });
  }

  const listCount = (() => {
    try {
      return parseCsvText(listText).length;
    } catch {
      return 0;
    }
  })();
  const rangeCount = source.range ? rangeLength(source.range) : 0;
  const csvCount = source.csv?.length ?? 0;

  const cardClass = error
    ? "rounded border border-rose-400 bg-white p-3"
    : "rounded border border-blue-200 bg-white p-3";

  return (
    <div className={cardClass}>
      <h4 className="mb-2 text-sm font-semibold text-slate-700">{param.label}</h4>
      <label className="block text-xs">
        <span className="text-slate-600">Comma-separated list</span>
        <input
          type="text"
          placeholder="comma-separated, e.g. 400, 510, 720"
          value={listText}
          onChange={(e) => commitList(e.target.value)}
          className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
        />
        {listCount > 0 && (
          <p className="mt-0.5 text-[0.7rem] text-emerald-700">{listCount} values</p>
        )}
      </label>
      <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
        <label htmlFor={minId} className="block">
          <span className="text-slate-600">Min</span>
          <input
            id={minId}
            type="number"
            step="any"
            value={rangeText.min}
            onChange={(e) => commitRange("min", e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
          />
        </label>
        <label htmlFor={maxId} className="block">
          <span className="text-slate-600">Max</span>
          <input
            id={maxId}
            type="number"
            step="any"
            value={rangeText.max}
            onChange={(e) => commitRange("max", e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
          />
        </label>
        <label htmlFor={stepId} className="block">
          <span className="text-slate-600">Step</span>
          <input
            id={stepId}
            type="number"
            step="any"
            value={rangeText.step}
            onChange={(e) => commitRange("step", e.target.value)}
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
          />
        </label>
      </div>
      {rangeCount > 0 && (
        <p className="mt-0.5 text-[0.7rem] text-emerald-700">{rangeCount} values</p>
      )}
      {!param.isInteger && (
        <div className="mt-2">
          <CsvValuesInput onChange={commitCsv} />
          {csvCount > 0 && (
            <p className="mt-0.5 text-[0.7rem] text-emerald-700">{csvCount} values</p>
          )}
        </div>
      )}
      {error && (
        <p className="mt-2 text-xs font-medium text-rose-700">{error}</p>
      )}
    </div>
  );
}
