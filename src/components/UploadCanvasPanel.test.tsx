import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { UploadCanvasPanel } from "./UploadCanvasPanel";
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

describe("UploadCanvasPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
});
