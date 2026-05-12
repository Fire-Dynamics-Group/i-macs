/** @jsxImportSource react */
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { SweepConfigSection } from "./SweepConfigSection";

const VARYABLE = [
  { name: "qf", label: "Fire load qf (MJ/m²)", isInteger: false },
  { name: "window_percent", label: "Window opening (%)", isInteger: false },
  { name: "numbeam", label: "Number of beams", isInteger: true },
];

describe("SweepConfigSection", () => {
  it("renders one checkbox per varyable parameter", () => {
    render(
      <SweepConfigSection
        varying={{}}
        onChange={() => {}}
        varyableParams={VARYABLE}
      />,
    );
    expect(screen.getByLabelText(/Fire load qf/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Window opening/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/Number of beams/i)).toBeInTheDocument();
  });

  it("does not show value-entry inputs for params that are not selected", () => {
    render(
      <SweepConfigSection
        varying={{}}
        onChange={() => {}}
        varyableParams={VARYABLE}
      />,
    );
    expect(screen.queryByPlaceholderText(/comma-separated/i)).not.toBeInTheDocument();
  });

  it("calls onChange with the param added when its checkbox is ticked", () => {
    const onChange = vi.fn();
    render(
      <SweepConfigSection
        varying={{}}
        onChange={onChange}
        varyableParams={VARYABLE}
      />,
    );
    fireEvent.click(screen.getByLabelText(/Fire load qf/i));
    expect(onChange).toHaveBeenCalledWith({ qf: {} });
  });

  it("calls onChange with the param removed when its checkbox is unticked", () => {
    const onChange = vi.fn();
    render(
      <SweepConfigSection
        varying={{ qf: { list: [400, 500] } }}
        onChange={onChange}
        varyableParams={VARYABLE}
      />,
    );
    fireEvent.click(screen.getByLabelText(/Fire load qf/i));
    expect(onChange).toHaveBeenCalledWith({});
  });

  it("renders the list / range / CSV inputs when a param is selected", () => {
    render(
      <SweepConfigSection
        varying={{ qf: {} }}
        onChange={() => {}}
        varyableParams={VARYABLE}
      />,
    );
    expect(screen.getByPlaceholderText(/comma-separated/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/min$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/max$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/step$/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/csv/i)).toBeInTheDocument();
  });

  it("hides the CSV picker for integer-typed params", () => {
    render(
      <SweepConfigSection
        varying={{ numbeam: {} }}
        onChange={() => {}}
        varyableParams={VARYABLE}
      />,
    );
    expect(screen.getByPlaceholderText(/comma-separated/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/csv/i)).not.toBeInTheDocument();
  });

  it("emits a list source when the user types numbers into the list field", () => {
    const onChange = vi.fn();
    render(
      <SweepConfigSection
        varying={{ qf: {} }}
        onChange={onChange}
        varyableParams={VARYABLE}
      />,
    );
    fireEvent.change(screen.getByPlaceholderText(/comma-separated/i), {
      target: { value: "400, 510, 720" },
    });
    expect(onChange).toHaveBeenLastCalledWith({
      qf: { list: [400, 510, 720] },
    });
  });

  it("emits a range source when min/max/step are filled", () => {
    const onChange = vi.fn();
    render(
      <SweepConfigSection
        varying={{ qf: {} }}
        onChange={onChange}
        varyableParams={VARYABLE}
      />,
    );
    fireEvent.change(screen.getByLabelText(/min$/i), { target: { value: "100" } });
    fireEvent.change(screen.getByLabelText(/max$/i), { target: { value: "500" } });
    fireEvent.change(screen.getByLabelText(/step$/i), { target: { value: "100" } });

    const calls = onChange.mock.calls;
    const lastCall = calls[calls.length - 1]?.[0];
    expect(lastCall).toEqual({ qf: { range: { min: 100, max: 500, step: 100 } } });
  });
});
