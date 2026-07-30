/** @jsxImportSource react */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PdfEvidencePanel from "./PdfEvidencePanel";
import type { HostCheck, PdfEvidenceStatus } from "../api/client";

const getReplayHostCheck = vi.fn();
const startPdfEvidence = vi.fn();
const getPdfEvidenceStatus = vi.fn();

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  getReplayHostCheck: () => getReplayHostCheck(),
  startPdfEvidence: (...args: unknown[]) => startPdfEvidence(...args),
  getPdfEvidenceStatus: (...args: unknown[]) => getPdfEvidenceStatus(...args),
}));

const IDLE: PdfEvidenceStatus = {
  active: false,
  batch_id: null,
  total: 0,
  completed: 0,
  output_dir: null,
  error: null,
  elapsed_s: 0,
  eta_s: null,
  finished_at: null,
};

const HOST_OK: HostCheck = { ok: true, lines: ["MACS+ 3.0.4 found"], error: null };

async function openPanel(runCount = 10000) {
  const user = userEvent.setup();
  render(<PdfEvidencePanel batchId="b1" runCount={runCount} />);
  await user.click(screen.getByRole("button", { name: /MACS\+ PDF evidence/i }));
  return user;
}

const generateButton = () => screen.getByRole("button", { name: /generate/i });

beforeEach(() => {
  vi.clearAllMocks();
  getReplayHostCheck.mockResolvedValue(HOST_OK);
  getPdfEvidenceStatus.mockResolvedValue(IDLE);
  startPdfEvidence.mockResolvedValue({ started: true });
});

describe("PdfEvidencePanel", () => {
  it("stays collapsed until asked, then reports the host is ready", async () => {
    await openPanel();
    expect(await screen.findByText(/set up correctly/i)).toBeInTheDocument();
  });

  describe("scope", () => {
    it("sends no sample when generating for the whole batch", async () => {
      const user = await openPanel();
      await screen.findByText(/set up correctly/i);
      await user.click(generateButton());
      expect(startPdfEvidence).toHaveBeenCalledWith("b1", undefined);
    });

    it("sends the sample size when generating a sample", async () => {
      const user = await openPanel();
      await screen.findByText(/set up correctly/i);
      await user.click(screen.getByRole("radio", { name: /auditable sample/i }));
      await user.click(generateButton());
      expect(startPdfEvidence).toHaveBeenCalledWith("b1", 200);
    });

    // A sample bigger than the batch is a typo, not a request for extra runs.
    it("clamps a sample larger than the batch to the run count", async () => {
      const user = await openPanel(50);
      await screen.findByText(/set up correctly/i);
      await user.click(screen.getByRole("radio", { name: /auditable sample/i }));
      await user.click(generateButton());
      expect(startPdfEvidence).toHaveBeenCalledWith("b1", 50);
    });

    // Regression: an empty box read as 0, which the backend treats as falsy and
    // so as "all runs" - one keystroke silently turning a 200-run sample into
    // an 11-hour job over 10,000.
    it("refuses to start when the sample box has been cleared", async () => {
      const user = await openPanel();
      await screen.findByText(/set up correctly/i);
      await user.click(screen.getByRole("radio", { name: /auditable sample/i }));
      await user.clear(screen.getByRole("spinbutton"));
      expect(generateButton()).toBeDisabled();
      expect(startPdfEvidence).not.toHaveBeenCalled();
    });
  });

  describe("host readiness", () => {
    it("blocks generation and explains why when the host is not ready", async () => {
      getReplayHostCheck.mockResolvedValue({
        ok: false,
        lines: ["FAIL  display scaling is 125% (must be 100%)"],
        error: null,
      });
      await openPanel();
      expect(await screen.findByText(/not ready/i)).toBeInTheDocument();
      expect(screen.getByText(/display scaling/i)).toBeInTheDocument();
      expect(generateButton()).toBeDisabled();
    });

    // An unanswered host check is not a passing one: the scaling trap yields
    // correct numbers with silently squashed charts, so "unknown" must not
    // read as "fine".
    it("blocks generation when the host check itself fails", async () => {
      getReplayHostCheck.mockRejectedValue(new Error("sidecar unreachable"));
      await openPanel();
      expect(await screen.findByText(/sidecar unreachable/i)).toBeInTheDocument();
      expect(generateButton()).toBeDisabled();
    });

    it("blocks generation while the host check is still in flight", async () => {
      getReplayHostCheck.mockReturnValue(new Promise(() => {}));
      await openPanel();
      expect(generateButton()).toBeDisabled();
    });
  });

  describe("progress", () => {
    it("shows counts and remaining time while running", async () => {
      getPdfEvidenceStatus.mockResolvedValue({
        ...IDLE,
        active: true,
        total: 200,
        completed: 50,
        eta_s: 675,
      });
      await openPanel();
      expect(await screen.findByText(/50 of 200 PDFs/i)).toBeInTheDocument();
      expect(screen.getByText(/11 min remaining/i)).toBeInTheDocument();
    });

    it("surfaces a backend refusal verbatim", async () => {
      getPdfEvidenceStatus.mockResolvedValue({
        ...IDLE,
        error: "batch b1 has no frc_import_id, so its seed .frc is unknown.",
      });
      await openPanel();
      expect(await screen.findByText(/no frc_import_id/i)).toBeInTheDocument();
    });

    it("points at the output directory once finished", async () => {
      getPdfEvidenceStatus.mockResolvedValue({
        ...IDLE,
        total: 6,
        completed: 6,
        output_dir: "C:\\Users\\x\\AppData\\Local\\i-macs\\pdf_evidence\\b1\\pdfs",
        finished_at: 1,
      });
      await openPanel();
      expect(await screen.findByText(/6 PDFs in/i)).toBeInTheDocument();
    });
  });

  it("stops polling once the job is no longer active", async () => {
    getPdfEvidenceStatus.mockResolvedValue(IDLE);
    await openPanel();
    await waitFor(() => expect(getPdfEvidenceStatus).toHaveBeenCalled());
    const calls = getPdfEvidenceStatus.mock.calls.length;
    await new Promise((r) => setTimeout(r, 3200));
    expect(getPdfEvidenceStatus.mock.calls.length).toBe(calls);
  });
});
