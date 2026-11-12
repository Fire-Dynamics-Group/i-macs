import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  UploadCanvasPanel,
  UPLOAD_CANVAS_NOT_AUTHORISED_MESSAGE,
  UPLOAD_CANVAS_PRODUCTION_BACKEND,
  UPLOAD_CANVAS_PRODUCTION_WEB,
  UPLOAD_CANVAS_SIGN_IN_MESSAGE,
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
    startUploadCanvasSignIn: vi.fn(),
    signOutUploadCanvas: vi.fn(),
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
  has_app_key: false,
  signed_in: true,
  account_email: "sam@firedynamicsgroup.com",
  account_name: "Sam Bennett",
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
    [401, "Missing or invalid IMACS_APP_KEY", UPLOAD_CANVAS_SIGN_IN_MESSAGE],
    [403, "IMACS_APP_KEY is rejected (wrong key)", UPLOAD_CANVAS_NOT_AUTHORISED_MESSAGE],
    [503, "i-macs access is not configured.", UPLOAD_CANVAS_SIGN_IN_MESSAGE],
  ])("shows a sign-in or auth error when project search returns %s", async (status, detail, expected) => {
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
    expect(alert).toHaveTextContent(expected);
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

  it("asks the user to sign in before creating a project", async () => {
    vi.mocked(client.getUploadCanvasSummary).mockResolvedValue({
      job_id: "batch-100",
      imacs_job_id: "imacs-uuid-1",
      summary: null,
    });
    vi.mocked(client.getUploadCanvasConfig).mockResolvedValue({
      ...PRODUCTION_CONFIG,
      signed_in: false,
      has_app_key: false,
    });

    renderPanel();
    await openChooser();

    expect(await screen.findByText(UPLOAD_CANVAS_SIGN_IN_MESSAGE)).toBeInTheDocument();
    expect(screen.queryByLabelText(/app key/i)).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue(/secret/i)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Create new project/i }));

    expect(client.createUploadCanvasHandoff).not.toHaveBeenCalled();
  });

  it("starts Microsoft sign-in from the dialog", async () => {
    vi.mocked(client.getUploadCanvasSummary).mockResolvedValue({
      job_id: "batch-100",
      imacs_job_id: "imacs-uuid-1",
      summary: null,
    });
    vi.mocked(client.getUploadCanvasConfig).mockResolvedValue({
      ...PRODUCTION_CONFIG,
      signed_in: false,
      has_app_key: false,
    });
    vi.mocked(client.startUploadCanvasSignIn).mockResolvedValue({
      auth_url:
        "https://login.microsoftonline.com/8c535dde-8170-4909-8edc-40bbff4924ba/oauth2/v2.0/authorize?client_id=2b180b8a-7cd3-40b2-83dd-8338103ce41e",
      redirect_uri: "http://127.0.0.1:47831/callback",
    });

    renderPanel();
    await openChooser();
    fireEvent.click(screen.getByRole("button", { name: /Sign in with Microsoft/i }));

    await waitFor(() => {
      expect(client.startUploadCanvasSignIn).toHaveBeenCalledTimes(1);
    });
    expect(screen.queryByLabelText(/app key/i)).not.toBeInTheDocument();
  });

  it("opens settings from the dialog with production URLs and no key field", async () => {
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
    expect(screen.queryByLabelText(/app key/i)).not.toBeInTheDocument();
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
      has_app_key: false,
      signed_in: true,
      account_email: "sam@firedynamicsgroup.com",
      account_name: "Sam Bennett",
    });

    renderPanel();
    await openChooser();
    fireEvent.click(screen.getByRole("button", { name: /settings/i }));

    expect(await screen.findByDisplayValue("https://api.example.test")).toBeInTheDocument();
    expect(screen.getByDisplayValue("https://canvas.example.test")).toBeInTheDocument();
  });

  it("saves URL overrides and does not send an app key", async () => {
    vi.mocked(client.getUploadCanvasSummary).mockResolvedValue({
      job_id: "batch-100",
      imacs_job_id: "imacs-uuid-1",
      summary: null,
    });

    renderPanel();
    await openChooser();
    fireEvent.click(screen.getByRole("button", { name: /settings/i }));
    fireEvent.click(screen.getByRole("button", { name: /save settings/i }));

    await waitFor(() => {
      expect(client.putUploadCanvasConfig).toHaveBeenCalledWith({
        backend_base_url: UPLOAD_CANVAS_PRODUCTION_BACKEND,
        upload_canvas_base_url: UPLOAD_CANVAS_PRODUCTION_WEB,
      });
    });
    expect(screen.queryByLabelText(/app key/i)).not.toBeInTheDocument();
    const sent = vi.mocked(client.putUploadCanvasConfig).mock.calls[0][0];
    expect(sent).not.toHaveProperty("imacs_app_key");
  });
});
