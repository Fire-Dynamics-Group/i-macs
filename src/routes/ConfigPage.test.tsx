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

  // sh_con is a percentage (engine.py divides by 100), not a length — the old
  // label said "spacing (mm)" and the field accepted any number.
  it("constrains every shear-connection input to 0-100%", async () => {
    renderPage();
    const inputs = await screen.findAllByRole("spinbutton", {
      name: /shear connection \(%\)/i,
    });
    // Centre (unprotected) beam plus perimeter sides A-D.
    expect(inputs).toHaveLength(5);
    for (const input of inputs) {
      expect(input).toHaveAttribute("min", "0");
      expect(input).toHaveAttribute("max", "100");
    }
  });

  // The HTML min/max attributes alone don't block submission — the resolver has
  // to reject it, or a 150% run reaches the engine as eta = 1.5.
  it("blocks submission when shear connection is outside 0-100%", async () => {
    const user = userEvent.setup();
    renderPage();
    const [centre] = await screen.findAllByRole("spinbutton", {
      name: /shear connection \(%\)/i,
    });
    // The ref-data effect reset()s the form; type after it lands or the
    // seeded 80 overwrites what we type.
    await waitFor(() => expect(centre).toHaveValue(80));

    await user.clear(centre);
    await user.type(centre, "150");
    await user.click(screen.getByRole("button", { name: /submit calculation/i }));

    expect(
      await screen.findByText(/must be between 0 and 100/i),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.some((c) => String(c[0]).includes("/api/run")),
    ).toBe(false);
  });

  it("explains the degree of shear connection behind an info icon", async () => {
    const user = userEvent.setup();
    renderPage();
    const icons = await screen.findAllByRole("button", {
      name: /about shear connection/i,
    });
    expect(icons).toHaveLength(5);

    await user.click(icons[0]);
    const tip = await screen.findByRole("tooltip");
    expect(tip).toHaveTextContent(/full composite action/i);
    expect(tip).toHaveTextContent(/EN 1994-1-1/i);
    // The minimum MACS+ checks against (shear_check.py:52).
    expect(tip).toHaveTextContent(/1 − \(355 \/ f/i);
  });
});

describe("ConfigPage — naming and .frc provenance", () => {
  /** Body of the most recent POST to `path`. */
  function lastPostBody(path: string): Record<string, unknown> {
    const call = [...fetchMock.mock.calls]
      .reverse()
      .find(([url, init]) => String(url).includes(path) && init?.method === "POST");
    if (!call) throw new Error(`no POST to ${path}`);
    return JSON.parse(call[1].body as string);
  }

  it("offers project and run name inputs", async () => {
    renderPage();
    expect(await screen.findByTestId("project-name-input")).toBeInTheDocument();
    expect(screen.getByTestId("batch-name-input")).toBeInTheDocument();
  });

  it("suggests previously-used project names", async () => {
    fetchMock.mockImplementation((url: string) => {
      if (url.includes("/api/projects")) {
        return Promise.resolve(
          jsonResponse({ projects: ["Atlantic Park Unit 7", "Ark Royal"] }),
        );
      }
      if (url.includes("/api/healthz")) {
        return Promise.resolve(
          jsonResponse({ ok: true, macs_installed: true, com: true }),
        );
      }
      if (url.includes("/api/custom-sections")) return Promise.resolve(jsonResponse([]));
      if (url.includes("/api/ref-data")) {
        return Promise.resolve(
          jsonResponse({ sections: {}, decks: {}, meshes: {}, defaults: {} }),
        );
      }
      return Promise.resolve(jsonResponse({ detail: "not mocked" }, 404));
    });
    renderPage();
    await waitFor(() =>
      expect(
        document.querySelector('option[value="Atlantic Park Unit 7"]'),
      ).toBeInTheDocument(),
    );
  });

  it("sends the typed labels as meta on a single run", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (String(url).includes("/api/runs") && init?.method === "POST") {
        return Promise.resolve(
          jsonResponse({ id: 7, uf_max: 0.5, overall_pass: true, checks: [] }),
        );
      }
      if (String(url).includes("/api/healthz")) {
        return Promise.resolve(
          jsonResponse({ ok: true, macs_installed: true, com: true }),
        );
      }
      if (String(url).includes("/api/custom-sections")) {
        return Promise.resolve(jsonResponse([]));
      }
      if (String(url).includes("/api/ref-data")) {
        return Promise.resolve(
          jsonResponse({ sections: {}, decks: {}, meshes: {}, defaults: {} }),
        );
      }
      return Promise.resolve(jsonResponse({ projects: [] }));
    });
    renderPage();

    await user.type(
      await screen.findByTestId("project-name-input"),
      "Atlantic Park Unit 7",
    );
    await user.type(screen.getByTestId("batch-name-input"), "  Plant deck  ");
    await user.click(screen.getByRole("button", { name: /submit calculation/i }));

    await waitFor(() => {
      const body = lastPostBody("/api/runs");
      expect(body.meta).toEqual({
        name: "Plant deck",
        project_name: "Atlantic Park Unit 7",
      });
    });
  });

  it("omits meta entirely when nothing is named", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (String(url).includes("/api/runs") && init?.method === "POST") {
        return Promise.resolve(
          jsonResponse({ id: 7, uf_max: 0.5, overall_pass: true, checks: [] }),
        );
      }
      if (String(url).includes("/api/healthz")) {
        return Promise.resolve(
          jsonResponse({ ok: true, macs_installed: true, com: true }),
        );
      }
      if (String(url).includes("/api/custom-sections")) {
        return Promise.resolve(jsonResponse([]));
      }
      if (String(url).includes("/api/ref-data")) {
        return Promise.resolve(
          jsonResponse({ sections: {}, decks: {}, meshes: {}, defaults: {} }),
        );
      }
      return Promise.resolve(jsonResponse({ projects: [] }));
    });
    renderPage();

    await user.click(await screen.findByRole("button", { name: /submit calculation/i }));
    await waitFor(() => expect(lastPostBody("/api/runs").meta).toBeUndefined());
  });

  it("adopts the .frc's project name and links the run to the stored file", async () => {
    const user = userEvent.setup();
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (String(url).includes("/api/import-frc")) {
        return Promise.resolve(
          jsonResponse({
            params: { span1: 10.5 },
            project: { ProjectName: "Atlantic Park Unit 7" },
            frc_import_id: "sha256hash",
            frc_filename: "unit7.frc",
          }),
        );
      }
      if (String(url).includes("/api/runs") && init?.method === "POST") {
        return Promise.resolve(
          jsonResponse({ id: 7, uf_max: 0.5, overall_pass: true, checks: [] }),
        );
      }
      if (String(url).includes("/api/healthz")) {
        return Promise.resolve(
          jsonResponse({ ok: true, macs_installed: true, com: true }),
        );
      }
      if (String(url).includes("/api/custom-sections")) {
        return Promise.resolve(jsonResponse([]));
      }
      if (String(url).includes("/api/ref-data")) {
        return Promise.resolve(
          jsonResponse({ sections: {}, decks: {}, meshes: {}, defaults: {} }),
        );
      }
      return Promise.resolve(jsonResponse({ projects: [] }));
    });
    renderPage();

    const input = (await screen.findByTestId("frc-file-input")) as HTMLInputElement;
    await user.upload(
      input,
      new File(["<Root/>"], "unit7.frc", { type: "text/xml" }),
    );

    await waitFor(() =>
      expect(screen.getByTestId("project-name-input")).toHaveValue(
        "Atlantic Park Unit 7",
      ),
    );
    expect(screen.getByTestId("frc-provenance-note")).toHaveTextContent(
      "unit7.frc",
    );

    await user.click(screen.getByRole("button", { name: /submit calculation/i }));
    await waitFor(() =>
      expect(lastPostBody("/api/runs").meta).toEqual({
        project_name: "Atlantic Park Unit 7",
        frc_import_id: "sha256hash",
      }),
    );
  });
});
