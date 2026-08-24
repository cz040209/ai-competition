import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Sheet, SheetHostContext } from "./Sheet";

describe("Sheet", () => {
  it("names itself for a screen reader", () => {
    render(
      <Sheet label="Nasi Kandar Pelita" onClose={vi.fn()}>
        <p>body</p>
      </Sheet>,
    );
    expect(screen.getByRole("dialog", { name: "Nasi Kandar Pelita" })).toBeInTheDocument();
  });

  it("closes when the scrim is tapped", async () => {
    const onClose = vi.fn();
    const { container } = render(
      <Sheet label="Details" onClose={onClose}>
        <p>body</p>
      </Sheet>,
    );
    await userEvent.click(container.querySelector(".scrim") as HTMLElement);
    expect(onClose).toHaveBeenCalled();
  });

  it("closes on Escape", async () => {
    const onClose = vi.fn();
    render(
      <Sheet label="Details" onClose={onClose}>
        <p>body</p>
      </Sheet>,
    );
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });

  it("mounts into the device frame, not the scrolling content", () => {
    const host = document.createElement("div");
    host.className = "screen";
    document.body.append(host);
    const ref = { current: host };

    render(
      <SheetHostContext.Provider value={ref}>
        <div className="viewport">
          <Sheet label="Details" onClose={vi.fn()}>
            <p>body</p>
          </Sheet>
        </div>
      </SheetHostContext.Provider>,
    );

    expect(host.querySelector(".sheet")).not.toBeNull();
    expect(document.querySelector(".viewport")?.querySelector(".sheet")).toBeNull();
    host.remove();
  });

  it("stays open when the sheet itself is tapped", async () => {
    const onClose = vi.fn();
    render(
      <Sheet label="Details" onClose={onClose}>
        <p>body</p>
      </Sheet>,
    );
    await userEvent.click(screen.getByText("body"));
    expect(onClose).not.toHaveBeenCalled();
  });
});
