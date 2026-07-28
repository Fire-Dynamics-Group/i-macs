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

vi.mock("@tauri-apps/plugin-dialog", () => ({
  open: vi.fn(),
  message: vi.fn(),
}));

vi.mock("../lib/updater", () => ({
  checkForUpdates: vi.fn(async () => undefined),
}));

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

import { _resetBaseUrl, type RefData } from "../api/client";
import ConfigPage, { flattenSections } from "./ConfigPage";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function installFetchMock() {
  fetchMock.mockImplementation((url: string) => {
    if (url.includes("/api/healthz")) {
      return Promise.resolve(
        jsonResponse({ ok: true, macs_installed: true, com: true }),
      );
    }
    if (url.includes("/api/custom-sections")) {
      return Promise.resolve(jsonResponse([]));
    }
    if (url.includes("/api/ref-data")) {
      return Promise.resolve(
        jsonResponse({
          sections: {},
          decks: {},
          meshes: {},
          defaults: {},
        }),
      );
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
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<ConfigPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  fetchMock.mockReset();
  _resetBaseUrl();
  installFetchMock();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("ConfigPage", () => {
  it("defaults the fire analysis method to parametric", async () => {
    renderPage();
    const methodSelect = await screen.findByRole("combobox", {
      name: /analysis method/i,
    });
    // The form's defaultValues seed `method: "parametric"`, and the
    // ref-data reset effect keeps it (its fallback is also parametric).
    await waitFor(() => {
      expect(methodSelect).toHaveValue("parametric");
    });
  });

  it("labels catalogue sections with their family", () => {
    const refData = {
      sections: {
        IPE: [{ id: "IPE_500", name: "IPE 500", h: 500, b: 200 }],
      },
    } as unknown as RefData;

    expect(flattenSections(refData)[0].label).toBe("IPE 500 (IPE)");
  });

  it("does not repeat a suffix the section name already carries", () => {
    // The sidecar labels custom rows "<name> (Custom)" (app.py:167) — appending
    // the family again would render "My Beam (Custom) (Custom)".
    const refData = {
      sections: {
        Custom: [{ id: "CUSTOM_1", name: "My Beam (Custom)", h: 529.1, b: 165.9 }],
      },
    } as unknown as RefData;

    const [option] = flattenSections(refData);
    expect(option.label).toBe("My Beam (Custom)");
    expect(option.id).toBe("CUSTOM_1");
    expect(option.secondary).toBe("529.1 × 165.9");
  });

  it("offers a custom-sections panel for beams outside the catalogue", async () => {
    renderPage();
    expect(
      await screen.findByRole("button", { name: /add section/i }),
    ).toBeInTheDocument();
  });
});
