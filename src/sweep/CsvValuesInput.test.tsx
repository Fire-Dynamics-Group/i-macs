/** @jsxImportSource react */
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

import { CsvValuesInput } from "./CsvValuesInput";

function makeFile(text: string, name = "values.csv"): File {
  return new File([text], name, { type: "text/csv" });
}

describe("CsvValuesInput", () => {
  it("renders a file picker with no loaded state initially", () => {
    render(<CsvValuesInput onChange={() => {}} />);
    expect(screen.getByLabelText(/csv/i)).toBeInTheDocument();
    expect(screen.queryByText(/values/i)).not.toBeInTheDocument();
  });

  it("parses a single-column CSV and reports the count + min–max range", async () => {
    const onChange = vi.fn();
    render(<CsvValuesInput onChange={onChange} />);

    const input = screen.getByLabelText(/csv/i) as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [makeFile("10\n20\n30\n40\n95")] },
    });

    await waitFor(() => expect(onChange).toHaveBeenCalled());
    expect(onChange).toHaveBeenLastCalledWith([10, 20, 30, 40, 95]);
    expect(screen.getByText(/5 values/i)).toBeInTheDocument();
    expect(screen.getByText(/10/)).toBeInTheDocument();
    expect(screen.getByText(/95/)).toBeInTheDocument();
  });

  it("shows the bad token inline when the CSV has a non-numeric value", async () => {
    const onChange = vi.fn();
    render(<CsvValuesInput onChange={onChange} />);

    const input = screen.getByLabelText(/csv/i) as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [makeFile("10\n20\noops\n40")] },
    });

    await waitFor(() => expect(screen.getByText(/oops/)).toBeInTheDocument());
    // No values reported on parse failure.
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("rejects multi-column rows (commas inside a row)", async () => {
    const onChange = vi.fn();
    render(<CsvValuesInput onChange={onChange} />);

    const input = screen.getByLabelText(/csv/i) as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [makeFile("10\n20, 30\n40")] },
    });

    await waitFor(() =>
      expect(screen.getByText(/row 2.*one numeric value/i)).toBeInTheDocument(),
    );
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("clears the loaded state when the user re-uploads a malformed file", async () => {
    const onChange = vi.fn();
    render(<CsvValuesInput onChange={onChange} />);

    const input = screen.getByLabelText(/csv/i) as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [makeFile("1\n2\n3")] },
    });
    await waitFor(() => expect(screen.getByText(/3 values/i)).toBeInTheDocument());

    fireEvent.change(input, {
      target: { files: [makeFile("1\noops")] },
    });
    await waitFor(() => expect(screen.getByText(/oops/)).toBeInTheDocument());
    expect(screen.queryByText(/3 values/i)).not.toBeInTheDocument();
  });
});
