/** @jsxImportSource react */
import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SearchableSelect } from "./SearchableSelect";

type Opt = {
  id: string;
  label: string;
  secondary?: string;
  searchTerms?: string[];
};

const SECTIONS: Opt[] = [
  {
    id: "UB_457x191x89",
    label: "UB 457 x 191 x 89",
    secondary: "463 × 192",
    searchTerms: ["UB", "457", "191"],
  },
  {
    id: "UB_610x305x238",
    label: "UB 610 x 305 x 238",
    secondary: "635 × 311",
    searchTerms: ["UB", "610", "305"],
  },
  {
    id: "IPE_500",
    label: "IPE 500",
    secondary: "500 × 200",
    searchTerms: ["IPE", "500", "200"],
  },
];

describe("SearchableSelect", () => {
  it("displays the selected option's label on the closed trigger", () => {
    render(
      <SearchableSelect
        value="UB_457x191x89"
        onChange={() => {}}
        options={SECTIONS}
      />,
    );
    expect(
      screen.getByRole("combobox", { name: /ub 457 x 191 x 89/i }),
    ).toBeInTheDocument();
  });

  it("falls back to the placeholder when no value is selected", () => {
    render(
      <SearchableSelect
        value=""
        onChange={() => {}}
        options={SECTIONS}
        placeholder="Choose a section…"
      />,
    );
    expect(screen.getByRole("combobox")).toHaveTextContent(/choose a section/i);
  });

  it("opens the listbox on click and renders all options", async () => {
    const user = userEvent.setup();
    render(
      <SearchableSelect value="" onChange={() => {}} options={SECTIONS} />,
    );
    await user.click(screen.getByRole("combobox"));
    const listbox = await screen.findByRole("listbox");
    expect(within(listbox).getAllByRole("option")).toHaveLength(3);
    expect(within(listbox).getByText("UB 457 x 191 x 89")).toBeInTheDocument();
    expect(within(listbox).getByText("IPE 500")).toBeInTheDocument();
  });

  it("renders the secondary text muted to the right when provided", async () => {
    const user = userEvent.setup();
    render(
      <SearchableSelect value="" onChange={() => {}} options={SECTIONS} />,
    );
    await user.click(screen.getByRole("combobox"));
    expect(await screen.findByText("463 × 192")).toBeInTheDocument();
    expect(screen.getByText("500 × 200")).toBeInTheDocument();
  });

  it("fuzzy matches across the label", async () => {
    const user = userEvent.setup();
    render(
      <SearchableSelect value="" onChange={() => {}} options={SECTIONS} />,
    );
    await user.click(screen.getByRole("combobox"));
    await user.keyboard("457");

    const listbox = await screen.findByRole("listbox");
    const optionTexts = within(listbox)
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(optionTexts.some((t) => t?.includes("457"))).toBe(true);
    expect(optionTexts.some((t) => t?.includes("IPE 500"))).toBe(false);
  });

  it("fuzzy matches via searchTerms (not the visible label)", async () => {
    const user = userEvent.setup();
    const opts: Opt[] = [
      { id: "alpha", label: "Alpha", searchTerms: ["foxtrot"] },
      { id: "bravo", label: "Bravo", searchTerms: ["whiskey"] },
    ];
    render(<SearchableSelect value="" onChange={() => {}} options={opts} />);
    await user.click(screen.getByRole("combobox"));
    await user.keyboard("foxtrot");

    const listbox = await screen.findByRole("listbox");
    const optionTexts = within(listbox)
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(optionTexts.some((t) => t?.includes("Alpha"))).toBe(true);
    expect(optionTexts.some((t) => t?.includes("Bravo"))).toBe(false);
  });

  it("selects the highlighted option on Enter and fires onChange", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <SearchableSelect value="" onChange={onChange} options={SECTIONS} />,
    );
    await user.click(screen.getByRole("combobox"));
    await screen.findByRole("listbox");
    // First option is highlighted by default; arrow down moves to the second.
    await user.keyboard("{ArrowDown}");
    await user.keyboard("{Enter}");
    expect(onChange).toHaveBeenCalledWith("UB_610x305x238");
  });

  it("closes the listbox on Escape without firing onChange", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <SearchableSelect value="" onChange={onChange} options={SECTIONS} />,
    );
    await user.click(screen.getByRole("combobox"));
    await screen.findByRole("listbox");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("clicking an option selects it and closes the listbox", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <SearchableSelect value="" onChange={onChange} options={SECTIONS} />,
    );
    await user.click(screen.getByRole("combobox"));
    const listbox = await screen.findByRole("listbox");
    await user.click(within(listbox).getByText("IPE 500"));
    expect(onChange).toHaveBeenCalledWith("IPE_500");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });
});
