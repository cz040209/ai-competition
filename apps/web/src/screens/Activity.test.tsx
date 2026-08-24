import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { Activity as ActivityData } from "@kira/contracts";

import { Activity } from "./Activity";

const DATA = {
  drafts: [
    {
      id: "d1",
      merchant: "Grab — office to KLCC",
      amount_sen: 1400,
      category: "transport",
      category_label: "Transport",
      occurred_on: "2026-09-03",
      status: "draft",
      source: "voice",
      confidence: 71,
      note: "Heard 'fourteen ringgit'.",
    },
    {
      id: "d2",
      merchant: "Nasi Kandar Pelita",
      amount_sen: 1890,
      category: "food",
      category_label: "Food & drink",
      occurred_on: "2026-09-03",
      status: "draft",
      source: "receipt",
      confidence: 94,
      note: "Line item total matched.",
    },
  ],
  draft_total_sen: 3290,
  days: [
    {
      date: "2026-09-02",
      total_sen: 2870,
      transactions: [
        {
          id: "t1",
          merchant: "Grab — KLCC to home",
          amount_sen: 1620,
          category: "transport",
      category_label: "Transport",
          occurred_on: "2026-09-02",
          status: "confirmed",
          source: "manual",
          confidence: null,
          note: "",
        },
        {
          id: "t2",
          merchant: "Family Mart",
          amount_sen: 1250,
          category: "groceries",
          category_label: "Groceries",
          occurred_on: "2026-09-02",
          status: "confirmed",
          source: "receipt",
          confidence: null,
          note: "",
        },
      ],
    },
  ],
  spent_this_cycle_sen: 42025,
  categories: [
    { slug: "transport", label: "Transport", spent_this_cycle_sen: 1620, count: 1 },
    { slug: "groceries", label: "Groceries", spent_this_cycle_sen: 1250, count: 1 },
    { slug: "food", label: "Food & drink", spent_this_cycle_sen: 890, count: 1 },
  ],
} as ActivityData;

function renderActivity(overrides: Partial<Parameters<typeof Activity>[0]> = {}) {
  const props = {
    data: DATA as ActivityData | undefined,
    isLoading: false,
    isError: false,
    onConfirm: vi.fn(),
    onDiscard: vi.fn(),
    onUnconfirm: vi.fn(),
    settlingId: null,
    category: null,
    onCategory: vi.fn(),
    go: vi.fn(),
    ...overrides,
  };
  return { ...render(<Activity {...props} />), props };
}

function draftCard(merchant: string): HTMLElement {
  return screen.getByText(merchant).closest(".draft") as HTMLElement;
}

describe("Activity", () => {
  it("sends capture to Butler rather than repeating it here", async () => {
    const { props } = renderActivity();
    expect(screen.queryByRole("button", { name: "Receipt" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Voice" })).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Tell Butler/ }));
    expect(props.go).toHaveBeenCalledWith("butler");
  });

  it("offers a chip for each category present, dearest first", () => {
    renderActivity();
    const chips = screen.getAllByRole("radio").map((chip) => chip.textContent);
    expect(chips?.[0]).toMatch(/All/);
    expect(chips?.[1]).toMatch(/Transport/);
    expect(chips?.[3]).toMatch(/Food & drink/);
  });

  it("asks for the category that was tapped", async () => {
    const { props } = renderActivity();
    await userEvent.click(screen.getByRole("radio", { name: /Food & drink/ }));
    expect(props.onCategory).toHaveBeenCalledWith("food");
  });

  it("clears the filter when All is tapped", async () => {
    const { props } = renderActivity({ category: "food" });
    await userEvent.click(screen.getByRole("radio", { name: /All/ }));
    expect(props.onCategory).toHaveBeenCalledWith(null);
  });

  it("marks the active chip for a screen reader", () => {
    renderActivity({ category: "food" });
    expect(screen.getByRole("radio", { name: /Food & drink/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /All/ })).not.toBeChecked();
  });

  it("names the filter in the cycle heading", () => {
    renderActivity({ category: "food" });
    expect(screen.getByText(/Food & drink this cycle/)).toBeInTheDocument();
  });

  it("says which filter came up empty", () => {
    renderActivity({ category: "food", data: { ...DATA, days: [], spent_this_cycle_sen: 0 } });
    expect(screen.getByText(/Nothing under Food & drink this cycle/)).toBeInTheDocument();
  });

  it("counts the drafts waiting for a decision", () => {
    renderActivity();
    expect(screen.getByText(/Waiting for you · 2/)).toBeInTheDocument();
  });

  it("shows a draft with the confidence it was read with", () => {
    renderActivity();
    expect(screen.getByText("Nasi Kandar Pelita")).toBeInTheDocument();
    expect(within(draftCard("Nasi Kandar Pelita")).getByText("Food & drink")).toBeInTheDocument();
    expect(screen.getByText(/94% sure/)).toBeInTheDocument();
  });

  it("confirms the draft that was tapped", async () => {
    const { props } = renderActivity();
    await userEvent.click(
      within(draftCard("Nasi Kandar Pelita")).getByRole("button", { name: "Confirm" }),
    );
    expect(props.onConfirm).toHaveBeenCalledWith("d2");
  });

  it("discards the draft that was tapped", async () => {
    const { props } = renderActivity();
    await userEvent.click(
      within(draftCard("Nasi Kandar Pelita")).getByRole("button", { name: "Discard" }),
    );
    expect(props.onDiscard).toHaveBeenCalledWith("d2");
  });

  it("lists confirmed spending under the day it happened", () => {
    renderActivity();
    expect(screen.getByText("Wednesday, 2 September")).toBeInTheDocument();
    expect(screen.getByText("Family Mart")).toBeInTheDocument();
    expect(screen.getByText("Groceries · Receipt")).toBeInTheDocument();
  });

  it("totals each day and the cycle so far", () => {
    renderActivity();
    expect(screen.getByText("RM28.70")).toBeInTheDocument();
    expect(screen.getByText("RM420.25")).toBeInTheDocument();
  });

  it("says nothing is waiting when no drafts remain", () => {
    renderActivity({ data: { ...DATA, drafts: [], draft_total_sen: 0 } });
    expect(screen.getByText(/Nothing waiting/)).toBeInTheDocument();
  });

  it("invites a first entry when the ledger is empty", () => {
    renderActivity({
      data: { ...DATA, drafts: [], draft_total_sen: 0, days: [], spent_this_cycle_sen: 0 },
    });
    expect(screen.getByText(/Nothing on your ledger yet/)).toBeInTheDocument();
  });

  it("waits rather than guessing while the ledger loads", () => {
    renderActivity({ data: undefined, isLoading: true });
    expect(screen.getByText(/Fetching your ledger/)).toBeInTheDocument();
  });

  it("admits when it cannot reach the ledger", () => {
    renderActivity({ data: undefined, isLoading: false, isError: true });
    expect(screen.getByText(/couldn't reach your ledger/i)).toBeInTheDocument();
  });

  it("opens a detail sheet for the confirmed row that was tapped", async () => {
    renderActivity();
    await userEvent.click(screen.getByRole("button", { name: /Family Mart/ }));
    const sheet = screen.getByRole("dialog", { name: "Family Mart" });
    expect(within(sheet).getByText("RM12.50")).toBeInTheDocument();
    expect(within(sheet).getByText("Groceries")).toBeInTheDocument();
    expect(within(sheet).getByText("Wednesday, 2 September")).toBeInTheDocument();
    expect(within(sheet).getByText("Receipt")).toBeInTheDocument();
  });

  it("takes a transaction back off the ledger from its sheet", async () => {
    const { props } = renderActivity();
    await userEvent.click(screen.getByRole("button", { name: /Family Mart/ }));
    await userEvent.click(screen.getByRole("button", { name: /Move back to drafts/ }));
    expect(props.onUnconfirm).toHaveBeenCalledWith("t2");
  });

  it("closes the sheet once the row it showed is no longer on the ledger", async () => {
    const { rerender, props } = renderActivity();
    await userEvent.click(screen.getByRole("button", { name: /Family Mart/ }));
    expect(screen.getByRole("dialog", { name: "Family Mart" })).toBeInTheDocument();

    const [day] = DATA.days;
    const [firstTxn] = day!.transactions;
    rerender(
      <Activity
        {...props}
        data={{ ...DATA, days: [{ ...day!, transactions: [firstTxn!], total_sen: 1620 }] }}
      />,
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("leaves drafts to their own inline details", async () => {
    renderActivity();
    await userEvent.click(
      within(draftCard("Nasi Kandar Pelita")).getByRole("button", { name: "Details" }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("disables both choices on the draft being settled", () => {
    renderActivity({ settlingId: "d2" });
    const card = draftCard("Nasi Kandar Pelita");
    expect(within(card).getByRole("button", { name: "Confirm" })).toBeDisabled();
    expect(within(card).getByRole("button", { name: "Discard" })).toBeDisabled();
    expect(
      within(draftCard("Grab — office to KLCC")).getByRole("button", { name: "Confirm" }),
    ).toBeEnabled();
  });
});
