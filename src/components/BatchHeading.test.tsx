/** @jsxImportSource react */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BatchHeading } from "./BatchHeading";
import type { BatchSummary } from "../api/client";

const renameBatch = vi.fn();
const getFrcImport = vi.fn();

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  renameBatch: (...args: unknown[]) => renameBatch(...args),
  getFrcImport: (...args: unknown[]) => getFrcImport(...args),
}));

function makeBatch(overrides: Partial<BatchSummary> = {}): BatchSummary {
  return {
    batch_id: "0123456789abcdef0123456789abcdef",
    created_at: "2026-07-01T10:00:00Z",
    mode: "sweep",
    total_expected: 10,
    run_count: 10,
    pass_count: 8,
    fail_count: 2,
    error_count: 0,
    varying_params: {},
    fixed_params: {},
    ...overrides,
  };
}

function renderHeading(batch: BatchSummary) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <BatchHeading batch={batch} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  renameBatch.mockReset();
  getFrcImport.mockReset();
});

describe("BatchHeading", () => {
  it("shows the batch name as the heading when there is one", () => {
    renderHeading(makeBatch({ name: "Span sweep 9-12m" }));
    expect(
      screen.getByRole("heading", { name: "Span sweep 9-12m" }),
    ).toBeInTheDocument();
  });

  it("falls back to the short id when unnamed", () => {
    renderHeading(makeBatch());
    expect(
      screen.getByRole("heading", { name: /01234567/ }),
    ).toBeInTheDocument();
  });

  it("always exposes the full batch id", () => {
    renderHeading(makeBatch({ name: "Named" }));
    expect(
      screen.getByText("0123456789abcdef0123456789abcdef"),
    ).toBeInTheDocument();
  });

  it("shows the project name when set", () => {
    renderHeading(makeBatch({ project_name: "Atlantic Park Unit 7" }));
    expect(screen.getByText("Atlantic Park Unit 7")).toBeInTheDocument();
  });

  it("credits the source .frc when the batch was seeded from one", () => {
    renderHeading(
      makeBatch({
        frc: { id: "abc", filename: "unit7.frc", project: {} },
      }),
    );
    expect(screen.getByTestId("frc-source")).toHaveTextContent("unit7.frc");
  });

  it("omits the .frc line for a hand-configured batch", () => {
    renderHeading(makeBatch());
    expect(screen.queryByTestId("frc-source")).not.toBeInTheDocument();
  });

  it("opens a rename form prefilled with the current labels", async () => {
    const user = userEvent.setup();
    renderHeading(makeBatch({ name: "Old", project_name: "Proj" }));
    await user.click(screen.getByRole("button", { name: /rename/i }));
    expect(screen.getByTestId("rename-name-input")).toHaveValue("Old");
    expect(screen.getByTestId("rename-project-input")).toHaveValue("Proj");
  });

  it("saves trimmed labels and closes the form", async () => {
    const user = userEvent.setup();
    renameBatch.mockResolvedValue(makeBatch({ name: "New" }));
    renderHeading(makeBatch({ name: "Old", project_name: "Proj" }));

    await user.click(screen.getByRole("button", { name: /rename/i }));
    const nameInput = screen.getByTestId("rename-name-input");
    await user.clear(nameInput);
    await user.type(nameInput, "  New  ");
    await user.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() =>
      expect(renameBatch).toHaveBeenCalledWith(
        "0123456789abcdef0123456789abcdef",
        { name: "New", project_name: "Proj" },
      ),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("rename-name-input")).not.toBeInTheDocument(),
    );
  });

  it("discards edits on cancel", async () => {
    const user = userEvent.setup();
    renderHeading(makeBatch({ name: "Old" }));
    await user.click(screen.getByRole("button", { name: /rename/i }));
    await user.type(screen.getByTestId("rename-name-input"), "-edited");
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(renameBatch).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: /rename/i }));
    expect(screen.getByTestId("rename-name-input")).toHaveValue("Old");
  });

  it("surfaces a rename failure instead of silently discarding it", async () => {
    const user = userEvent.setup();
    renameBatch.mockRejectedValue(new Error("sidecar down"));
    renderHeading(makeBatch({ name: "Old" }));

    await user.click(screen.getByRole("button", { name: /rename/i }));
    await user.click(screen.getByRole("button", { name: /save/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("sidecar down");
    // The form stays open so the edit isn't lost.
    expect(screen.getByTestId("rename-name-input")).toBeInTheDocument();
  });
});
