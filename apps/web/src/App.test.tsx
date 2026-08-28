import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const DASHBOARD = {
  date: "2026-09-03",
  display_name: "Floyd",
  currency: "MYR",
  balance_sen: 418040,
  reserved_sen: 200300,
  buffer_sen: 80000,
  goal_reserve_sen: 21200,
  unclaimed_sen: 116540,
  per_day_sen: 5297,
  spent_today_sen: 0,
  safe_today_sen: 5297,
  days_to_payday: 22,
  cycle_elapsed: 8,
  commitment_count: 5,
  drafts_waiting: 2,
  next_commitment: null,
  goals: [],
};

const DRAFT = {
  id: "d1",
  merchant: "Nasi Kandar Pelita",
  amount_sen: 1890,
  category: "food",
  category_label: "Food & drink",
  occurred_on: "2026-09-03",
  status: "draft",
  source: "receipt",
  confidence: 94,
  note: "Line item total matched.",
};

const LEDGER_TXN = {
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
};

const ACTIVITY = {
  drafts: [DRAFT],
  draft_total_sen: 1890,
  days: [
    {
      date: "2026-09-02",
      total_sen: 1620,
      transactions: [LEDGER_TXN],
    },
  ],
  spent_this_cycle_sen: 1620,
  categories: [{ slug: "transport", label: "Transport", spent_this_cycle_sen: 1620, count: 1 }],
};

/** Mutable so a test can prove the screens re-read after a confirm. */
let activity = ACTIVITY;
let dashboard = DASHBOARD;
let asked: (string | null)[] = [];

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  activity = ACTIVITY;
  dashboard = DASHBOARD;
  asked = [];
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/v1/auth/refresh")) return new Response("", { status: 401 });
      if (url.endsWith("/v1/auth/login")) {
        return new Response(JSON.stringify({ access_token: "t", token_type: "bearer" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.endsWith("/v1/dashboard/today")) {
        return new Response(JSON.stringify(dashboard), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.includes("/v1/transactions?category=")) {
        asked.push(new URL(url, "http://test").searchParams.get("category"));
        return new Response(JSON.stringify({ ...activity, days: [], spent_this_cycle_sen: 0 }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.endsWith("/v1/transactions")) {
        return new Response(JSON.stringify(activity), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.endsWith(`/v1/transactions/${LEDGER_TXN.id}/unconfirm`)) {
        activity = { ...ACTIVITY, days: [] , spent_this_cycle_sen: 0 };
        return new Response(JSON.stringify({ ...LEDGER_TXN, status: "draft" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.endsWith(`/v1/transactions/${DRAFT.id}/confirm`)) {
        activity = { ...ACTIVITY, drafts: [], draft_total_sen: 0 };
        dashboard = { ...DASHBOARD, safe_today_sen: 3321, drafts_waiting: 0 };
        return new Response(JSON.stringify({ ...DRAFT, status: "confirmed" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
      if (url.includes("/v1/day-plan/places")) {
        return new Response(
          // The counts are what tell the three empty lists apart, so a stub
          // that leaves them out is a response the API never sends.
          JSON.stringify({
            room_sen: 5297,
            cap_sen: 5297,
            nearby_count: 0,
            matching_count: 0,
            places: [],
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        );
      }
      return new Response("", { status: 404 });
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("App", () => {
  it("shows the login gate before authentication", async () => {
    renderApp();
    expect(await screen.findByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("renders the five navigation tabs once signed in", async () => {
    renderApp();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: /sign in/i }));

    for (const label of ["Today", "Activity", "Butler", "Plan", "More"]) {
      expect(await screen.findByRole("button", { name: new RegExp(`^${label}$`, "i") })).toBeInTheDocument();
    }
  });

  it("shows the ledger on the Activity tab", async () => {
    renderApp();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: /sign in/i }));
    await user.click(await screen.findByRole("button", { name: /^Activity$/i }));

    expect(await screen.findByText("Nasi Kandar Pelita")).toBeInTheDocument();
    expect(screen.getByText("Grab — KLCC to home")).toBeInTheDocument();
  });

  it("moves today's safe-to-spend when a draft is confirmed", async () => {
    renderApp();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: /sign in/i }));
    await user.click(await screen.findByRole("button", { name: /^Activity$/i }));
    await user.click(await screen.findByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.getByText(/Nothing waiting/)).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /^Today$/i }));
    expect(await screen.findByLabelText("RM33.21")).toBeInTheDocument();
  });

  it("opens a ledger row and moves it back to the drafts", async () => {
    renderApp();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: /sign in/i }));
    await user.click(await screen.findByRole("button", { name: /^Activity$/i }));
    await user.click(await screen.findByRole("button", { name: /Grab — KLCC to home/ }));

    await user.click(screen.getByRole("button", { name: /Move back to drafts/ }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText(/Nothing on your ledger yet/)).toBeInTheDocument();
  });

  it("asks the API for the category that was tapped", async () => {
    renderApp();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: /sign in/i }));
    await user.click(await screen.findByRole("button", { name: /^Activity$/i }));
    await user.click(await screen.findByRole("radio", { name: /Transport/ }));

    await waitFor(() => expect(asked).toContain("transport"));
    expect(await screen.findByText(/Nothing under Transport this cycle/)).toBeInTheDocument();
  });

  it("switches tabs without losing the shell", async () => {
    renderApp();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await user.click(await screen.findByRole("button", { name: /sign in/i }));
    await user.click(await screen.findByRole("button", { name: /^Plan$/i }));

    await waitFor(() => expect(screen.getByText(/What today's money can buy/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /^Today$/i })).toBeInTheDocument();
  });
});
