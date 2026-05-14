import { type Page } from "@playwright/test";

const DEFAULT_REF_DATA = {
  sections: {
    UB: [
      { id: "UB_457x191x89", name: "UB 457 x 191 x 89", h: 463, b: 192 },
      { id: "UB_610x305x238", name: "UB 610 x 305 x 238", h: 635, b: 311 },
    ],
    IPE: [{ id: "IPE_500", name: "IPE 500", h: 500, b: 200 }],
  },
  decks: {
    T14: { name: "COFRAPLUS 60", deck_type: "T", deck_depth: 58 },
  },
  meshes: {
    ST15C: { name: "ST15C", mainArea: 142, transArea: 142 },
    A393: { name: "A393", mainArea: 393, transArea: 393 },
  },
  defaults: {
    span1: 9, span2: 9, numbeam: 2, slab_depth: 130, fck: 25,
    conc_type: "NW", method: "iso", time_limit: 60,
    qf: 511, window_percent: 95, Lc: 27, Bc: 18, Hc: 3.6, Hw: 1.8, Lw: 30,
    Bfac: 720, combustion_factor: 0.8, growth_rate: 1,
    DeckId: "T14", mesh_type: "ST15C",
    uSecSize: "IPE_500", fy5: "355", ush_con: 80,
    SideASecSize: "IPE_500", fy1: "355", SideAEdgeFlag: 1, SideACompoFlag: 0, SideAsh_con: 80,
    SideBSecSize: "IPE_500", fy2: "355", SideBEdgeFlag: 0, SideBCompoFlag: 1, SideBsh_con: 80,
    SideCSecSize: "IPE_500", fy3: "355", SideCEdgeFlag: 0, SideCCompoFlag: 1, SideCsh_con: 80,
    SideDSecSize: "IPE_500", fy4: "355", SideDEdgeFlag: 1, SideDCompoFlag: 0, SideDsh_con: 80,
  },
  occupancy_presets: [
    { name: "Office", mean: 420, type: "gumbel", cov: 0.3 },
  ],
};

const DEFAULT_HEALTHZ = {
  sidecar: "alive",
  macs_installed: true,
  macs_version: "304",
};

interface MockOpts {
  sidecarPort: number;
  refData?: typeof DEFAULT_REF_DATA;
  healthz?: typeof DEFAULT_HEALTHZ;
  /** Override the default 200 OK + uf_max=0.42 response from POST /api/runs. */
  submitRun?: { status: number; body: Record<string, unknown> };
  /** Override the default 200 OK + batch_id response from POST /api/sweeps. */
  submitSweep?: { status: number; body: Record<string, unknown> };
  /** Runs returned by GET /api/runs?batch_id=... — defaults to empty. */
  batchRuns?: Array<Record<string, unknown>>;
  /**
   * SSE event sequence sent when the dashboard subscribes to /api/sweeps/events.
   * Each event becomes one record on the stream. The default sends a small
   * sweep that ends in batch_done so the dashboard freezes in 'closed' state.
   */
  sweepEvents?: Array<{ event: "run_completed" | "batch_done"; data: Record<string, unknown> }>;
  /** Stats payload from /api/stats. */
  stats?: Record<string, number>;
  /** Batches list returned by GET /api/batches. */
  batches?: { batches: Array<Record<string, unknown>>; total: number };
  /** Ungrouped runs returned by GET /api/runs/ungrouped. */
  ungrouped?: { runs: Array<Record<string, unknown>>; total: number };
  /** Map of batch_id → summary for GET /api/batches/{batch_id}. */
  batchSummaries?: Record<string, Record<string, unknown>>;
  /** Map of run id → row for GET /api/runs/{id}. Falls back to the default
   *  pass response when the requested id isn't in the map. */
  runs?: Record<string, Record<string, unknown>>;
  /** Map of column → payload returned by GET /api/batches/:id/distribution.
   *  Falls back to an empty payload (renders the "No successful runs"
   *  placeholder) when not configured. */
  distribution?: Record<string, {
    average: Array<[number, number]>;
    spaghetti: Array<{ run_id: number; points: Array<[number, number]> }>;
    factored_hot_min: number | null;
    factored_hot_max: number | null;
  }>;
}

/**
 * Intercepts the React app's fetches to the FastAPI sidecar and returns
 * canned responses. Pair with `installTauriShim` so the API client's
 * `invoke('get_sidecar_port')` returns `sidecarPort`.
 */
export async function installSidecarMock(page: Page, opts: MockOpts) {
  const refData = opts.refData ?? DEFAULT_REF_DATA;
  const healthz = opts.healthz ?? DEFAULT_HEALTHZ;
  const submitRun =
    opts.submitRun ?? {
      status: 200,
      body: {
        id: 1,
        uf_max: 0.42,
        duration_ms: 200,
        overall_pass: true,
        checks: {},
      },
    };
  const submitSweep =
    opts.submitSweep ?? {
      status: 200,
      body: {
        batch_id: "BATCH123",
        total: 4,
        message: "Sweep started",
      },
    };
  const batchRuns = opts.batchRuns ?? [];
  const sweepEvents = opts.sweepEvents ?? [
    {
      event: "run_completed",
      data: {
        type: "run_completed",
        run: {
          id: 1, batch_id: "BATCH123", qf: 400, uf_max: 0.4,
          error: null, overall_pass: true, checks: {},
        },
        batch_id: "BATCH123", total: 2, completed: 1, errors: 0,
      },
    },
    {
      event: "run_completed",
      data: {
        type: "run_completed",
        run: {
          id: 2, batch_id: "BATCH123", qf: 500, uf_max: 0.6,
          error: null, overall_pass: true, checks: {},
        },
        batch_id: "BATCH123", total: 2, completed: 2, errors: 0,
      },
    },
    {
      event: "batch_done",
      data: {
        type: "batch_done",
        batch_id: "BATCH123",
        total: 2, completed: 2, errors: 0,
      },
    },
  ];

  function formatSseStream(): string {
    return sweepEvents
      .map(
        (ev) => `event: ${ev.event}\ndata: ${JSON.stringify(ev.data)}\n\n`,
      )
      .join("");
  }

  await page.route(`http://127.0.0.1:${opts.sidecarPort}/**`, async (route) => {
    const url = new URL(route.request().url());
    const method = route.request().method();
    if (method === "GET" && url.pathname === "/healthz") {
      return route.fulfill({ status: 200, json: healthz });
    }
    if (method === "GET" && url.pathname === "/api/ref-data") {
      return route.fulfill({ status: 200, json: refData });
    }
    if (method === "POST" && url.pathname === "/api/runs") {
      return route.fulfill({ status: submitRun.status, json: submitRun.body });
    }
    if (method === "POST" && url.pathname === "/api/sweeps") {
      return route.fulfill({ status: submitSweep.status, json: submitSweep.body });
    }
    if (method === "GET" && url.pathname === "/api/runs/ungrouped") {
      return route.fulfill({
        status: 200,
        json: opts.ungrouped ?? { runs: [], total: 0 },
      });
    }
    if (method === "GET" && url.pathname === "/api/runs") {
      // batch_id filter or general list — both shapes tested.
      return route.fulfill({
        status: 200,
        json: { runs: batchRuns, stats: {} },
      });
    }
    if (method === "GET" && url.pathname === "/api/stats") {
      return route.fulfill({
        status: 200,
        json: opts.stats ?? {
          total: 0, successful: 0, errors: 0, pass_count: 0, fail_count: 0,
        },
      });
    }
    if (method === "GET" && url.pathname === "/api/batches") {
      return route.fulfill({
        status: 200,
        json: opts.batches ?? { batches: [], total: 0 },
      });
    }
    if (method === "GET" && url.pathname.startsWith("/api/batches/")) {
      const tail = url.pathname.slice("/api/batches/".length);
      const slash = tail.indexOf("/");
      if (slash >= 0 && tail.slice(slash + 1) === "distribution") {
        const column = url.searchParams.get("column") ?? "";
        const payload = (opts.distribution ?? {})[column] ?? {
          average: [],
          spaghetti: [],
          factored_hot_min: null,
          factored_hot_max: null,
        };
        return route.fulfill({ status: 200, json: payload });
      }
      const id = tail;
      const summary = (opts.batchSummaries ?? {})[id];
      if (!summary) {
        return route.fulfill({ status: 404, json: { error: "Not found" } });
      }
      return route.fulfill({ status: 200, json: summary });
    }
    if (method === "GET" && url.pathname.startsWith("/api/report/chart/")) {
      // 1x1 transparent PNG. <img> needs *something* or jsdom logs noise.
      const png = Buffer.from(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489" +
          "0000000a49444154789c6300010000050001" +
          "0d0a2db40000000049454e44ae426082",
        "hex",
      );
      return route.fulfill({
        status: 200,
        contentType: "image/png",
        body: png,
      });
    }
    if (method === "GET" && url.pathname === "/api/sweeps/events") {
      return route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: formatSseStream(),
      });
    }
    if (method === "GET" && url.pathname.startsWith("/api/runs/")) {
      if (url.pathname.endsWith("/timeseries")) {
        return route.fulfill({
          status: 200,
          json: [
            { time_step: 1, time_min: 5, fire_temp: 576, utilization_factor: 0.2, total_plate_capacity: 700 },
            { time_step: 2, time_min: 10, fire_temp: 678, utilization_factor: 0.4, total_plate_capacity: 650 },
          ],
        });
      }
      const id = url.pathname.slice("/api/runs/".length);
      const override = (opts.runs ?? {})[id];
      return route.fulfill({
        status: 200,
        json: override ?? {
          id: 1,
          uf_max: 0.42,
          duration_ms: 200,
          error: null,
          overall_pass: true,
          checks: [
            { name: "Slab UF", value: 0.42, limit: 1.0, pass: true },
            { name: "Composite section", value: 0, limit: 0, pass: true },
            { name: "Side A beam load", value: 0.3, limit: 1.0, pass: true },
            { name: "Side B beam load", value: 0.4, limit: 1.0, pass: true },
            { name: "Side C beam load", value: 0.35, limit: 1.0, pass: true },
            { name: "Side D beam load", value: 0.32, limit: 1.0, pass: true },
          ],
        },
      });
    }
    return route.fulfill({ status: 404, json: { detail: "Not Found" } });
  });
}
