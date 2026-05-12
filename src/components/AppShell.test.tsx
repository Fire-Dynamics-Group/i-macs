/** @jsxImportSource react */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AppShell } from "./AppShell";

function renderShell(initialPath = "/") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <AppShell>
        <Routes>
          <Route path="/" element={<div>config page</div>} />
          <Route path="/runs" element={<div>runs page</div>} />
        </Routes>
      </AppShell>
    </MemoryRouter>,
  );
}

describe("AppShell", () => {
  it("renders the New Run nav link pointing at /", () => {
    renderShell();
    const link = screen.getByRole("link", { name: /new run/i });
    expect(link).toHaveAttribute("href", "/");
  });

  it("renders the History nav link pointing at /runs", () => {
    renderShell();
    const link = screen.getByRole("link", { name: /history/i });
    expect(link).toHaveAttribute("href", "/runs");
  });

  it("renders its children in the main outlet", () => {
    renderShell("/");
    expect(screen.getByText("config page")).toBeInTheDocument();
  });

  it("marks the active route's link aria-current", () => {
    renderShell("/runs");
    const history = screen.getByRole("link", { name: /history/i });
    expect(history).toHaveAttribute("aria-current", "page");
    const newRun = screen.getByRole("link", { name: /new run/i });
    expect(newRun).not.toHaveAttribute("aria-current", "page");
  });
});
