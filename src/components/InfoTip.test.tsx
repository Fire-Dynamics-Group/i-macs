/** @jsxImportSource react */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { InfoTip } from "./InfoTip";

describe("InfoTip", () => {
  it("keeps the content hidden until the icon is clicked", async () => {
    const user = userEvent.setup();
    render(<InfoTip label="Shear connection">the formula</InfoTip>);

    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /shear connection/i }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent("the formula");
  });

  it("toggles closed on a second click", async () => {
    const user = userEvent.setup();
    render(<InfoTip label="Shear connection">the formula</InfoTip>);

    const icon = screen.getByRole("button", { name: /shear connection/i });
    await user.click(icon);
    await user.click(icon);

    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    render(<InfoTip label="Shear connection">the formula</InfoTip>);

    await user.click(screen.getByRole("button", { name: /shear connection/i }));
    await screen.findByRole("tooltip");
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  // The tip lives inside the config <form>; a default-type button would submit it.
  it("does not submit the surrounding form", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn((e: React.FormEvent) => e.preventDefault());
    render(
      <form onSubmit={onSubmit}>
        <InfoTip label="Shear connection">the formula</InfoTip>
      </form>,
    );

    await user.click(screen.getByRole("button", { name: /shear connection/i }));
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
