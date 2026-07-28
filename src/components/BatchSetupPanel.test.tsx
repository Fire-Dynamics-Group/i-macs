/** @jsxImportSource react */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { BatchSetupPanel } from "./BatchSetupPanel";
import type { BatchSetup } from "../api/client";

const getBatchSetup = vi.fn();

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  getBatchSetup: (...args: unknown[]) => getBatchSetup(...args),
}));

const SETUP: BatchSetup = {
  run_count: 250,
  groups: [
    {
      title: "Geometry",
      fields: [
        { key: "span2", label: "Span 2", unit: "m", varies: false, value: 9 },
        {
          key: "span1",
          label: "Span 1",
          unit: "m",
          varies: true,
          distinct: 5,
          min: 9,
          max: 12,
        },
      ],
    },
    {
      title: "Beams",
      fields: [
        {
          key: "u_sec_size",
          label: "Unprotected section",
          unit: "",
          varies: false,
          value: "IPE_500",
        },
      ],
    },
  ],
};

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <BatchSetupPanel batchId="b1" />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  getBatchSetup.mockReset();
  getBatchSetup.mockResolvedValue(SETUP);
});

describe("BatchSetupPanel", () => {
  it("lists shared inputs with their value and unit", async () => {
    renderPanel();
    expect(await screen.findByText("Span 2")).toBeInTheDocument();
    expect(screen.getByTestId("setup-span2")).toHaveTextContent("9 m");
  });

  it("groups fields under the config form's section headings", async () => {
    renderPanel();
    expect(await screen.findByText("Geometry")).toBeInTheDocument();
    expect(screen.getByText("Beams")).toBeInTheDocument();
  });

  it("shows a range for an input that varied across the batch", async () => {
    renderPanel();
    const row = await screen.findByTestId("setup-span1");
    expect(row).toHaveTextContent("9–12 m");
    expect(row).toHaveTextContent("5 values");
  });

  it("marks varying inputs so they aren't mistaken for shared setup", async () => {
    renderPanel();
    expect(await screen.findByTestId("setup-span1")).toHaveAttribute(
      "data-varies",
      "true",
    );
    expect(screen.getByTestId("setup-span2")).toHaveAttribute(
      "data-varies",
      "false",
    );
  });

  it("omits the unit for dimensionless fields", async () => {
    renderPanel();
    const row = await screen.findByTestId("setup-u_sec_size");
    expect(row).toHaveTextContent("IPE_500");
  });

  it("lists sampled values for a non-numeric field that varied", async () => {
    getBatchSetup.mockResolvedValue({
      run_count: 3,
      groups: [
        {
          title: "Beams",
          fields: [
            {
              key: "u_sec_size",
              label: "Unprotected section",
              unit: "",
              varies: true,
              distinct: 2,
              values: ["IPE_300", "IPE_500"],
            },
          ],
        },
      ],
    } satisfies BatchSetup);
    renderPanel();
    expect(await screen.findByTestId("setup-u_sec_size")).toHaveTextContent(
      "IPE_300, IPE_500",
    );
  });

  it("explains an empty setup rather than rendering a blank panel", async () => {
    getBatchSetup.mockResolvedValue({ run_count: 0, groups: [] });
    renderPanel();
    expect(await screen.findByText(/no runs recorded yet/i)).toBeInTheDocument();
  });

  it("surfaces a fetch failure", async () => {
    getBatchSetup.mockRejectedValue(new Error("sidecar down"));
    renderPanel();
    expect(await screen.findByRole("alert")).toHaveTextContent("sidecar down");
  });

  it("can be collapsed so it doesn't dominate the page", async () => {
    const user = userEvent.setup();
    renderPanel();
    expect(await screen.findByText("Span 2")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /setup/i }));
    expect(screen.queryByText("Span 2")).not.toBeInTheDocument();
  });
});
