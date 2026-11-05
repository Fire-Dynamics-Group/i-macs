/** @jsxImportSource react */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { GoverningCriticalTempCard } from "./GoverningCriticalTempCard";
import type { Run } from "../api/client";

function makeRun(overrides: Partial<Run> = {}): Run {
  return {
    id: 1,
    uf_max: 0.42,
    duration_ms: 120,
    error: null,
    overall_pass: true,
    checks: [],
    side_a_critical_temp: 706.4,
    side_b_critical_temp: 728.1,
    side_c_critical_temp: 650.2,
    side_d_critical_temp: 728.1,
    ...overrides,
  } as Run;
}

describe("GoverningCriticalTempCard", () => {
  it("shows the governing critical temperature and which side governs", () => {
    render(<GoverningCriticalTempCard run={makeRun()} />);
    expect(screen.getByText("650 °C")).toBeInTheDocument();
    expect(screen.getByText(/side c governs/i)).toBeInTheDocument();
  });

  it("copies the bare number to the clipboard and confirms", async () => {
    // userEvent.setup() installs a working clipboard stub over jsdom's
    // missing one — assert through it rather than mocking writeText.
    const user = userEvent.setup();
    render(<GoverningCriticalTempCard run={makeRun()} />);

    await user.click(screen.getByRole("button", { name: /copy/i }));

    expect(await navigator.clipboard.readText()).toBe("650");
    expect(await screen.findByText(/copied/i)).toBeInTheDocument();
  });

  it("says what the value is for", () => {
    render(<GoverningCriticalTempCard run={makeRun()} />);
    expect(screen.getByText(/reliability/i)).toBeInTheDocument();
  });

  it("renders nothing when the run has no perimeter-beam outputs", () => {
    const { container } = render(
      <GoverningCriticalTempCard
        run={makeRun({
          side_a_critical_temp: null,
          side_b_critical_temp: null,
          side_c_critical_temp: null,
          side_d_critical_temp: null,
        })}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing for an errored run", () => {
    const { container } = render(
      <GoverningCriticalTempCard run={makeRun({ error: "COMError: boom" })} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
