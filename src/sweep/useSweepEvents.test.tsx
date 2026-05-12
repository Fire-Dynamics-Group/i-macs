/** @jsxImportSource react */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";

vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(async (cmd: string) => {
    if (cmd === "get_sidecar_port") return 8765;
    throw new Error(`unmocked invoke: ${cmd}`);
  }),
}));

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  closed = false;
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  listeners: Record<string, Array<(e: MessageEvent) => void>> = {};

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    (this.listeners[type] ||= []).push(fn);
  }

  removeEventListener(type: string, fn: (e: MessageEvent) => void) {
    this.listeners[type] = (this.listeners[type] || []).filter((f) => f !== fn);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, data: unknown) {
    const fns = this.listeners[type] || [];
    const ev = new MessageEvent(type, { data: JSON.stringify(data) });
    fns.forEach((fn) => fn(ev));
  }

  emitError() {
    if (this.onerror) this.onerror(new Event("error"));
  }
}

vi.stubGlobal("EventSource", MockEventSource);

import { _resetBaseUrl } from "../api/client";
import { useSweepEvents } from "./useSweepEvents";

beforeEach(() => {
  fetchMock.mockReset();
  MockEventSource.instances = [];
  _resetBaseUrl();
});

afterEach(() => {
  // Close any leftover sources.
  MockEventSource.instances.forEach((s) => s.close());
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("useSweepEvents", () => {
  it("backfills runs from /api/runs?batch_id=… and then opens an EventSource", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({
        runs: [
          { id: 1, batch_id: "B1", uf_max: 0.5, error: null },
          { id: 2, batch_id: "B1", uf_max: 0.7, error: null },
        ],
        stats: { total: 2, successful: 2, errors: 0, pass_count: 2, fail_count: 0 },
      }),
    );

    const { result } = renderHook(() => useSweepEvents("B1"));

    await waitFor(() => expect(result.current.runs.length).toBe(2));

    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8765/api/runs?batch_id=B1");
    expect(MockEventSource.instances.length).toBe(1);
    expect(MockEventSource.instances[0].url).toBe("http://127.0.0.1:8765/api/sweeps/events");
    expect(result.current.status).toBe("streaming");
  });

  it("appends a run_completed event to the runs list and updates the summary", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ runs: [], stats: {} }),
    );

    const { result } = renderHook(() => useSweepEvents("B1"));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    const es = MockEventSource.instances[0];

    act(() => {
      es.emit("run_completed", {
        type: "run_completed",
        run: { id: 7, batch_id: "B1", uf_max: 0.42, error: null },
        batch_id: "B1",
        total: 3,
        completed: 1,
        errors: 0,
      });
    });

    expect(result.current.runs.length).toBe(1);
    expect(result.current.runs[0].id).toBe(7);
    expect(result.current.completed).toBe(1);
    expect(result.current.total).toBe(3);
    expect(result.current.errors).toBe(0);
  });

  it("ignores run_completed events for a different batch", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ runs: [], stats: {} }));
    const { result } = renderHook(() => useSweepEvents("B1"));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    const es = MockEventSource.instances[0];

    act(() => {
      es.emit("run_completed", {
        type: "run_completed",
        run: { id: 99, batch_id: "OTHER", uf_max: 0.1, error: null },
        batch_id: "OTHER",
        total: 5,
        completed: 1,
        errors: 0,
      });
    });

    expect(result.current.runs).toEqual([]);
    expect(result.current.total).toBeNull();
  });

  it("counts errored runs in the errors summary", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ runs: [], stats: {} }));
    const { result } = renderHook(() => useSweepEvents("B1"));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    const es = MockEventSource.instances[0];

    act(() => {
      es.emit("run_completed", {
        type: "run_completed",
        run: { id: 8, batch_id: "B1", uf_max: null, error: "COM error" },
        batch_id: "B1",
        total: 2,
        completed: 1,
        errors: 1,
      });
    });

    expect(result.current.runs.length).toBe(1);
    expect(result.current.errors).toBe(1);
  });

  it("closes the EventSource and sets status to closed on batch_done", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ runs: [], stats: {} }));
    const { result } = renderHook(() => useSweepEvents("B1"));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    const es = MockEventSource.instances[0];

    act(() => {
      es.emit("batch_done", {
        type: "batch_done",
        batch_id: "B1",
        total: 3,
        completed: 3,
        errors: 0,
      });
    });

    expect(es.closed).toBe(true);
    expect(result.current.status).toBe("closed");
    expect(result.current.total).toBe(3);
    expect(result.current.completed).toBe(3);
  });

  it("ignores batch_done events for a different batch", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ runs: [], stats: {} }));
    const { result } = renderHook(() => useSweepEvents("B1"));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    const es = MockEventSource.instances[0];

    act(() => {
      es.emit("batch_done", {
        type: "batch_done",
        batch_id: "OTHER",
        total: 9,
        completed: 9,
        errors: 0,
      });
    });

    expect(es.closed).toBe(false);
    expect(result.current.status).toBe("streaming");
  });

  it("transitions to error status on EventSource error", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ runs: [], stats: {} }));
    const { result } = renderHook(() => useSweepEvents("B1"));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    const es = MockEventSource.instances[0];

    act(() => {
      es.emitError();
    });

    expect(result.current.status).toBe("error");
  });

  it("closes the EventSource on unmount", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ runs: [], stats: {} }));
    const { unmount } = renderHook(() => useSweepEvents("B1"));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    const es = MockEventSource.instances[0];

    unmount();
    expect(es.closed).toBe(true);
  });

  it("reports an error when the backfill GET fails", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "boom" }), { status: 500 }),
    );

    const { result } = renderHook(() => useSweepEvents("B1"));

    await waitFor(() => expect(result.current.status).toBe("error"));
    expect(result.current.error).toBeTruthy();
    // Backfill failure should not have opened an EventSource.
    expect(MockEventSource.instances.length).toBe(0);
  });
});
