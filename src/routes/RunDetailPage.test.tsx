/** @jsxImportSource react */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { RunSummary, TimeSeriesTable } from "./RunDetailPage";
import type { Run, TimeSeriesRow } from "../api/client";

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

function makeTimeSeriesRow(overrides: Partial<TimeSeriesRow> = {}): TimeSeriesRow {
  return {
    time_step: 1,
    time_min: 4,
    fire_temp: 349,
    lofl_temp: 43,
    mesh_temp: 20,
    slabtop_temp: 20,
    slabbot_temp: 63,
    beam_hot_capacity: 20.07,
    deflection: 270,
    slab_yield: 1.01,
    enhancement: 2.64,
    slab_cap: 2.67,
    total_plate_capacity: 22.74,
    utilization_factor: 0.24,
    ...overrides,
  } as TimeSeriesRow;
}

describe("TimeSeriesTable", () => {
  it("shows only the summary columns by default", () => {
    render(<TimeSeriesTable rows={[makeTimeSeriesRow()]} />);
    expect(screen.getByText("Time (min)")).toBeInTheDocument();
    expect(screen.getByText("Fire temp (°C)")).toBeInTheDocument();
    expect(screen.queryByText(/Slab yield/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Enhancement/i)).not.toBeInTheDocument();
  });

  it("reveals every MACS report column once expanded", async () => {
    const user = userEvent.setup();
    render(<TimeSeriesTable rows={[makeTimeSeriesRow()]} />);

    await user.click(screen.getByRole("button", { name: /show all columns/i }));

    for (const header of [
      "Beam (°C)",
      "Mesh (°C)",
      "Slab top (°C)",
      "Slab bottom (°C)",
      "Beam capacity (kN/m²)",
      "Maximum allowable deflection (mm)",
      "Slab yield (kN/m²)",
      "Enhancement",
      "Slab capacity (kN/m²)",
      "Total capacity (kN/m²)",
      "Unity factor",
    ]) {
      expect(screen.getByText(header)).toBeInTheDocument();
    }
    // spot-check a couple of formatted values from the expanded columns
    expect(screen.getByText("43")).toBeInTheDocument(); // Beam temp (lofl_temp)
    expect(screen.getByText("1.01")).toBeInTheDocument(); // Slab yield
  });

  it("collapses back to the summary columns when toggled again", async () => {
    const user = userEvent.setup();
    render(<TimeSeriesTable rows={[makeTimeSeriesRow()]} />);

    await user.click(screen.getByRole("button", { name: /show all columns/i }));
    await user.click(screen.getByRole("button", { name: /show fewer columns/i }));

    expect(screen.queryByText(/Slab yield/i)).not.toBeInTheDocument();
  });
});
