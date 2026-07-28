import { useEffect, useId, useRef, useState } from "react";

/** A small "i" icon that reveals explanatory content (a formula, a caveat) on
 * click. Click-to-toggle rather than hover so the content stays reachable by
 * keyboard and on touch. */
export function InfoTip({
  label,
  children,
}: {
  /** Names the field this explains — used for the icon's accessible name. */
  label: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLSpanElement>(null);
  const tipId = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    const onPointer = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onPointer);
    };
  }, [open]);

  return (
    <span ref={wrapRef} className="relative inline-block align-middle">
      <button
        // Must be explicit: a default-type button submits the config form.
        type="button"
        aria-label={`About ${label}`}
        aria-expanded={open}
        aria-controls={open ? tipId : undefined}
        onClick={() => setOpen((v) => !v)}
        className="ml-1 inline-flex h-4 w-4 items-center justify-center rounded-full border border-slate-400 text-[10px] font-semibold leading-none text-slate-500 hover:border-blue-500 hover:text-blue-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
      >
        i
      </button>
      {open && (
        <span
          id={tipId}
          role="tooltip"
          className="absolute left-0 top-6 z-20 block w-72 rounded border border-slate-300 bg-white p-3 text-xs font-normal leading-relaxed text-slate-700 shadow-lg"
        >
          {children}
        </span>
      )}
    </span>
  );
}
