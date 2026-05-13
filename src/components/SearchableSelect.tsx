import { useEffect, useMemo, useRef, useState } from "react";
import * as Popover from "@radix-ui/react-popover";
import { Command } from "cmdk";
import Fuse from "fuse.js";

export interface SearchableSelectOption {
  id: string;
  label: string;
  secondary?: string;
  searchTerms?: string[];
}

export interface SearchableSelectProps {
  value: string;
  onChange: (id: string) => void;
  options: SearchableSelectOption[];
  placeholder?: string;
  /**
   * Optional id passed through to the trigger button. The label that wraps
   * `SearchableSelect` in the form uses an htmlFor/id pair to associate the
   * visible label with the picker for accessibility + Playwright's getByLabel.
   */
  id?: string;
  /** Optional accessible name when the trigger isn't wrapped by a <label>. */
  ariaLabel?: string;
}

export function SearchableSelect({
  value,
  onChange,
  options,
  placeholder,
  id,
  ariaLabel,
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);

  const selected = options.find((o) => o.id === value);

  const fuse = useMemo(
    () =>
      new Fuse(options, {
        keys: ["label", "searchTerms"],
        threshold: 0.4,
        ignoreLocation: true,
      }),
    [options],
  );

  const filtered = useMemo(() => {
    const q = search.trim();
    if (!q) return options;
    return fuse.search(q).map((r) => r.item);
  }, [fuse, options, search]);

  // Clear the search when the popover closes so the next open starts fresh.
  useEffect(() => {
    if (!open) setSearch("");
  }, [open]);

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={ariaLabel ?? selected?.label ?? placeholder ?? "Choose…"}
        className="mt-1 flex w-full items-center justify-between rounded border border-slate-300 bg-white px-3 py-1.5 text-left text-sm focus:border-blue-500 focus:outline-none"
      >
        <span className={selected ? "text-slate-900" : "text-slate-400"}>
          {selected?.label ?? placeholder ?? "Choose…"}
        </span>
        <span aria-hidden className="ml-2 text-slate-400">
          ▾
        </span>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={4}
          className="z-50 w-[var(--radix-popover-trigger-width)] overflow-hidden rounded-md border border-slate-200 bg-white shadow-lg"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            inputRef.current?.focus();
          }}
        >
          <Command shouldFilter={false} loop>
            <div className="border-b border-slate-100 px-2 py-1.5">
              <input
                ref={inputRef}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search…"
                className="w-full bg-transparent text-sm outline-none placeholder:text-slate-400"
              />
            </div>
            <Command.List className="max-h-64 overflow-y-auto py-1">
              {filtered.length === 0 ? (
                <div className="px-3 py-2 text-sm text-slate-400">
                  No matches
                </div>
              ) : (
                filtered.map((opt) => (
                  <Command.Item
                    key={opt.id}
                    value={opt.id}
                    onSelect={() => {
                      onChange(opt.id);
                      setOpen(false);
                    }}
                    className="flex cursor-pointer items-center justify-between gap-3 px-3 py-1.5 text-sm aria-selected:bg-blue-50 aria-selected:text-blue-900"
                  >
                    <span>{opt.label}</span>
                    {opt.secondary && (
                      <span className="text-xs text-slate-400">
                        {opt.secondary}
                      </span>
                    )}
                  </Command.Item>
                ))
              )}
            </Command.List>
          </Command>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
