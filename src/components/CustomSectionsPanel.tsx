import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createCustomSection,
  deleteCustomSection,
  listCustomSections,
  type CustomSectionInput,
} from "../api/client";

/** The four dimensions MACS+ needs to describe an I-section, in the order
 *  they appear on a Blue Book dimensions table. */
const DIMENSIONS = [
  { key: "h", label: "Depth h (mm)" },
  { key: "b", label: "Width b (mm)" },
  { key: "tw", label: "Web thickness tw (mm)" },
  { key: "tf", label: "Flange thickness tf (mm)" },
] as const;

type DimensionKey = (typeof DIMENSIONS)[number]["key"];

const EMPTY_FORM: Record<"name" | DimensionKey, string> = {
  name: "",
  h: "",
  b: "",
  tw: "",
  tf: "",
};

/** Manage the user-defined beam sections held in this device's SQLite DB.
 *
 *  The sidecar already merges these ahead of the Blue Book and Data.xml
 *  catalogues, so anything added here surfaces at the top of every section
 *  dropdown as "<name> (Custom)" once the ref-data query is refreshed. */
export function CustomSectionsPanel() {
  const queryClient = useQueryClient();
  const [form, setForm] = useState(EMPTY_FORM);
  const [validationError, setValidationError] = useState<string | null>(null);

  const sectionsQuery = useQuery({
    queryKey: ["custom-sections"],
    queryFn: listCustomSections,
  });

  /** Both mutations refresh ref-data — that's the query backing the section
   *  dropdowns on the config form. */
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ["custom-sections"] });
    queryClient.invalidateQueries({ queryKey: ["ref-data"] });
  };

  const addMutation = useMutation({
    mutationFn: (section: CustomSectionInput) => createCustomSection(section),
    onSuccess: () => {
      setForm(EMPTY_FORM);
      refresh();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteCustomSection(id),
    onSuccess: refresh,
  });

  const setField = (key: keyof typeof EMPTY_FORM, value: string) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();

    const name = form.name.trim();
    if (!name) {
      setValidationError("Name is required");
      return;
    }
    const parsed = {} as Record<DimensionKey, number>;
    for (const { key, label } of DIMENSIONS) {
      const value = Number(form[key]);
      if (!Number.isFinite(value) || value <= 0) {
        setValidationError(`${label} must be greater than zero`);
        return;
      }
      parsed[key] = value;
    }

    setValidationError(null);
    addMutation.mutate({ name, ...parsed });
  };

  const sections = sectionsQuery.data ?? [];
  const submitError = addMutation.error
    ? String((addMutation.error as Error).message)
    : null;

  return (
    <section className="rounded border border-slate-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-slate-800">Custom sections</h3>
      <p className="mt-1 text-xs text-slate-500">
        Stored on this device. They appear at the top of every section dropdown.
      </p>

      {sectionsQuery.isLoading ? (
        <p className="mt-3 text-sm text-slate-500">Loading…</p>
      ) : sections.length === 0 ? (
        <p className="mt-3 text-sm text-slate-500">
          No custom sections defined yet.
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-slate-100">
          {sections.map((sec) => (
            <li
              key={sec.id}
              className="flex items-center justify-between gap-3 py-2"
            >
              <div className="min-w-0">
                <span className="block truncate text-sm text-slate-800">
                  {sec.name}
                </span>
                <span className="block text-xs text-slate-500">
                  {`h ${sec.h} × b ${sec.b} × tw ${sec.tw} × tf ${sec.tf} mm`}
                </span>
              </div>
              <button
                type="button"
                aria-label={`Delete ${sec.name}`}
                onClick={() => deleteMutation.mutate(sec.id)}
                disabled={deleteMutation.isPending}
                className="shrink-0 rounded border border-slate-300 px-2 py-1 text-xs text-rose-600 hover:bg-rose-50 disabled:opacity-50"
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={handleSubmit} className="mt-4 border-t border-slate-100 pt-3">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-5">
          <label className="block sm:col-span-5">
            <span className="text-sm font-medium text-slate-700">Name</span>
            <input
              type="text"
              value={form.name}
              onChange={(e) => setField("name", e.target.value)}
              placeholder="e.g. UB 533x165x74"
              className="mt-1 w-full rounded border border-slate-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
            />
          </label>
          {DIMENSIONS.map(({ key, label }) => (
            <label key={key} className="block">
              <span className="text-sm font-medium text-slate-700">{label}</span>
              <input
                type="number"
                step="any"
                value={form[key]}
                onChange={(e) => setField(key, e.target.value)}
                className="mt-1 w-full rounded border border-slate-300 px-3 py-1.5 text-sm focus:border-blue-500 focus:outline-none"
              />
            </label>
          ))}
          <div className="flex items-end">
            <button
              type="submit"
              disabled={addMutation.isPending}
              className="w-full rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              Add section
            </button>
          </div>
        </div>

        {(validationError || submitError) && (
          <p role="alert" className="mt-2 text-xs text-rose-600">
            {validationError ?? submitError}
          </p>
        )}
      </form>
    </section>
  );
}
