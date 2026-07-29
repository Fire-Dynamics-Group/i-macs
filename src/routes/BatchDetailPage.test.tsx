/** @jsxImportSource react */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

import { _resetBaseUrl, type BatchSetup, type BatchSummary } from "../api/client";
import BatchProgressPage from "./BatchProgressPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function zipResponse(filename = "macs_data_BATCH123.zip"): Response {
  return new Response("PKstub", {
    status: 200,
    headers: {
      "Content-Type": "application/zip",
      "Content-Disposition": `attachment; filename="${filename}"`,
    },
  });
}

/** Overridable so a test can defer or fail the export request. */
let zipHandler: () => Promise<Response> = () => Promise.resolve(zipResponse());

// jsdom has no object-URL plumbing; saveBlob() only needs these to not throw.
vi.stubGlobal("URL", {
  ...URL,
  createObjectURL: vi.fn(() => "blob:stub"),
  revokeObjectURL: vi.fn(),
});

const COMPLETE_BATCH: BatchSummary = {
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
  setup?: BatchSetup;
  runs?: Array<Record<string, unknown>>;
  shearCheck?: {
    batch_id: string;
    checked: number;
    sub_limit_runs: Array<{ run_id: number; flags: Array<Record<string, unknown>> }>;
  };
}) {
  fetchMock.mockImplementation((url: string) => {
    if (url.includes("/api/report/zip")) {
      return zipHandler();
    }
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
    // Must precede the bare /api/batches/BATCH123 match below — that prefix
    // also matches this URL, and returning a BatchSummary here would feed the
    // setup panel a payload with no `groups`.
    if (url.includes("/setup")) {
      return Promise.resolve(
        jsonResponse(opts.setup ?? { run_count: 2, groups: [] }),
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
  zipHandler = () => Promise.resolve(zipResponse());
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
    // Unnamed batch — the heading falls back to the short id, and the full id
    // stays visible on the line beneath it.
    expect(screen.getByRole("heading", { name: "BATCH123" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "#1" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "#2" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /rerun batch/i })).toBeInTheDocument();
  });

  it("shows the shared setup for a batch that was never seeded from a .frc", async () => {
    mockResponses({
      batch: COMPLETE_BATCH,
      runs: TWO_RUNS,
      setup: {
        run_count: 2,
        groups: [
          {
            title: "Geometry",
            fields: [
              { key: "span2", label: "Span 2", unit: "m", varies: false, value: 9 },
            ],
          },
        ],
      },
    });
    renderPage();
    expect(await screen.findByTestId("setup-span2")).toHaveTextContent("9 m");
  });

  it("shows the batch name and project when the batch is named", async () => {
    mockResponses({
      batch: {
        ...COMPLETE_BATCH,
        name: "Span sweep 9-12m",
        project_name: "Atlantic Park Unit 7",
        frc: { id: "abc123", filename: "unit7.frc", project: {} },
      },
      runs: TWO_RUNS,
    });
    renderPage();
    expect(
      await screen.findByRole("heading", { name: "Span sweep 9-12m" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Atlantic Park Unit 7")).toBeInTheDocument();
    expect(screen.getByTestId("frc-source")).toHaveTextContent("unit7.frc");
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

describe("BatchProgressPage — results download", () => {
  const downloadButton = () =>
    screen.findByRole("button", { name: /download|preparing/i });

  /** Resolve the export request by hand, so the pending state is observable. */
  function deferExport() {
    let settle!: (r: Response) => void;
    let fail!: (e: Error) => void;
    const pending = new Promise<Response>((res, rej) => {
      settle = res;
      fail = rej;
    });
    zipHandler = () => pending;
    return { settle, fail };
  }

  it("asks the sidecar for the data by default", async () => {
    mockResponses({});
    renderPage();
    fireEvent.click(await downloadButton());

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          (call) =>
            String(call[0]).includes("/api/report/zip") &&
            String(call[0]).includes("include=data"),
        ),
      ).toBe(true),
    );
  });

  it.each([
    ["charts", "include=charts"],
    ["both", "include=both"],
  ])("requests %s when chosen", async (mode, expected) => {
    mockResponses({});
    renderPage();
    await downloadButton();

    fireEvent.change(screen.getByLabelText(/what to download/i), {
      target: { value: mode },
    });
    fireEvent.click(await downloadButton());

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          (call) =>
            String(call[0]).includes("/api/report/zip") &&
            String(call[0]).includes(expected),
        ),
      ).toBe(true),
    );
  });

  it("shows progress while the sidecar builds the export", async () => {
    mockResponses({});
    const { settle } = deferExport();
    renderPage();
    fireEvent.click(await downloadButton());

    // A 10k chart export takes ~25s server-side — the user must see something.
    const busy = await screen.findByRole("button", { name: /preparing/i });
    expect(busy).toBeDisabled();
    expect(screen.getByRole("status")).toBeInTheDocument();

    settle(zipResponse());
    await waitFor(() =>
      expect(screen.queryByRole("status")).not.toBeInTheDocument(),
    );
  });

  it("re-enables the button once the export finishes", async () => {
    mockResponses({});
    renderPage();
    fireEvent.click(await downloadButton());

    await waitFor(async () => expect(await downloadButton()).toBeEnabled());
  });

  it("confirms the save, naming the file", async () => {
    // The Tauri webview has no download bar, so without this the spinner just
    // vanishes and the user cannot tell whether anything was saved.
    mockResponses({});
    renderPage();
    fireEvent.click(await downloadButton());

    expect(await screen.findByTestId("download-saved")).toHaveTextContent(
      "macs_data_BATCH123.zip",
    );
  });

  it("clears the previous confirmation when a new export starts", async () => {
    mockResponses({});
    renderPage();
    fireEvent.click(await downloadButton());
    await screen.findByTestId("download-saved");

    const { settle } = deferExport();
    fireEvent.click(await downloadButton());
    await waitFor(() =>
      expect(screen.queryByTestId("download-saved")).not.toBeInTheDocument(),
    );
    settle(zipResponse());
  });

  it("surfaces a sidecar failure instead of dumping JSON at the user", async () => {
    mockResponses({});
    zipHandler = () =>
      Promise.resolve(
        jsonResponse({ detail: "No module named 'matplotlib'" }, 500),
      );
    renderPage();
    fireEvent.click(await downloadButton());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /No module named 'matplotlib'/,
    );
  });

  it("clears a previous error when the next attempt starts", async () => {
    mockResponses({});
    zipHandler = () => Promise.resolve(jsonResponse({ detail: "boom" }, 500));
    renderPage();
    fireEvent.click(await downloadButton());
    await screen.findByRole("alert");

    const { settle } = deferExport();
    fireEvent.click(await downloadButton());
    await waitFor(() =>
      expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
    );
    settle(zipResponse());
  });

  it("keeps the results download separate from the report download", async () => {
    mockResponses({});
    renderPage();

    expect(await downloadButton()).toBeInTheDocument();
    expect(
      await screen.findByRole("link", { name: /download report/i }),
    ).toBeInTheDocument();
  });
});
