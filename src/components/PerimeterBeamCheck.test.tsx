/** @jsxImportSource react */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { PerimeterBeamCheck } from "./PerimeterBeamCheck";
import type { Run } from "../api/client";

// Real values from a MACS+-generated PDF (Atlantic Park Unit 7 corpus,
// run00000): Side A/C share Mb2_Reqd_1 + span1, Side B/D share Mb1_Reqd_1 +
// span2 — confirmed against MACS+'s own PrintP.js (FillPerim1Beam).
function makeRun(overrides: Partial<Run> = {}): Run {
  return {
    id: 1,
    uf_max: 0.42,
    duration_ms: 120,
    error: null,
    overall_pass: true,
    checks: [],
    span1: 7.3,
    span2: 7.48,
    mb1_reqd: 167.61,
    mb2_reqd: 105.06,
    side_a_sec: "UB 457x191x67",
    side_a_composite: 1,
    side_a_edge: 0,
    side_a_sh_con: 80,
    side_a_load_ratio: 0.25,
    side_a_critical_temp: 706,
    side_b_sec: "UB 457x191x74",
    side_b_composite: 1,
    side_b_edge: 1,
    side_b_sh_con: 80,
    side_b_load_ratio: 0.23,
    side_b_critical_temp: 728,
    side_c_sec: "UB 457x191x67",
    side_c_composite: 1,
    side_c_edge: 0,
    side_c_sh_con: 80,
    side_c_load_ratio: 0.25,
    side_c_critical_temp: 706,
    side_d_sec: "UB 457x191x74",
    side_d_composite: 1,
    side_d_edge: 1,
    side_d_sh_con: 80,
    side_d_load_ratio: 0.23,
    side_d_critical_temp: 728,
    ...overrides,
  } as Run;
}

describe("PerimeterBeamCheck", () => {
  it("shows the section, shear connection, degree of utilization and critical temp per side", () => {
    render(<PerimeterBeamCheck run={makeRun()} />);
    expect(screen.getAllByText("UB 457x191x67").length).toBeGreaterThan(0);
    expect(screen.getAllByText("80 %").length).toBeGreaterThan(0);
    expect(screen.getAllByText("0.25").length).toBeGreaterThan(0);
    expect(screen.getAllByText("706 °C").length).toBeGreaterThan(0);
  });

  it("derives Side A/C's moment resistance and line load from Mb2_Reqd_1 + span1", () => {
    render(<PerimeterBeamCheck run={makeRun()} />);
    // Required moment resistance is read straight off mb2_reqd (shared by A + C).
    expect(screen.getAllByText("105.06 kNm")).toHaveLength(2);
    // Line load = 8 * Mreqd / span^2 = 8 * 105.06 / 7.3^2 = 15.77 kN/m.
    expect(screen.getAllByText("15.77 kN/m")).toHaveLength(2);
  });

  it("derives Side B/D's moment resistance and line load from Mb1_Reqd_1 + span2", () => {
    render(<PerimeterBeamCheck run={makeRun()} />);
    expect(screen.getAllByText("167.61 kNm")).toHaveLength(2);
    // 8 * 167.61 / 7.48^2 = 23.97 kN/m
    expect(screen.getAllByText("23.97 kN/m")).toHaveLength(2);
  });

  it("labels beam type from the composite/edge flags", () => {
    render(<PerimeterBeamCheck run={makeRun()} />);
    expect(screen.getAllByText("Composite").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Internal beam").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Edge beam").length).toBeGreaterThan(0);
  });

  it("skips a side with no section configured", () => {
    render(
      <PerimeterBeamCheck run={makeRun({ side_a_sec: null, side_a_composite: null })} />,
    );
    expect(screen.queryByText("Side A")).not.toBeInTheDocument();
    expect(screen.getByText("Side B")).toBeInTheDocument();
  });

  it("returns null when no sides have section data", () => {
    const { container } = render(
      <PerimeterBeamCheck
        run={makeRun({
          side_a_sec: null,
          side_b_sec: null,
          side_c_sec: null,
          side_d_sec: null,
        })}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
