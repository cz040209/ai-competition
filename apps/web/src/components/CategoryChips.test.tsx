import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CategorySummary } from "@kira/contracts";

import { CategoryChips } from "./CategoryChips";

const CATEGORIES = [
  { slug: "transport", label: "Transport", spent_this_cycle_sen: 15620, count: 3 },
  { slug: "food", label: "Food & drink", spent_this_cycle_sen: 4430, count: 3 },
] as CategorySummary[];

/** jsdom has no layout, so the scroll geometry has to be stated outright. */
function withGeometry(bar: HTMLElement, scrollLeft: number, scrollWidth = 900, clientWidth = 360) {
  Object.defineProperty(bar, "scrollWidth", { value: scrollWidth, configurable: true });
  Object.defineProperty(bar, "clientWidth", { value: clientWidth, configurable: true });
  bar.scrollLeft = scrollLeft;
  fireEvent.scroll(bar);
}

function renderChips() {
  const onPick = vi.fn();
  render(
    <CategoryChips categories={CATEGORIES} active={null} onPick={onPick} totalSen={20050} />,
  );
  return { bar: screen.getByRole("radiogroup"), onPick };
}

describe("CategoryChips", () => {
  it("fades the right edge while chips remain off-screen", () => {
    const { bar } = renderChips();
    withGeometry(bar, 0);
    expect(bar.className).toContain("fade-end");
    expect(bar.className).not.toContain("fade-start");
  });

  it("fades both edges once scrolled into the middle", () => {
    const { bar } = renderChips();
    withGeometry(bar, 200);
    expect(bar.className).toContain("fade-start");
    expect(bar.className).toContain("fade-end");
  });

  it("drops the right fade at the end of the row", () => {
    const { bar } = renderChips();
    withGeometry(bar, 540);
    expect(bar.className).toContain("fade-start");
    expect(bar.className).not.toContain("fade-end");
  });

  it("fades neither edge when every chip already fits", () => {
    const { bar } = renderChips();
    withGeometry(bar, 0, 360, 360);
    expect(bar.className).not.toContain("fade-start");
    expect(bar.className).not.toContain("fade-end");
  });
});
