/** @jsxImportSource react */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
import { CustomSectionsPanel } from "./CustomSectionsPanel";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Rows the GET endpoint returns; mutate between renders to vary the fixture. */
let stored: Array<Record<string, unknown>> = [];

function installFetchMock() {
  fetchMock.mockImplementation((url: string, init?: RequestInit) => {
    if (url.includes("/api/custom-sections")) {
      const method = init?.method ?? "GET";
      if (method === "GET") return Promise.resolve(jsonResponse(stored));
      if (method === "POST") {
        const body = JSON.parse(String(init?.body));
        return Promise.resolve(jsonResponse({ id: "CUSTOM_9", ...body }));
      }
      if (method === "DELETE") return Promise.resolve(jsonResponse({ ok: true }));
    }
    return Promise.resolve(jsonResponse({ detail: "not mocked" }, 404));
  });
}

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const invalidateSpy = vi.spyOn(client, "invalidateQueries");
  const utils = render(
    <QueryClientProvider client={client}>
      <CustomSectionsPanel />
    </QueryClientProvider>,
  );
  return { ...utils, client, invalidateSpy };
}

/** Fill the add-section form. Omitted fields are left untouched. */
async function fillForm(
  user: ReturnType<typeof userEvent.setup>,
  values: Partial<Record<"name" | "h" | "b" | "tw" | "tf", string>>,
) {
  const labels = {
    name: /name/i,
    h: /depth/i,
    b: /width/i,
    tw: /web thickness/i,
    tf: /flange thickness/i,
  } as const;
  for (const [field, value] of Object.entries(values)) {
    const input = screen.getByLabelText(labels[field as keyof typeof labels]);
    await user.clear(input);
    if (value) await user.type(input, value);
  }
}

const VALID = { name: "UB 533x165x74", h: "529.1", b: "165.9", tw: "9.7", tf: "13.6" };

beforeEach(() => {
  stored = [];
  fetchMock.mockReset();
  _resetBaseUrl();
  installFetchMock();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("CustomSectionsPanel", () => {
  it("lists the custom sections already stored on this device", async () => {
    stored = [
      { id: "CUSTOM_1", name: "Plate girder", h: 900, b: 300, tw: 12, tf: 25 },
      { id: "CUSTOM_2", name: "Stub beam", h: 300, b: 150, tw: 6, tf: 10 },
    ];
    renderPanel();

    expect(await screen.findByText("Plate girder")).toBeInTheDocument();
    expect(screen.getByText("Stub beam")).toBeInTheDocument();
  });

  it("shows each section's dimensions so they can be checked at a glance", async () => {
    stored = [
      { id: "CUSTOM_1", name: "Plate girder", h: 900, b: 300, tw: 12, tf: 25 },
    ];
    renderPanel();

    const row = await screen.findByRole("listitem");
    expect(within(row).getByText(/900/)).toBeInTheDocument();
    expect(within(row).getByText(/300/)).toBeInTheDocument();
    expect(within(row).getByText(/12/)).toBeInTheDocument();
    expect(within(row).getByText(/25/)).toBeInTheDocument();
  });

  it("tells the user when none are defined yet", async () => {
    renderPanel();
    expect(await screen.findByText(/no custom sections/i)).toBeInTheDocument();
  });

  it("POSTs the entered dimensions when the form is submitted", async () => {
    const user = userEvent.setup();
    renderPanel();
    await screen.findByText(/no custom sections/i);

    await fillForm(user, VALID);
    await user.click(screen.getByRole("button", { name: /add section/i }));

    await waitFor(() => {
      const post = fetchMock.mock.calls.find(
        ([, init]) => init?.method === "POST",
      );
      expect(post).toBeDefined();
      expect(JSON.parse(String(post![1].body))).toEqual({
        name: "UB 533x165x74",
        h: 529.1,
        b: 165.9,
        tw: 9.7,
        tf: 13.6,
      });
    });
  });

  it("refreshes the section catalogue so the new section reaches the dropdown", async () => {
    const user = userEvent.setup();
    const { invalidateSpy } = renderPanel();
    await screen.findByText(/no custom sections/i);

    await fillForm(user, VALID);
    await user.click(screen.getByRole("button", { name: /add section/i }));

    // ConfigPage's section dropdown is fed by the ["ref-data"] query — without
    // invalidating it the new section stays invisible until a page reload.
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ["ref-data"] });
    });
  });

  it("clears the form after a successful add", async () => {
    const user = userEvent.setup();
    renderPanel();
    await screen.findByText(/no custom sections/i);

    await fillForm(user, VALID);
    await user.click(screen.getByRole("button", { name: /add section/i }));

    await waitFor(() => {
      expect(screen.getByLabelText(/name/i)).toHaveValue("");
    });
  });

  it("rejects a blank name without calling the API", async () => {
    const user = userEvent.setup();
    renderPanel();
    await screen.findByText(/no custom sections/i);

    await fillForm(user, { ...VALID, name: "" });
    await user.click(screen.getByRole("button", { name: /add section/i }));

    expect(await screen.findByText(/name is required/i)).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(([, init]) => init?.method === "POST"),
    ).toHaveLength(0);
  });

  it("rejects a non-positive dimension without calling the API", async () => {
    const user = userEvent.setup();
    renderPanel();
    await screen.findByText(/no custom sections/i);

    await fillForm(user, { ...VALID, tw: "0" });
    await user.click(screen.getByRole("button", { name: /add section/i }));

    expect(
      await screen.findByText(/must be greater than zero/i),
    ).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(([, init]) => init?.method === "POST"),
    ).toHaveLength(0);
  });

  it("DELETEs the section when its remove button is used", async () => {
    stored = [
      { id: "CUSTOM_1", name: "Plate girder", h: 900, b: 300, tw: 12, tf: 25 },
    ];
    const user = userEvent.setup();
    renderPanel();
    await screen.findByText("Plate girder");

    await user.click(screen.getByRole("button", { name: /delete plate girder/i }));

    await waitFor(() => {
      const del = fetchMock.mock.calls.find(
        ([, init]) => init?.method === "DELETE",
      );
      expect(del).toBeDefined();
      expect(del![0]).toContain("/api/custom-sections/CUSTOM_1");
    });
  });

  it("surfaces a failed add instead of silently swallowing it", async () => {
    fetchMock.mockImplementation((url: string, init?: RequestInit) => {
      if (url.includes("/api/custom-sections")) {
        if ((init?.method ?? "GET") === "GET") {
          return Promise.resolve(jsonResponse([]));
        }
        return Promise.resolve(
          jsonResponse({ detail: "database is locked" }, 500),
        );
      }
      return Promise.resolve(jsonResponse({ detail: "not mocked" }, 404));
    });

    const user = userEvent.setup();
    renderPanel();
    await screen.findByText(/no custom sections/i);

    await fillForm(user, VALID);
    await user.click(screen.getByRole("button", { name: /add section/i }));

    expect(await screen.findByText(/database is locked/i)).toBeInTheDocument();
  });
});
