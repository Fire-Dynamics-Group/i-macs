import { afterEach, describe, expect, it, vi } from "vitest";

// Mock the Tauri invoke command so the API client thinks the sidecar
// chose port 8765. This is the smoke check for slice 4 — slice 5 adds
// component-level tests that go through TanStack Query.
vi.mock("@tauri-apps/api/core", () => ({
  invoke: vi.fn(async (cmd: string) => {
    if (cmd === "get_sidecar_port") return 8765;
    throw new Error(`unmocked invoke: ${cmd}`);
  }),
}));

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

import {
  _resetBaseUrl,
  createCustomSection,
  deleteCustomSection,
  fetchHealth,
  fetchRefData,
  listCustomSections,
  submitRun,
} from "./client";

afterEach(() => {
  fetchMock.mockReset();
  _resetBaseUrl();
});

describe("api/client", () => {
  it("hits /healthz against the resolved sidecar port", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ sidecar: "alive", macs_installed: true, macs_version: "304" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const health = await fetchHealth();

    expect(health.macs_installed).toBe(true);
    expect(health.macs_version).toBe("304");
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8765/healthz");
  });

  it("hits /api/ref-data and decodes the response shape", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          sections: { IPE: [{ id: "IPE_500", name: "IPE 500", h: 500, b: 200 }] },
          decks: {},
          meshes: {},
          defaults: {},
          occupancy_presets: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const data = await fetchRefData();

    expect(data.sections.IPE[0].id).toBe("IPE_500");
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8765/api/ref-data");
  });

  it("POSTs JSON to /api/runs and returns the typed response", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: 7,
          uf_max: 0.42,
          duration_ms: 123,
          overall_pass: true,
          checks: {},
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const resp = await submitRun({ method: "iso" });

    expect(resp.id).toBe(7);
    expect(resp.uf_max).toBe(0.42);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8765/api/runs");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ method: "iso" });
  });

  it("surfaces an error when the sidecar replies 500 with JSON detail", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "engine timeout" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(submitRun({})).rejects.toThrow(/engine timeout/);
  });
});

describe("api/client — custom sections", () => {
  it("GETs /api/custom-sections and returns the stored rows", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify([
          { id: "CUSTOM_1", name: "Plate girder", h: 900, b: 300, tw: 12, tf: 25 },
        ]),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const sections = await listCustomSections();

    expect(sections).toHaveLength(1);
    expect(sections[0].id).toBe("CUSTOM_1");
    expect(sections[0].name).toBe("Plate girder");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8765/api/custom-sections",
    );
  });

  it("POSTs the five dimension fields to /api/custom-sections", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ id: "CUSTOM_2", name: "UB 533x165x74", h: 529.1, b: 165.9, tw: 9.7, tf: 13.6 }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    const created = await createCustomSection({
      name: "UB 533x165x74",
      h: 529.1,
      b: 165.9,
      tw: 9.7,
      tf: 13.6,
    });

    expect(created.id).toBe("CUSTOM_2");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8765/api/custom-sections");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({
      name: "UB 533x165x74",
      h: 529.1,
      b: 165.9,
      tw: 9.7,
      tf: 13.6,
    });
  });

  it("DELETEs /api/custom-sections/{id} with the id URL-encoded", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await deleteCustomSection("CUSTOM 1/x");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://127.0.0.1:8765/api/custom-sections/CUSTOM%201%2Fx");
    expect(init.method).toBe("DELETE");
  });

  it("surfaces the sidecar's error detail when a create fails", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "name already used" }), {
        status: 422,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(
      createCustomSection({ name: "dupe", h: 1, b: 1, tw: 1, tf: 1 }),
    ).rejects.toThrow(/name already used/);
  });
});
