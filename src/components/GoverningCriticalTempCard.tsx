import { useEffect, useRef, useState } from "react";

import type { Run } from "../api/client";
import { governingCriticalTemp } from "../lib/governingCriticalTemp";

interface Props {
  run: Run;
}

/** The one number this run hands to the time-eq reliability study: the
 *  governing (lowest) perimeter-beam critical temperature, copyable as a bare
 *  number so it pastes straight into the critical-temperature override. */
export function GoverningCriticalTempCard({ run }: Props) {
  const gov = governingCriticalTemp(run);
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    };
  }, []);

  if (!gov) return null;
  const value = gov.temp.toFixed(0);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard unavailable — leave the value on screen to copy by hand.
    }
  }

  return (
    <section
      data-testid="governing-critical-temp"
      className="mt-6 rounded-md border border-blue-200 bg-blue-50 p-4 shadow-sm"
    >
      <h2 className="text-sm font-semibold uppercase tracking-wide text-blue-800">
        Governing critical temperature
      </h2>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-2xl font-semibold tabular-nums text-slate-900">
          {value} °C
        </span>
        <span className="text-sm text-slate-700">Side {gov.side} governs</span>
        <button
          type="button"
          onClick={copy}
          className="rounded border border-blue-300 bg-white px-2.5 py-1 text-xs font-medium text-blue-800 hover:bg-blue-100"
        >
          Copy value
        </button>
        {copied && (
          <span aria-live="polite" className="text-xs font-medium text-emerald-700">
            Copied
          </span>
        )}
      </div>
      <p className="mt-1.5 text-xs text-slate-600">
        Lowest perimeter-beam critical temperature — enter it as the
        critical-temperature override in the Monte Carlo reliability study
        (unprotected mode) to get the probability a realistic fire takes this
        member past failure.
      </p>
    </section>
  );
}
