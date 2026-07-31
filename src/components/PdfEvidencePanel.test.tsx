/** @jsxImportSource react */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PdfEvidencePanel from "./PdfEvidencePanel";
import type { HostCheck, PdfEvidenceStatus } from "../api/client";

const getReplayHostCheck = vi.fn();
const startPdfEvidence = vi.fn();
const getPdfEvidenceStatus = vi.fn();
const stopPdfEvidence = vi.fn();
const resetPdfEvidence = vi.fn();
const revealItemInDir = vi.fn();
const openDialog = vi.fn();

vi.mock("@tauri-apps/plugin-opener", () => ({
  revealItemInDir: (...args: unknown[]) => revealItemInDir(...args),
}));

vi.mock("@tauri-apps/plugin-dialog", () => ({
  open: (...args: unknown[]) => openDialog(...args),
}));

vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  getReplayHostCheck: () => getReplayHostCheck(),
  startPdfEvidence: (...args: unknown[]) => startPdfEvidence(...args),
  getPdfEvidenceStatus: (...args: unknown[]) => getPdfEvidenceStatus(...args),
  stopPdfEvidence: (...args: unknown[]) => stopPdfEvidence(...args),
  resetPdfEvidence: (...args: unknown[]) => resetPdfEvidence(...args),
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
  sample: null,
  seed: null,
  job_dir: null,
  stopping: false,
  resumable: false,
};

const HOST_OK: HostCheck = { ok: true, lines: ["MACS+ 3.0.4 found"], error: null };

async function openPanel(runCount = 10000, seedName: string | null = "job.frc") {
  const user = userEvent.setup();
  render(
    <PdfEvidencePanel batchId="b1" runCount={runCount} seedName={seedName} />,
  );
  await user.click(screen.getByRole("button", { name: /MACS\+ PDF evidence/i }));
  return user;
}

const generateButton = () => screen.getByRole("button", { name: /generate/i });

beforeEach(() => {
  vi.clearAllMocks();
  getReplayHostCheck.mockResolvedValue(HOST_OK);
  getPdfEvidenceStatus.mockResolvedValue(IDLE);
  startPdfEvidence.mockResolvedValue({ started: true });
  stopPdfEvidence.mockResolvedValue({ stopping: true });
  resetPdfEvidence.mockResolvedValue({ reset: true, deleted: 0 });
  openDialog.mockResolvedValue(null);
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
      expect(startPdfEvidence).toHaveBeenCalledWith("b1", expect.objectContaining({ sample: undefined }));
    });

    it("sends the sample size when generating a sample", async () => {
      const user = await openPanel();
      await screen.findByText(/set up correctly/i);
      await user.click(screen.getByRole("radio", { name: /auditable sample/i }));
      await user.click(generateButton());
      expect(startPdfEvidence).toHaveBeenCalledWith("b1", expect.objectContaining({ sample: 200 }));
    });

    // A sample bigger than the batch is a typo, not a request for extra runs.
    it("clamps a sample larger than the batch to the run count", async () => {
      const user = await openPanel(50);
      await screen.findByText(/set up correctly/i);
      await user.click(screen.getByRole("radio", { name: /auditable sample/i }));
      await user.click(generateButton());
      expect(startPdfEvidence).toHaveBeenCalledWith("b1", expect.objectContaining({ sample: 50 }));
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

    // A seed mismatch lists one line per input - 30 of them on a real batch.
    // Collapsed into one paragraph it is an unreadable wall of text, and the
    // whole point of the message is that you can see which inputs disagree.
    it("keeps a multi-line refusal readable line by line", async () => {
      getPdfEvidenceStatus.mockResolvedValue({
        ...IDLE,
        error:
          "the seed .frc disagrees with the batch on 2 fixed input(s):\n" +
          "  span1: seed='8' batch=7.3\n" +
          "  deck_name: seed='TR60' batch='Multideck 60'\n\n" +
          "Those inputs would be reproduced incorrectly in every PDF.",
      });
      await openPanel();

      expect(await screen.findByText("span1: seed='8' batch=7.3")).toBeInTheDocument();
      expect(
        screen.getByText("deck_name: seed='TR60' batch='Multideck 60'"),
      ).toBeInTheDocument();
      expect(
        screen.getByText(/disagrees with the batch on 2 fixed/),
      ).toBeInTheDocument();
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

    // The PDFs are the deliverable, so the path must be reachable rather than
    // a string to retype into Explorer.
    it("opens the output folder on request", async () => {
      const dir = "C:\\Users\\x\\AppData\\Local\\i-macs\\pdf_evidence\\b1\\pdfs";
      getPdfEvidenceStatus.mockResolvedValue({
        ...IDLE, total: 6, completed: 6, output_dir: dir, finished_at: 1,
      });
      const user = await openPanel();
      await user.click(await screen.findByRole("button", { name: /open folder/i }));
      expect(revealItemInDir).toHaveBeenCalledWith(dir);
    });

    it("offers the folder while the job is still running", async () => {
      const dir = "C:\\evidence\\b1\\pdfs";
      getPdfEvidenceStatus.mockResolvedValue({
        ...IDLE, active: true, total: 200, completed: 12, output_dir: dir,
      });
      const user = await openPanel();
      await user.click(await screen.findByRole("button", { name: /open folder/i }));
      expect(revealItemInDir).toHaveBeenCalledWith(dir);
    });
  });

  describe("pause and resume", () => {
    const RUNNING = { ...IDLE, active: true, total: 200, completed: 40, sample: 200 };

    it("offers a pause while running", async () => {
      getPdfEvidenceStatus.mockResolvedValue(RUNNING);
      const user = await openPanel();
      await user.click(await screen.findByRole("button", { name: /pause/i }));
      expect(stopPdfEvidence).toHaveBeenCalledWith("b1");
    });

    // The runner holds the default printer and a live MACS+ instance, and only
    // tidies both up on its way out, so a pause is a request, not an instant.
    it("says it is finishing the current run once asked to pause", async () => {
      getPdfEvidenceStatus.mockResolvedValue({ ...RUNNING, stopping: true });
      await openPanel();
      expect(await screen.findByText(/finishing the current run/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /pausing/i })).toBeDisabled();
    });

    it("offers to resume a paused job", async () => {
      getPdfEvidenceStatus.mockResolvedValue({
        ...RUNNING, active: false, resumable: true, finished_at: 1,
      });
      const user = await openPanel();
      await user.click(await screen.findByRole("button", { name: /resume/i }));
      expect(startPdfEvidence).toHaveBeenCalled();
    });

    // Resuming with a different sample would export a different set of runs,
    // and the PDFs already on disk would no longer line up with it.
    it("resumes over the same runs as the paused job", async () => {
      getPdfEvidenceStatus.mockResolvedValue({
        ...RUNNING, active: false, resumable: true, sample: 200, finished_at: 1,
      });
      const user = await openPanel();
      await user.click(await screen.findByRole("button", { name: /resume/i }));
      expect(startPdfEvidence).toHaveBeenCalledWith("b1", expect.objectContaining({ sample: 200 }));
    });

    // Closing the app kills the runner; the sidecar rebuilds the job from disk,
    // so resuming must not make the user re-pick the folder and the seed.
    it("resumes a job this session never started, with its original settings", async () => {
      getPdfEvidenceStatus.mockResolvedValue({
        ...IDLE,
        total: 10000,
        completed: 3184,
        resumable: true,
        sample: null,
        seed: "D:\\jobs\\CaliforniaDrive.frc",
        job_dir: "E:\\evidence",
      });
      const user = await openPanel(10000, null);
      await user.click(await screen.findByRole("button", { name: /resume/i }));
      expect(startPdfEvidence).toHaveBeenCalledWith("b1", {
        sample: undefined,
        outDir: "E:\\evidence",
        seed: "D:\\jobs\\CaliforniaDrive.frc",
      });
    });

    it("shows how much is already done when paused", async () => {
      getPdfEvidenceStatus.mockResolvedValue({
        ...RUNNING, active: false, resumable: true, finished_at: 1,
      });
      await openPanel();
      expect(await screen.findByText(/40 of 200/i)).toBeInTheDocument();
    });
  });

  // Batches run before i-macs stored the seed have no .frc on record, and the
  // run rows cannot be turned back into one - project metadata and the deck
  // identifiers were never columns. So the file has to come from the user.
  describe("seed .frc", () => {
    it("uses the stored seed when the batch has one", async () => {
      const user = await openPanel(10000, "job.frc");
      await screen.findByText(/set up correctly/i);
      expect(screen.getByText(/job\.frc/)).toBeInTheDocument();
      await user.click(generateButton());
      expect(startPdfEvidence).toHaveBeenCalledWith(
        "b1",
        expect.objectContaining({ seed: undefined }),
      );
    });

    it("will not start without a seed when the batch has none", async () => {
      await openPanel(10000, null);
      await screen.findByText(/set up correctly/i);
      expect(screen.getByText(/no .frc on record/i)).toBeInTheDocument();
      expect(generateButton()).toBeDisabled();
    });

    it("starts once a seed is chosen for a batch that has none", async () => {
      openDialog.mockResolvedValue("D:\\jobs\\CaliforniaDrive.frc");
      const user = await openPanel(10000, null);
      await screen.findByText(/set up correctly/i);
      await user.click(screen.getByRole("button", { name: /choose \.frc/i }));
      expect(await screen.findByText(/CaliforniaDrive\.frc/)).toBeInTheDocument();
      await user.click(generateButton());
      expect(startPdfEvidence).toHaveBeenCalledWith(
        "b1",
        expect.objectContaining({ seed: "D:\\jobs\\CaliforniaDrive.frc" }),
      );
    });

    it("asks for .frc files in the picker", async () => {
      const user = await openPanel(10000, null);
      await screen.findByText(/set up correctly/i);
      await user.click(screen.getByRole("button", { name: /choose \.frc/i }));
      expect(openDialog).toHaveBeenCalledWith(
        expect.objectContaining({
          filters: [expect.objectContaining({ extensions: ["frc"] })],
        }),
      );
    });

    it("lets a stored seed be overridden", async () => {
      openDialog.mockResolvedValue("D:\\jobs\\Other.frc");
      const user = await openPanel(10000, "job.frc");
      await screen.findByText(/set up correctly/i);
      await user.click(screen.getByRole("button", { name: /different \.frc/i }));
      await user.click(generateButton());
      expect(startPdfEvidence).toHaveBeenCalledWith(
        "b1",
        expect.objectContaining({ seed: "D:\\jobs\\Other.frc" }),
      );
    });

    // export_batch checks the seed against the run rows and refuses on a
    // mismatch, which is how you find out you picked the wrong one of several.
    it("surfaces a seed that does not match the batch", async () => {
      getPdfEvidenceStatus.mockResolvedValue({
        ...IDLE,
        error: "seed disagrees with the batch on 23 fixed inputs: span1 9.0 vs 12.0",
      });
      await openPanel(10000, null);
      expect(await screen.findByText(/disagrees with the batch/i)).toBeInTheDocument();
    });
  });

  describe("reset", () => {
    const PAUSED = {
      ...IDLE, total: 10000, completed: 3184, resumable: true, finished_at: 1,
    };

    it("is offered alongside resume on a stopped job", async () => {
      getPdfEvidenceStatus.mockResolvedValue(PAUSED);
      await openPanel();
      expect(await screen.findByRole("button", { name: /^reset/i })).toBeInTheDocument();
    });

    it("is not offered while the job is running", async () => {
      getPdfEvidenceStatus.mockResolvedValue({ ...PAUSED, active: true });
      await openPanel();
      await screen.findByRole("button", { name: /pause/i });
      expect(screen.queryByRole("button", { name: /^reset/i })).toBeNull();
    });

    // Discarding hours of PDFs is not something a stray click should do, so
    // the first press only asks.
    it("asks before doing anything", async () => {
      getPdfEvidenceStatus.mockResolvedValue(PAUSED);
      const user = await openPanel();
      await user.click(await screen.findByRole("button", { name: /^reset/i }));
      expect(resetPdfEvidence).not.toHaveBeenCalled();
      expect(screen.getByText(/3,184 PDFs/i)).toBeInTheDocument();
    });

    it("keeps the PDFs when only forgetting the job", async () => {
      getPdfEvidenceStatus.mockResolvedValue(PAUSED);
      const user = await openPanel();
      await user.click(await screen.findByRole("button", { name: /^reset/i }));
      await user.click(screen.getByRole("button", { name: /keep the pdfs/i }));
      expect(resetPdfEvidence).toHaveBeenCalledWith("b1", false);
    });

    it("discards the PDFs only when that is chosen explicitly", async () => {
      getPdfEvidenceStatus.mockResolvedValue(PAUSED);
      const user = await openPanel();
      await user.click(await screen.findByRole("button", { name: /^reset/i }));
      await user.click(screen.getByRole("button", { name: /delete the pdfs/i }));
      expect(resetPdfEvidence).toHaveBeenCalledWith("b1", true);
    });

    it("can be backed out of", async () => {
      getPdfEvidenceStatus.mockResolvedValue(PAUSED);
      const user = await openPanel();
      await user.click(await screen.findByRole("button", { name: /^reset/i }));
      await user.click(screen.getByRole("button", { name: /cancel/i }));
      expect(resetPdfEvidence).not.toHaveBeenCalled();
      expect(screen.getByRole("button", { name: /resume/i })).toBeInTheDocument();
    });

    it("is offered on a finished job so the batch can be redone", async () => {
      getPdfEvidenceStatus.mockResolvedValue({
        ...IDLE, total: 6, completed: 6, output_dir: "C:\\x", finished_at: 1,
      });
      await openPanel();
      expect(await screen.findByRole("button", { name: /^reset/i })).toBeInTheDocument();
    });
  });

  // Someone reads this before committing a machine for the night, so it should
  // not flatter itself. Printing without the dialog measured a 3.55 s median
  // over 120 consecutive runs (4.14 s mean, including one 81 s stall), against
  // 5.1 s for the old dialog route; PDFs average 442 KB.
  describe("estimate", () => {
    it("is in the right ballpark for a full 10k batch", async () => {
      await openPanel(10000);
      const text = (await screen.findByText(/GB/)).textContent ?? "";
      const hours = Number(/([\d.]+) h/.exec(text)?.[1]);
      expect(hours).toBeGreaterThan(9);
      expect(hours).toBeLessThan(12);
      const gb = Number(/~([\d.]+) GB/.exec(text)?.[1]);
      expect(gb).toBeGreaterThan(4);
      expect(gb).toBeLessThan(5);
    });
  });

  describe("output folder", () => {
    it("saves to the default location when none is chosen", async () => {
      const user = await openPanel();
      await screen.findByText(/set up correctly/i);
      await user.click(generateButton());
      expect(startPdfEvidence).toHaveBeenCalledWith("b1", expect.objectContaining({ sample: undefined }));
    });

    it("sends a chosen folder", async () => {
      openDialog.mockResolvedValue("D:\\Evidence");
      const user = await openPanel();
      await screen.findByText(/set up correctly/i);
      await user.click(screen.getByRole("button", { name: /choose folder/i }));
      expect(await screen.findByText(/D:\\Evidence/)).toBeInTheDocument();
      await user.click(generateButton());
      expect(startPdfEvidence).toHaveBeenCalledWith(
        "b1",
        expect.objectContaining({ outDir: "D:\\Evidence" }),
      );
    });

    it("keeps the default when the picker is dismissed", async () => {
      openDialog.mockResolvedValue(null);
      const user = await openPanel();
      await screen.findByText(/set up correctly/i);
      await user.click(screen.getByRole("button", { name: /choose folder/i }));
      await user.click(generateButton());
      expect(startPdfEvidence).toHaveBeenCalledWith("b1", expect.objectContaining({ sample: undefined }));
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
