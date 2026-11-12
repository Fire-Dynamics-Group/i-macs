import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  UploadCanvasPanel,
  UPLOAD_CANVAS_KEY_MESSAGE,
  UPLOAD_CANVAS_PRODUCTION_BACKEND,
  UPLOAD_CANVAS_PRODUCTION_WEB,
} from "./UploadCanvasPanel";
import * as client from "../api/client";

vi.mock("../api/client", async () => {
  const actual = await vi.importActual("../api/client");
  return {
    ...actual,
    getUploadCanvasSummary: vi.fn(),
    createUploadCanvasHandoff: vi.fn(),
    searchUploadCanvasProjects: vi.fn(),
    linkUploadCanvasProject: vi.fn(),
    unlinkUploadCanvasProject: vi.fn(),
    pushUploadCanvasRun: vi.fn(),
    getUploadCanvasConfig: vi.fn(),
    putUploadCanvasConfig: vi.fn(),
  };
});

// Mock window.open / opener
vi.stubGlobal("open", vi.fn());

function renderPanel(jobId = "batch-100") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <UploadCanvasPanel jobId={jobId} />
    </QueryClientProvider>,
  );
}

const PRODUCTION_CONFIG = {
  backend_base_url: UPLOAD_CANVAS_PRODUCTION_BACKEND,
  upload_canvas_base_url: UPLOAD_CANVAS_PRODUCTION_WEB,
  has_app_key: true,
};

describe("UploadCanvasPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(client.getUploadCanvasConfig).mockResolvedValue(PRODUCTION_CONFIG);
    vi.mocked(client.putUploadCanvasConfig).mockResolvedValue({ status: "saved" });
    vi.mocked(client.searchUploadCanvasProjects).mockResolvedValue({ projects: [] });
  });

  it("renders 'Open in Upload Canvas' when unlinked and opens chooser modal", async () => {
    vi.mocked(client.getUploadCanvasSummary).mockResolvedValue({
      job_id: "batch-100",
      imacs_job_id: "imacs-uuid-1",
      summary: null,
    });

    renderPanel("batch-100");

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Open in Upload Canvas/i }),
      ).toBeInTheDocument();
    });

    // Click button to open chooser modal
    fireEvent.click(
      screen.getByRole("button", { name: /Open in Upload Canvas/i }),
    );

    expect(screen.getByText(/Create new project/i)).toBeInTheDocument();
    expect(screen.getByText(/Link to existing project/i)).toBeInTheDocument();
  });

  it("handles new project handoff creation", async () => {
    vi.mocked(client.getUploadCanvasSummary).mockResolvedValue({
      job_id: "batch-100",
      imacs_job_id: "imacs-uuid-1",
      summary: null,
    });
    vi.mocked(client.createUploadCanvasHandoff).mockResolvedValue({
      handoff_id: "h-xyz",
      url: "http://localhost:3000/?handoff=h-xyz",
    });

    renderPanel("batch-100");

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Open in Upload Canvas/i }),
      ).toBeInTheDocument();
    });

    fireEvent.click(
      screen.getByRole("button", { name: /Open in Upload Canvas/i }),
    );

    const newProjBtn = screen.getByRole("button", {
      name: /Create new project/i,
    });
    fireEvent.click(newProjBtn);

    await waitFor(() => {
      expect(client.createUploadCanvasHandoff).toHaveBeenCalledWith(
        "batch-100",
      );
    });
  });

  it("shows the linked project after New project once the claim exists", async () => {
    let handoffDone = false;
    let fetchesAfterHandoff = 0;
    vi.mocked(client.getUploadCanvasSummary).mockImplementation(async () => {
      if (!handoffDone || fetchesAfterHandoff < 1) {
        if (handoffDone) fetchesAfterHandoff += 1;
        return {
          job_id: "batch-100",
          imacs_job_id: "imacs-uuid-1",
          summary: null,
        };
      }
      fetchesAfterHandoff += 1;
      return {
        job_id: "batch-100",
        imacs_job_id: "imacs-uuid-1",
        summary: {
          project_id: "42625cdb-d3bb-49ff-a0d2-9d023a866519",
          project_name: "Site Plan Time Eq",
          last_sent_at: "2026-11-10T10:19:02.000Z",
          outcome: null,
        },
      };
    });
    vi.mocked(client.createUploadCanvasHandoff).mockImplementation(async () => {
      handoffDone = true;
      return {
        handoff_id: "h-xyz",
        url: "http://localhost:3000/structural-fire?handoff=h-xyz",
      };
    });

    renderPanel("batch-100");

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /Open in Upload Canvas/i }),
      ).toBeInTheDocument();
    });

    fireEvent.click(
      screen.getByRole("button", { name: /Open in Upload Canvas/i }),
    );
    fireEvent.click(screen.getByRole("button", { name: /Create new project/i }));

    await waitFor(() => {
      expect(client.createUploadCanvasHandoff).toHaveBeenCalledWith("batch-100");
    });
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText(/failed/i)).not.toBeInTheDocument();

    await waitFor(
      () => {
        expect(screen.getByText("Site Plan Time Eq")).toBeInTheDocument();
      },
      { timeout: 2000 },
    );
    expect(screen.getByText(/No time-eq run yet/i)).toBeInTheDocument();
    expect(screen.getByText("Last Sent")).toBeInTheDocument();
    expect(screen.queryByText("Never")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Open project/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Open in Upload Canvas/i }),
    ).not.toBeInTheDocument();
  });

  it("renders linked project summary and 'Open project' button when linked", async () => {
    vi.mocked(client.getUploadCanvasSummary).mockResolvedValue({
      job_id: "batch-100",
      imacs_job_id: "imacs-uuid-1",
      summary: {
        project_id: "p-abc",
        project_name: "Birmingham Depot TEQ",
        last_sent_at: "2026-11-02T14:30:00Z",
        outcome: null,
      },
    });

    renderPanel("batch-100");

    await waitFor(() => {
      expect(screen.getByText("Birmingham Depot TEQ")).toBeInTheDocument();
      expect(screen.getByText(/No time-eq run yet/i)).toBeInTheDocument();
      expect(
        screen.getByRole("button", { name: /Open project/i }),
      ).toBeInTheDocument();
    });
  });

  it("renders formatted reliability outcome when completed", async () => {
    vi.mocked(client.getUploadCanvasSummary).mockResolvedValue({
      job_id: "batch-100",
      imacs_job_id: "imacs-uuid-1",
      summary: {
        project_id: "p-abc",
        project_name: "Birmingham Depot TEQ",
        last_sent_at: "2026-11-02T14:30:00Z",
        outcome: {
          reliabilityPercent: 98.5,
          frPeriod: 60,
        },
      },
    });

    renderPanel("batch-100");

    await waitFor(() => {
      expect(screen.getByText("98.5% reliability (FR 60 min)")).toBeInTheDocument();
    });
  });

  it.each([401, 403, 503])(
    "shows summary %s on the card instead of the unlinked button",
    async (status) => {
      vi.mocked(client.getUploadCanvasSummary).mockRejectedValue(
        new Error(
          `GET /api/imacs/jobs/batch-100/upload-canvas-summary failed: ${status} backend refused`,
        ),
      );

      renderPanel("batch-100");

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent(String(status));
      expect(
        screen.queryByRole("button", { name: /Open in Upload Canvas/i }),
      ).not.toBeInTheDocument();
    },
  );

  async function openChooser() {
    fireEvent.click(
      await screen.findByRole("button", { name: /Open in Upload Canvas/i }),
    );
  }

  it("shows a saved empty search as no projects", async () => {
    vi.mocked(client.getUploadCanvasSummary).mockResolvedValue({
      job_id: "batch-100",
      imacs_job_id: "imacs-uuid-1",
      summary: null,
    });
    vi.mocked(client.searchUploadCanvasProjects).mockResolvedValue({ projects: [] });

    renderPanel();
    await openChooser();

    expect(await screen.findByText(/No time-eq projects found/i)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("lists projects returned by search", async () => {
    vi.mocked(client.getUploadCanvasSummary).mockResolvedValue({
      job_id: "batch-100",
      imacs_job_id: "imacs-uuid-1",
      summary: null,
    });
    vi.mocked(client.searchUploadCanvasProjects).mockResolvedValue({
      projects: [{ id: "p-1", name: "Site Plan Time Eq", mode: "timeEq" }],
    });

    renderPanel();
    await openChooser();

    expect(await screen.findByText("Site Plan Time Eq")).toBeInTheDocument();
    expect(screen.queryByText(/No time-eq projects found/i)).not.toBeInTheDocument();
  });

  it.each([
    [401, "Missing or invalid IMACS_APP_KEY"],
    [403, "IMACS_APP_KEY is rejected (wrong key)"],
    [503, "i-macs access is not configured."],
  ])("shows a settings prompt when project search returns %s", async (status, detail) => {
    vi.mocked(client.getUploadCanvasSummary).mockResolvedValue({
      job_id: "batch-100",
      imacs_job_id: "imacs-uuid-1",
      summary: null,
    });
    vi.mocked(client.searchUploadCanvasProjects).mockRejectedValue(
      new Error(`GET /api/imacs/upload-canvas-projects?q= failed: ${status} ${detail}`),
    );

    renderPanel();
    await openChooser();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(UPLOAD_CANVAS_KEY_MESSAGE);
    expect(screen.queryByText(/No time-eq projects found/i)).not.toBeInTheDocument();
  });

  it("shows a not-found error for search 404 instead of an empty list", async () => {
    vi.mocked(client.getUploadCanvasSummary).mockResolvedValue({
      job_id: "batch-100",
      imacs_job_id: "imacs-uuid-1",
      summary: null,
    });
    vi.mocked(client.searchUploadCanvasProjects).mockRejectedValue(
      new Error(
        "GET /api/imacs/upload-canvas-projects?q= failed: 404 Upload Canvas resource was not found.",
      ),
    );

    renderPanel();
    await openChooser();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/not found/i);
    expect(alert).not.toHaveTextContent(/No time-eq projects found/i);
    expect(screen.queryByText(/No time-eq projects found/i)).not.toBeInTheDocument();
  });

  it("shows an unreachable error when search cannot contact the backend", async () => {
    vi.mocked(client.getUploadCanvasSummary).mockResolvedValue({
      job_id: "batch-100",
      imacs_job_id: "imacs-uuid-1",
      summary: null,
    });
    vi.mocked(client.searchUploadCanvasProjects).mockRejectedValue(
      new Error("Failed to fetch"),
    );

    renderPanel();
    await openChooser();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/unreachable/i);
    expect(screen.queryByText(/No time-eq projects found/i)).not.toBeInTheDocument();
  });

  it("asks for the app key before creating a project", async () => {
    vi.mocked(client.getUploadCanvasSummary).mockResolvedValue({
      job_id: "batch-100",
      imacs_job_id: "imacs-uuid-1",
      summary: null,
    });
    vi.mocked(client.getUploadCanvasConfig).mockResolvedValue({
      ...PRODUCTION_CONFIG,
      has_app_key: false,
    });

    renderPanel();
    await openChooser();

    expect(await screen.findByText(UPLOAD_CANVAS_KEY_MESSAGE)).toBeInTheDocument();
    const key = screen.getByLabelText(/app key/i);
    expect(key).toHaveAttribute("type", "password");
    expect(key).toHaveValue("");

    fireEvent.click(screen.getByRole("button", { name: /Create new project/i }));

    expect(client.createUploadCanvasHandoff).not.toHaveBeenCalled();
  });

  it("opens settings from the dialog with production URLs and a masked key", async () => {
    vi.mocked(client.getUploadCanvasSummary).mockResolvedValue({
      job_id: "batch-100",
      imacs_job_id: "imacs-uuid-1",
      summary: null,
    });

    renderPanel();
    await openChooser();
    fireEvent.click(screen.getByRole("button", { name: /settings/i }));

    expect(screen.getByLabelText(/backend url/i)).toHaveValue(
      UPLOAD_CANVAS_PRODUCTION_BACKEND,
    );
    expect(screen.getByLabelText(/web url/i)).toHaveValue(
      UPLOAD_CANVAS_PRODUCTION_WEB,
    );
    expect(screen.getByLabelText(/app key/i)).toHaveAttribute("type", "password");
  });

  it("keeps production URLs when config cannot be loaded", async () => {
    vi.mocked(client.getUploadCanvasSummary).mockResolvedValue({
      job_id: "batch-100",
      imacs_job_id: "imacs-uuid-1",
      summary: null,
    });
    vi.mocked(client.getUploadCanvasConfig).mockRejectedValue(new Error("offline"));

    renderPanel();
    await openChooser();
    fireEvent.click(screen.getByRole("button", { name: /settings/i }));

    expect(screen.getByLabelText(/backend url/i)).toHaveValue(
      UPLOAD_CANVAS_PRODUCTION_BACKEND,
    );
    expect(screen.getByLabelText(/web url/i)).toHaveValue(
      UPLOAD_CANVAS_PRODUCTION_WEB,
    );
  });

  it("shows a saved URL override from config", async () => {
    vi.mocked(client.getUploadCanvasSummary).mockResolvedValue({
      job_id: "batch-100",
      imacs_job_id: "imacs-uuid-1",
      summary: null,
    });
    vi.mocked(client.getUploadCanvasConfig).mockResolvedValue({
      backend_base_url: "https://api.example.test",
      upload_canvas_base_url: "https://canvas.example.test",
      has_app_key: true,
    });

    renderPanel();
    await openChooser();
    fireEvent.click(screen.getByRole("button", { name: /settings/i }));

    expect(await screen.findByDisplayValue("https://api.example.test")).toBeInTheDocument();
    expect(screen.getByDisplayValue("https://canvas.example.test")).toBeInTheDocument();
  });

  it("saves the app key without showing or logging it", async () => {
    vi.mocked(client.getUploadCanvasSummary).mockResolvedValue({
      job_id: "batch-100",
      imacs_job_id: "imacs-uuid-1",
      summary: null,
    });
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    const info = vi.spyOn(console, "info").mockImplementation(() => {});
    const debug = vi.spyOn(console, "debug").mockImplementation(() => {});

    renderPanel();
    await openChooser();
    fireEvent.click(screen.getByRole("button", { name: /settings/i }));
    fireEvent.change(screen.getByLabelText(/app key/i), {
      target: { value: "secret-key-value" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save settings/i }));

    await waitFor(() => {
      expect(client.putUploadCanvasConfig).toHaveBeenCalledWith(
        expect.objectContaining({
          imacs_app_key: "secret-key-value",
          backend_base_url: UPLOAD_CANVAS_PRODUCTION_BACKEND,
          upload_canvas_base_url: UPLOAD_CANVAS_PRODUCTION_WEB,
        }),
      );
    });
    expect(screen.getByLabelText(/app key/i)).toHaveValue("");
    expect(screen.queryByDisplayValue("secret-key-value")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("secret-key-value");
    const logged = [log, info, debug].flatMap((spy) => spy.mock.calls).flat().join(" ");
    expect(logged).not.toContain("secret-key-value");
    log.mockRestore();
    info.mockRestore();
    debug.mockRestore();
  });
});
