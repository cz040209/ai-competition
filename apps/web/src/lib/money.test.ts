import { describe, expect, it } from "vitest";

import { fmt } from "./money";

describe("fmt", () => {
  it("formats sen as grouped ringgit", () => {
    expect(fmt(418040)).toBe("4,180.40");
  });

  it("always shows two decimals", () => {
    expect(fmt(5)).toBe("0.05");
    expect(fmt(100)).toBe("1.00");
  });

  it("formats the demo safe-to-spend", () => {
    expect(fmt(5297)).toBe("52.97");
  });

  it("handles zero", () => {
    expect(fmt(0)).toBe("0.00");
  });

  it("handles negatives", () => {
    expect(fmt(-1890)).toBe("-18.90");
  });
});
