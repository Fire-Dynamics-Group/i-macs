/** @jsxImportSource react */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(async (cmd: string) => {
    if (cmd === "get_sidecar_port") return 8765;
    throw new Error(`unmocked invoke: ${cmd}`);
  }),
}));

// Plotly is loaded eagerly by SweepScatter on the live page; stub the
// methods SweepScatter uses so jsdom doesn't blow up.
vi.mock("plotly.js-dist-min", () => ({
  default: { react: vi.fn(), purge: vi.fn(), newPlot: vi.fn() },
}));

class MockEventSource {
  url: string;
  onopen: ((e: Event) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  listeners: Record<string, Array<(e: MessageEvent) => void>> = {};
  constructor(url: string) {
    this.url = url;
  }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    (this.listeners[type] ||= []).push(fn);
  }
  removeEventListener() {}
  close() {}
}
vi.stubGlobal("EventSource", MockEventSource);

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

import { _resetBaseUrl } from "../api/client";
import BatchProgressPage from "./BatchProgressPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const COMPLETE_BATCH: {
  batch_id: string;
  created_at: string;
  mode: string;
  sampling: string | null;
  total_expected: number;
  run_count: number;
  pass_count: number;
  fail_count: number;
  error_count: number;
  varying_params: Record<string, unknown>;
  fixed_params: Record<string, unknown>;
} = {
  batch_id: "BATCH123",
  created_at: "2026-04-01T12:00:00+00:00",
  mode: "sweep",
  sampling: "paired",
  total_expected: 2,
  run_count: 2,
  pass_count: 2,
  fail_count: 0,
  error_count: 0,
  varying_params: { qf: [400, 500] },
  fixed_params: { span1: 9 },
};
const IN_FLIGHT_BATCH = { ...COMPLETE_BATCH, run_count: 1, pass_count: 1 };
const HISTORICAL_GRID_BATCH = { ...COMPLETE_BATCH, sampling: null };

const TWO_RUNS = [
  { id: 1, qf: 400, uf_max: 0.4, error: null, overall_pass: true, checks: [] },
  { id: 2, qf: 500, uf_max: 0.6, error: null, overall_pass: true, checks: [] },
];

function mockResponses(opts: {
  batch?: typeof COMPLETE_BATCH;
  batchStatus?: number;
  runs?: Array<Record<string, unknown>>;
  shearCheck?: {
    batch_id: string;
    checked: number;
    sub_limit_runs: Array<{ run_id: number; flags: Array<Record<string, unknown>> }>;
  };
}) {
  fetchMock.mockImplementation((url: string) => {
    if (url.includes("/shear-check")) {
      return Promise.resolve(
        jsonResponse(
          opts.shearCheck ?? {
            batch_id: "BATCH123",
            checked: opts.runs?.length ?? TWO_RUNS.length,
            sub_limit_runs: [],
          },
        ),
      );
    }
    if (url.includes("/distribution")) {
      // AnalyticalView mounts 3x DistributionChart — return a benign payload
      // so the chart wrapper renders without blowing up on undefined arrays.
      return Promise.resolve(
        jsonResponse({
          average: [],
          spaghetti: [],
          factored_hot_min: null,
          factored_hot_max: null,
        }),
      );
    }
    if (url.includes("/api/batches/BATCH123")) {
      const status = opts.batchStatus ?? 200;
      return Promise.resolve(jsonResponse(opts.batch ?? COMPLETE_BATCH, status));
    }
    if (url.includes("/api/runs?batch_id=")) {
      return Promise.resolve(jsonResponse({ runs: opts.runs ?? TWO_RUNS, stats: {} }));
    }
    return Promise.resolve(jsonResponse({ detail: "not mocked" }, 404));
  });
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/batches/BATCH123"]}>
        <Routes>
          <Route path="/batches/:batch_id" element={<BatchProgressPage />} />
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

describe("BatchProgressPage — analytical view", () => {
  it("renders the analytical view when run_count === total_expected", async () => {
    mockResponses({ batch: COMPLETE_BATCH, runs: TWO_RUNS });
    renderPage();
    // Wait for the analytical view's Download-report link — its presence
    // implies the batch metadata loaded and the async URL state settled.
    expect(await screen.findByRole("link", { name: /download report/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /batch BATCH123/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "#1" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "#2" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /rerun batch/i })).toBeInTheDocument();
  });

  it("shows the sub-limit shear-connection warning when runs breach EN 1994-1-1", async () => {
    mockResponses({
      batch: COMPLETE_BATCH,
      shearCheck: {
        batch_id: "BATCH123",
        checked: 2,
        sub_limit_runs: [
          {
            run_id: 2,
            flags: [
              { beam: "Unprotected", sh_con: 30, fy: 355, span: 9, eta_min_pct: 52 },
            ],
          },
        ],
      },
    });
    renderPage();
    expect(
      await screen.findByText(/degree of shear connection/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/EN 1994-1-1/i)).toBeInTheDocument();
    // Names the offending beam with its value vs the EN minimum.
    expect(
      screen.getByText(/Unprotected 30% \(min 52%\)/),
    ).toBeInTheDocument();
  });

  it("shows a clear pass note when no run is sub-limit", async () => {
    mockResponses({ batch: COMPLETE_BATCH }); // default shearCheck = none
    renderPage();
    expect(
      await screen.findByText(/meet the EN 1994-1-1 minimum/i),
    ).toBeInTheDocument();
  });

  it("Rerun batch link points at /?from_batch=BATCH123", async () => {
    mockResponses({ batch: COMPLETE_BATCH });
    renderPage();
    await waitFor(() => {
      const rerun = screen.getByRole("link", { name: /rerun batch/i });
      expect(rerun).toHaveAttribute("href", "/?from_batch=BATCH123");
    });
  });

  it("falls back to the live-progress view when run_count < total_expected", async () => {
    mockResponses({ batch: IN_FLIGHT_BATCH });
    renderPage();
    // Live view's progress section uses the "Trend" subheading from
    // SweepScatter; analytical action buttons are absent.
    await waitFor(() => {
      expect(screen.getByText(/trend/i)).toBeInTheDocument();
    });
    expect(screen.queryByRole("link", { name: /download report/i })).toBeNull();
    expect(screen.queryByRole("link", { name: /rerun batch/i })).toBeNull();
  });

  it("falls back to the live-progress view when the batch metadata 404s", async () => {
    mockResponses({ batchStatus: 404 });
    renderPage();
    // No analytical buttons rendered.
    await waitFor(() => {
      expect(screen.queryByRole("link", { name: /download report/i })).toBeNull();
    });
    // Live progress view's heading is still present.
    expect(screen.getByRole("heading", { name: /batch BATCH123/i })).toBeInTheDocument();
  });

  it("disables Rerun batch on historical grid batches (no sampling: paired)", async () => {
    mockResponses({ batch: HISTORICAL_GRID_BATCH, runs: TWO_RUNS });
    renderPage();
    expect(await screen.findByRole("link", { name: /download report/i })).toBeInTheDocument();
    // Rerun is a non-link span with a tooltip, not a clickable Link
    expect(screen.queryByRole("link", { name: /rerun batch/i })).toBeNull();
    const rerun = screen.getByText(/rerun batch/i);
    expect(rerun.tagName).toBe("SPAN");
    expect(rerun).toHaveAttribute("title", expect.stringMatching(/grid-mode/i));
  });
});
