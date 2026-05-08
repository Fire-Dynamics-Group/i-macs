/** @jsxImportSource react */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { CheckBreakdown } from "./CheckBreakdown";

describe("CheckBreakdown", () => {
  it("renders a row per check with name, value, limit, and status badge", () => {
    render(
      <CheckBreakdown
        checks={[
          { name: "Slab UF", value: 0.42, limit: 1.0, pass: true },
          { name: "Side B beam load", value: 1.18, limit: 1.0, pass: false },
        ]}
      />,
    );
    expect(screen.getByText("Slab UF")).toBeInTheDocument();
    expect(screen.getByText("0.420")).toBeInTheDocument();
    expect(screen.getByText("Side B beam load")).toBeInTheDocument();
    expect(screen.getByText("1.180")).toBeInTheDocument();
    // Both rows have a status word.
    expect(screen.getAllByText(/Pass|Fail/).length).toBeGreaterThanOrEqual(2);
  });

  it("renders dash for null/undefined check values", () => {
    render(
      <CheckBreakdown
        checks={[
          { name: "Composite section", value: null, limit: 0, pass: true },
        ]}
      />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("formats the limit as ≤ {limit} for ratio checks", () => {
    render(
      <CheckBreakdown
        checks={[{ name: "Slab UF", value: 0.42, limit: 1.0, pass: true }]}
      />,
    );
    expect(screen.getByText(/≤\s*1\.00/)).toBeInTheDocument();
  });

  it("formats the composite-section limit as flag = 0 (not a number)", () => {
    render(
      <CheckBreakdown
        checks={[
          { name: "Composite section", value: 0, limit: 0, pass: true },
        ]}
      />,
    );
    expect(screen.getByText(/flag\s*=\s*0/)).toBeInTheDocument();
  });

  it("returns null when there are no checks", () => {
    const { container } = render(<CheckBreakdown checks={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("flags the failing row visually so beam failures stand out", () => {
    render(
      <CheckBreakdown
        checks={[
          { name: "Slab UF", value: 0.42, limit: 1.0, pass: true },
          { name: "Side B beam load", value: 1.18, limit: 1.0, pass: false },
          { name: "Side C beam load", value: 1.05, limit: 1.0, pass: false },
        ]}
      />,
    );
    // Two failing rows present → two "Fail" badges.
    expect(screen.getAllByText("Fail")).toHaveLength(2);
    // One passing row.
    expect(screen.getAllByText("Pass")).toHaveLength(1);
  });
});
