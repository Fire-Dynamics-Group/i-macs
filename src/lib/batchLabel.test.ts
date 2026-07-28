import { describe, expect, it } from "vitest";

import { batchLabel, frcLabel, shortBatchId, suggestBatchName } from "./batchLabel";

describe("shortBatchId", () => {
  it("truncates to the first 8 characters", () => {
    expect(shortBatchId("0123456789abcdef0123456789abcdef")).toBe("01234567");
  });

  it("leaves already-short ids alone", () => {
    expect(shortBatchId("abc")).toBe("abc");
  });

  it("tolerates a missing id", () => {
    expect(shortBatchId(undefined)).toBe("");
  });
});

describe("batchLabel", () => {
  it("prefers the user-supplied name", () => {
    expect(batchLabel({ batch_id: "0123456789ab", name: "Span sweep" })).toBe(
      "Span sweep",
    );
  });

  it("falls back to the short id when unnamed", () => {
    expect(batchLabel({ batch_id: "0123456789ab", name: null })).toBe("01234567");
  });

  it("falls back when the name is whitespace only", () => {
    // The API normalises blanks to null, but a hand-edited DB row shouldn't
    // render an empty cell.
    expect(batchLabel({ batch_id: "0123456789ab", name: "   " })).toBe("01234567");
  });

  it("falls back when name is absent entirely (legacy batch)", () => {
    expect(batchLabel({ batch_id: "0123456789ab" })).toBe("01234567");
  });
});

describe("frcLabel", () => {
  it("uses the filename", () => {
    expect(frcLabel({ id: "h", filename: "job.frc", project: {} })).toBe("job.frc");
  });

  it("falls back to the project name when the filename is missing", () => {
    expect(
      frcLabel({ id: "h", filename: null, project: { ProjectName: "Unit 7" } }),
    ).toBe("Unit 7");
  });

  it("falls back to a generic label when nothing is known", () => {
    expect(frcLabel({ id: "h", filename: null, project: {} })).toBe(
      "imported .frc",
    );
  });

  it("returns empty for no frc", () => {
    expect(frcLabel(null)).toBe("");
  });
});

describe("suggestBatchName", () => {
  it("names the varying parameters and the run count", () => {
    expect(suggestBatchName(["qf", "span1"], 250)).toBe("qf, span1 — 250 runs");
  });

  it("singularises a one-run batch", () => {
    expect(suggestBatchName(["qf"], 1)).toBe("qf — 1 run");
  });

  it("summarises when more than three parameters vary", () => {
    expect(suggestBatchName(["a", "b", "c", "d"], 10)).toBe(
      "a, b, c +1 more — 10 runs",
    );
  });

  it("handles a sweep with nothing varying yet", () => {
    expect(suggestBatchName([], 0)).toBe("");
  });
});
