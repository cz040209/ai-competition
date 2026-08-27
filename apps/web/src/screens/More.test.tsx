import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Memory } from "@kira/contracts";

import { More } from "./More";

const MEMORIES: Memory[] = [
  {
    id: "m1",
    kind: "constraint",
    subject: "standing rule",
    fact: "Never suggest cutting the wedding goal.",
    confidence: 90,
    source_message_id: null,
    created_at: "2026-09-01T04:00:00Z",
    last_used_at: null,
  },
  {
    id: "m2",
    kind: "person",
    subject: "housemate",
    fact: "Splits rent with a housemate.",
    confidence: 75,
    source_message_id: null,
    created_at: "2026-09-02T04:00:00Z",
    last_used_at: null,
  },
];

function setup(memories: Memory[] | undefined = MEMORIES) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <More memories={memories} isLoading={false} />
    </QueryClientProvider>,
  );
  return userEvent.setup();
}

describe("More", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve({ ...MEMORIES[0], fact: "Never cut the wedding goal." }),
          text: () => Promise.resolve(""),
        } as unknown as Response),
      ),
    );
  });

  afterEach(() => vi.unstubAllGlobals());

  it("lists every fact with what kind it is", () => {
    setup();
    expect(screen.getByText("Never suggest cutting the wedding goal.")).toBeInTheDocument();
    expect(screen.getByText("constraint")).toBeInTheDocument();
    expect(screen.getByText(/someone in your money/)).toBeInTheDocument();
  });

  it("says how sure it is, so a shaky fact reads as shaky", () => {
    setup();
    expect(screen.getByText("75% sure")).toBeInTheDocument();
  });

  it("says so plainly when it has learned nothing", () => {
    setup([]);
    expect(screen.getByText(/Nothing yet/)).toBeInTheDocument();
  });

  it("corrects a fact in place", async () => {
    const user = setup();
    await user.click(screen.getAllByRole("button", { name: "Correct" })[0]!);

    const field = screen.getByLabelText("Correct this memory");
    await user.clear(field);
    await user.type(field, "Never cut the wedding goal.");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/v1/butler/memories/m1",
        expect.objectContaining({ method: "PATCH" }),
      ),
    );
  });

  it("abandons a correction without sending it", async () => {
    const user = setup();
    await user.click(screen.getAllByRole("button", { name: "Correct" })[0]!);
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByLabelText("Correct this memory")).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("forgets a fact", async () => {
    const user = setup();
    await user.click(
      screen.getByRole("button", { name: "Forget: Splits rent with a housemate." }),
    );
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/v1/butler/memories/m2",
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
  });
});
