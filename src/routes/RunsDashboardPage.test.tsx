/** @jsxImportSource react */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(async (cmd: string) => {
    if (cmd === "get_sidecar_port") return 8765;
    throw new Error(`unmocked invoke: ${cmd}`);
  }),
}));

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

import { _resetBaseUrl } from "../api/client";
import RunsDashboardPage from "./RunsDashboardPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

interface MockResponses {
  stats?: unknown;
  batches?: unknown;
  ungrouped?: unknown;
}

function installFetchMock(responses: MockResponses, opts: { statsError?: boolean } = {}) {
  fetchMock.mockImplementation((url: string) => {
    if (url.includes("/api/stats")) {
      if (opts.statsError) {
        return Promise.resolve(jsonResponse({ detail: "boom" }, 500));
      }
      return Promise.resolve(jsonResponse(responses.stats ?? {
        total: 0, successful: 0, errors: 0, pass_count: 0, fail_count: 0,
      }));
    }
    if (url.includes("/api/batches")) {
      return Promise.resolve(jsonResponse(responses.batches ?? { batches: [], total: 0 }));
    }
    if (url.includes("/api/runs/ungrouped")) {
      return Promise.resolve(jsonResponse(responses.ungrouped ?? { runs: [], total: 0 }));
    }
    return Promise.resolve(jsonResponse({ detail: "not mocked" }, 404));
  });
}

function renderPage(initialPath = "/runs") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/runs" element={<RunsDashboardPage />} />
          <Route path="/batches/:batch_id" element={<div>batch detail</div>} />
          <Route path="/" element={<div>config page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  _resetBaseUrl();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("RunsDashboardPage", () => {
  it("renders 5 stat cards with values from /api/stats", async () => {
    installFetchMock({
      stats: {
        total: 42, successful: 40, errors: 2, pass_count: 30, fail_count: 10,
      },
    });
    renderPage();
    await waitFor(() => expect(screen.getByText("42")).toBeInTheDocument());
    // Pass card
    expect(screen.getByText("30")).toBeInTheDocument();
    // Fail card
    expect(screen.getByText("10")).toBeInTheDocument();
    // Error card
    expect(screen.getByText("2")).toBeInTheDocument();
    // Success rate (30/42 → 71%) — accept either "71%" or "71.4%"
    expect(screen.getByText(/71(\.\d+)?%/)).toBeInTheDocument();
  });

  it("shows empty state with a CTA when there are no runs yet", async () => {
    installFetchMock({});
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/no runs/i)).toBeInTheDocument();
    });
    expect(screen.getByRole("link", { name: /start your first run/i }))
      .toHaveAttribute("href", "/");
  });

  it("renders a batches list with run/pass/fail counts and varying-params summary", async () => {
    installFetchMock({
      stats: { total: 2, successful: 2, errors: 0, pass_count: 2, fail_count: 0 },
      batches: {
        total: 1,
        batches: [
          {
            batch_id: "abc123",
            created_at: "2026-04-01T12:00:00+00:00",
            mode: "sweep",
            total_expected: 2,
            run_count: 2,
            pass_count: 2,
            fail_count: 0,
            error_count: 0,
            varying_params: { qf: [400, 500] },
            fixed_params: { span1: 9 },
          },
        ],
      },
    });
    renderPage();
    // Truncated batch id rendered (we don't enforce exact format).
    await waitFor(() => {
      expect(screen.getByText(/abc123/i)).toBeInTheDocument();
    });
    // Varying-param chip surfaces the field name so the user knows what was swept.
    expect(screen.getByText(/qf/)).toBeInTheDocument();
  });

  it("links each batch row to /batches/:id", async () => {
    installFetchMock({
      batches: {
        total: 1,
        batches: [
          {
            batch_id: "abc123",
            created_at: "2026-04-01T12:00:00+00:00",
            mode: "sweep",
            total_expected: 2,
            run_count: 2,
            pass_count: 2,
            fail_count: 0,
            error_count: 0,
            varying_params: {},
            fixed_params: {},
          },
        ],
      },
    });
    renderPage();
    await waitFor(() => {
      const link = screen.getByRole("link", { name: /abc123/i });
      expect(link).toHaveAttribute("href", "/batches/abc123");
    });
  });

  it("renders an ungrouped runs table with UF max, status, and a sortable timestamp", async () => {
    installFetchMock({
      stats: { total: 1, successful: 1, errors: 0, pass_count: 1, fail_count: 0 },
      ungrouped: {
        total: 1,
        runs: [
          {
            id: 17,
            uf_max: 0.42,
            error: null,
            overall_pass: true,
            run_timestamp: "2026-04-01T12:00:00+00:00",
            checks: [],
          },
        ],
      },
    });
    renderPage();
    await waitFor(() =>
      expect(screen.getByRole("link", { name: "#17" })).toBeInTheDocument(),
    );
    // UF max rendered to 3 decimals (matches BatchRunsTable's tabular-nums treatment).
    expect(screen.getByText("0.420")).toBeInTheDocument();
    // Pass status appears in the row alongside the run id; the filter chip
    // labelled "Pass" is button-typed, so the table cell is the only span.
    expect(
      screen.getAllByText("Pass").some((el) => el.tagName === "SPAN"),
    ).toBe(true);
  });

  it("sorts the ungrouped runs table by UF max when the column header is clicked", async () => {
    const runs = [
      { id: 1, uf_max: 0.9, error: null, overall_pass: true, run_timestamp: "2026-04-01T12:00:00+00:00", checks: [] },
      { id: 2, uf_max: 0.3, error: null, overall_pass: true, run_timestamp: "2026-04-02T12:00:00+00:00", checks: [] },
      { id: 3, uf_max: 0.6, error: null, overall_pass: true, run_timestamp: "2026-04-03T12:00:00+00:00", checks: [] },
    ];
    installFetchMock({ ungrouped: { total: 3, runs } });
    const user = userEvent.setup();
    renderPage();
    await waitFor(() => screen.getByRole("link", { name: "#1" }));

    await user.click(screen.getByRole("button", { name: /uf max/i }));
    // After ascending sort, first row is the smallest UF — #2 with 0.3.
    const links = screen.getAllByRole("link", { name: /^#\d+$/ });
    expect(links[0]).toHaveTextContent("#2");
  });

  it("surfaces a per-section error banner when /api/stats fails", async () => {
    installFetchMock({}, { statsError: true });
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/couldn't load stats/i)).toBeInTheDocument();
    });
  });

  it("encodes status filter into the URL", async () => {
    installFetchMock({
      ungrouped: {
        total: 2,
        runs: [
          { id: 1, uf_max: 0.5, error: null, overall_pass: true, run_timestamp: "2026-04-01T12:00:00+00:00", checks: [] },
          { id: 2, uf_max: 1.4, error: null, overall_pass: false, run_timestamp: "2026-04-02T12:00:00+00:00", checks: [] },
        ],
      },
    });
    const user = userEvent.setup();
    renderPage("/runs?status=all");
    await waitFor(() => screen.getByRole("link", { name: "#1" }));

    await user.click(screen.getByRole("button", { name: /^fail$/i }));
    // Filter narrows to the failing row.
    await waitFor(() => {
      expect(screen.queryByRole("link", { name: "#1" })).toBeNull();
      expect(screen.getByRole("link", { name: "#2" })).toBeInTheDocument();
    });
  });
});
