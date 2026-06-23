/** @jsxImportSource react */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { RunSummary } from "./RunDetailPage";
import type { Run } from "../api/client";

function makeRun(overrides: Partial<Run> = {}): Run {
  return {
    id: 1,
    uf_max: 0.42,
    duration_ms: 120,
    error: null,
    overall_pass: true,
    checks: [],
    engine_version: "2.0.0.2",
    ...overrides,
  } as Run;
}

describe("RunSummary", () => {
  it("shows which FRACOF engine version produced the run", () => {
    render(<RunSummary run={makeRun({ engine_version: "2.0.0.2" })} />);
    expect(screen.getByText(/FRACOF/i)).toBeInTheDocument();
    expect(screen.getByText(/2\.0\.0\.2/)).toBeInTheDocument();
  });

  it("falls back to a dash when the engine version is unknown", () => {
    render(<RunSummary run={makeRun({ engine_version: null })} />);
    expect(screen.getByText(/FRACOF\s*—/)).toBeInTheDocument();
  });

  it("flags when a beam's shear connection is below the EN minimum", () => {
    render(
      <RunSummary
        run={makeRun({
          shear_flags: [
            { beam: "Side A", sh_con: 50, fy: 355, span: 9, eta_min_pct: 64.3 },
          ],
        })}
      />,
    );
    expect(screen.getByText(/shear connection/i)).toBeInTheDocument();
    // surfaces the offending beam + the minimum it fell short of
    expect(screen.getByText(/Side A/)).toBeInTheDocument();
    expect(screen.getByText(/64\.3/)).toBeInTheDocument();
  });

  it("shows no shear-connection warning when nothing is flagged", () => {
    render(<RunSummary run={makeRun({ shear_flags: [] })} />);
    expect(screen.queryByText(/shear connection/i)).not.toBeInTheDocument();
  });
});
