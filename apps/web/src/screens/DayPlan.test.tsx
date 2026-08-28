import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DayPlan as DayPlanData, Place } from "@kira/contracts";

import { api } from "../api/client";
import { DayPlan } from "./DayPlan";

vi.mock("../api/client", () => ({
  api: { get: vi.fn() },
}));

const ROOM_SEN = 5297;

const PLACES: Place[] = [
  {
    id: "p1",
    name: "Nasi Kandar Pelita",
    kind: "Mamak",
    km: 0.65,
    travel_sen: 0,
    minutes: 14,
    total_sen: 1250,
    share: 0.24,
    band: "ok",
    confidence: "high",
    halal: true,
    note: "Fast counter service, open late.",
  },
  {
    id: "p2",
    name: "Chee Meng Chicken Rice",
    kind: "Chinese",
    km: 1.8,
    travel_sen: 500,
    minutes: 22,
    total_sen: 4800,
    share: 0.92,
    band: "tight",
    confidence: "medium",
    halal: false,
    note: "Small shop, queue moves quickly.",
  },
  {
    id: "p3",
    name: "Sky Bar Steakhouse",
    kind: "Fine dining",
    km: 3.2,
    travel_sen: 900,
    minutes: 35,
    total_sen: 9800,
    share: 1.9,
    band: "over",
    confidence: "low",
    halal: true,
    note: "Way past today's room.",
  },
];

const RESPONSE: DayPlanData = {
  room_sen: ROOM_SEN,
  cap_sen: ROOM_SEN,
  nearby_count: PLACES.length,
  matching_count: PLACES.length,
  places: PLACES,
};

/** A spent-out day, stated the way the API states it — including the counts,
 *  which a fixture that leaves them out would quietly stop exercising. */
const NOTHING_LEFT: DayPlanData = {
  room_sen: 0,
  cap_sen: 0,
  nearby_count: PLACES.length,
  matching_count: PLACES.length,
  places: [],
};

function renderDayPlan() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <DayPlan />
    </QueryClientProvider>,
  );
}

function lastRequestedUrl(): string {
  const calls = vi.mocked(api.get).mock.calls;
  return String(calls[calls.length - 1]?.[0]);
}

/** jsdom ships no geolocation at all, so every case installs the one it needs. */
function stubGeolocation(getCurrentPosition: Geolocation["getCurrentPosition"]) {
  Object.defineProperty(navigator, "geolocation", {
    configurable: true,
    value: { getCurrentPosition },
  });
  return getCurrentPosition;
}

function failingGeolocation(code: number) {
  return stubGeolocation(
    vi.fn((_success, error) => {
      error?.({ code, message: "", PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3 });
    }),
  );
}

function geolocationAt(lat: number, lng: number) {
  return stubGeolocation(
    vi.fn((success) => {
      success({ coords: { latitude: lat, longitude: lng } } as GeolocationPosition);
    }),
  );
}

beforeEach(() => {
  vi.mocked(api.get).mockReset();
  vi.mocked(api.get).mockResolvedValue(RESPONSE);
  Reflect.deleteProperty(navigator, "geolocation");
});

describe("DayPlan", () => {
  it("lists ranked places with their cost and band", async () => {
    renderDayPlan();

    expect(await screen.findByText("Nasi Kandar Pelita")).toBeInTheDocument();
    expect(screen.getByText("RM12.50")).toBeInTheDocument();
    expect(screen.getByText("Chee Meng Chicken Rice")).toBeInTheDocument();
    expect(screen.getByText("RM48.00")).toBeInTheDocument();
    expect(screen.getByText("Sky Bar Steakhouse")).toBeInTheDocument();
    expect(screen.getByText("RM98.00")).toBeInTheDocument();
    expect(screen.getByText("Best fit")).toBeInTheDocument();
    expect(screen.getByText("Over")).toBeInTheDocument();
  });

  it("requests from KLCC on foot with halal on, by default", async () => {
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    const url = lastRequestedUrl();
    expect(url).toContain("lat=3.1577");
    expect(url).toContain("lng=101.712");
    expect(url).toContain("mode=walk");
    expect(url).toContain("halal_only=true");
    expect(url).not.toContain("cap_sen");
  });

  it("shows an empty state when nothing fits", async () => {
    vi.mocked(api.get).mockResolvedValue({ ...RESPONSE, places: [] });
    renderDayPlan();

    expect(await screen.findByText(/Nothing under RM52.97 yet/i)).toBeInTheDocument();
  });

  it("states the ceiling is nil at the ceiling, not distance", async () => {
    vi.mocked(api.get).mockResolvedValue({ ...RESPONSE, nearby_count: 3, matching_count: 3, places: [] });
    renderDayPlan();

    expect(await screen.findByText(/Nothing under RM52.97 yet/i)).toBeInTheDocument();
    expect(screen.getByText(/Raise the ceiling/i)).toBeInTheDocument();
    expect(screen.queryByText(/Nothing within range/i)).not.toBeInTheDocument();
  });

  it("blames distance rather than the ceiling when nothing was in range", async () => {
    // Raising the ceiling here could never surface a place, so the copy that
    // tells the user to raise it would send them round a loop with no exit.
    vi.mocked(api.get).mockResolvedValue({ ...RESPONSE, nearby_count: 0, matching_count: 0, places: [] });
    renderDayPlan();

    expect(await screen.findByText(/Nothing within range of here/i)).toBeInTheDocument();
    expect(screen.getByText(/demo set only covers central KL/i)).toBeInTheDocument();
    expect(screen.queryByText(/Raise the ceiling/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Nothing under RM52.97 yet/i)).not.toBeInTheDocument();
  });

  it("blames the halal filter rather than the ceiling when it is what emptied the list", async () => {
    // One place is in range and the ceiling is RM52.97 against a RM22 outing.
    // Telling the user to raise the ceiling here aims them at a slider that
    // cannot reach the thing that is actually in the way.
    vi.mocked(api.get).mockResolvedValue({
      ...RESPONSE,
      nearby_count: 1,
      matching_count: 0,
      places: [],
    });
    renderDayPlan();

    expect(
      await screen.findByText(/The one place within range of here is not halal/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Raising the ceiling will not change that/i)).toBeInTheDocument();
    expect(screen.queryByText(/Nothing under RM52.97 yet/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Raise the ceiling/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Nothing within range of here/i)).not.toBeInTheDocument();
  });

  it("counts the places the halal filter took out, rather than saying 'some'", async () => {
    vi.mocked(api.get).mockResolvedValue({
      ...RESPONSE,
      nearby_count: 4,
      matching_count: 0,
      places: [],
    });
    renderDayPlan();

    expect(
      await screen.findByText(/None of the 4 places within range of here are halal/i),
    ).toBeInTheDocument();
  });

  it("offers the halal toggle as the way out, and re-asks with it off", async () => {
    vi.mocked(api.get).mockResolvedValue({
      ...RESPONSE,
      nearby_count: 1,
      matching_count: 0,
      places: [],
    });
    renderDayPlan();
    await screen.findByText(/is not halal/i);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Turn Halal off" }));

    await waitFor(() => expect(lastRequestedUrl()).toContain("halal_only=false"));
  });

  it("keeps blaming the ceiling when the ceiling really is the cause", async () => {
    // The guard against overcorrecting: with everything in range still halal,
    // the ceiling is the only thing left and the copy must still say so.
    vi.mocked(api.get).mockResolvedValue({
      ...RESPONSE,
      nearby_count: 3,
      matching_count: 3,
      places: [],
    });
    renderDayPlan();

    expect(await screen.findByText(/Nothing under RM52.97 yet/i)).toBeInTheDocument();
    expect(screen.queryByText(/not halal/i)).not.toBeInTheDocument();
  });

  it("reports today's room from the server, never inferred from a share", async () => {
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    // total_sen / share on the first place would give RM52.08, not RM52.97.
    expect(screen.getByText("RM52.97")).toBeInTheDocument();
  });

  it("states nothing is left rather than inventing a room on a spent-out day", async () => {
    // The API floors safe-to-spend at zero and sends no share at all; a share
    // divided into total_sen would print a room the user does not have.
    vi.mocked(api.get).mockResolvedValue({
      ...NOTHING_LEFT,
      cap_sen: 5000,
      places: [{ ...PLACES[0], share: null, band: "over" }],
    });
    renderDayPlan();

    await screen.findByText("Nasi Kandar Pelita");
    expect(screen.getAllByText("Nothing left in today's room").length).toBeGreaterThan(0);
    expect(screen.queryByText(/% of today's room/i)).not.toBeInTheDocument();
    expect(screen.queryByText("RM6.25")).not.toBeInTheDocument();
  });

  it("sits the ceiling control on the ceiling it names, even at nil", async () => {
    // A range input clamps a value outside its bounds without saying so, which
    // would leave the knob at RM5 beside a figure reading RM0.00.
    vi.mocked(api.get).mockResolvedValue(NOTHING_LEFT);
    renderDayPlan();
    await screen.findByText(/Nothing under RM0.00 yet/i);

    const slider = screen.getByLabelText("Spending ceiling") as HTMLInputElement;
    expect(slider.value).toBe("0");
    expect(screen.getByLabelText("RM0.00")).toBeInTheDocument();
    expect(screen.queryByText("Inside today's room")).not.toBeInTheDocument();
  });

  it("keeps the ceiling control on screen while the new list is fetched", async () => {
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    const slider = screen.getByLabelText("Spending ceiling") as HTMLInputElement;
    fireEvent.change(slider, { target: { value: "3000" } });

    // Unmounting into the loading state here would end the drag on its first step.
    expect(screen.getByLabelText("Spending ceiling")).toBeInTheDocument();
    await waitFor(() => expect(lastRequestedUrl()).toContain("cap_sen=3000"));
  });

  it("does not move the scale out from under a ceiling dragged to the top", async () => {
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");

    const slider = screen.getByLabelText("Spending ceiling") as HTMLInputElement;
    const top = slider.max;
    fireEvent.change(slider, { target: { value: top } });

    const after = screen.getByLabelText("Spending ceiling") as HTMLInputElement;
    expect(after.max).toBe(top);
    expect(after.value).toBe(top);
  });

  it("never asks for a ceiling of nothing, which the API rejects", async () => {
    vi.mocked(api.get).mockResolvedValue(NOTHING_LEFT);
    renderDayPlan();
    await screen.findByText(/Nothing under RM0.00 yet/i);

    const slider = screen.getByLabelText("Spending ceiling") as HTMLInputElement;
    // Anything the control can reach below RM5 must be asked for as RM5.
    fireEvent.change(slider, { target: { value: "50" } });

    await waitFor(() => expect(lastRequestedUrl()).toContain("cap_sen=500"));
  });

  it("admits when the request fails", async () => {
    vi.mocked(api.get).mockRejectedValue(new Error("network down"));
    renderDayPlan();

    expect(await screen.findByText(/couldn't find places/i)).toBeInTheDocument();
  });

  it("re-fetches with the new mode when a mode chip is tapped", async () => {
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "LRT" }));

    await waitFor(() => expect(lastRequestedUrl()).toContain("mode=transit"));
  });

  it("re-fetches with halal_only=false once the halal toggle is switched off", async () => {
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Halal" }));

    await waitFor(() => expect(lastRequestedUrl()).toContain("halal_only=false"));
  });

  it("says a blocked location was blocked, and what it is planning from instead", async () => {
    // The bug this guards: locState went to "denied" and nothing on the page
    // read it, so a refused permission looked exactly like an untouched chip.
    failingGeolocation(1);
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Use my location" }));

    expect(await screen.findByText(/Location is blocked for this site/i)).toBeInTheDocument();
    expect(screen.getByText(/planning from KLCC/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Location blocked" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Use my location" })).not.toBeInTheDocument();
  });

  it("tells a timeout apart from a refusal, and lets it be tried again", async () => {
    const getCurrentPosition = failingGeolocation(3);
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Use my location" }));

    // Different cause, different advice: settings for a block, another tap here.
    expect(await screen.findByText(/took longer than 8 seconds/i)).toBeInTheDocument();
    expect(screen.queryByText(/blocked for this site/i)).not.toBeInTheDocument();
    const chip = screen.getByRole("button", { name: "Location timed out" });
    expect(chip).toBeEnabled();

    await user.click(chip);
    expect(getCurrentPosition).toHaveBeenCalledTimes(2);
  });

  it("plans from where the user is once located, and says so", async () => {
    geolocationAt(5.4141, 100.3288);
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Use my location" }));

    expect(await screen.findByRole("button", { name: "Located" })).toBeInTheDocument();
    expect(screen.getByText("Near you")).toBeInTheDocument();
    await waitFor(() => expect(lastRequestedUrl()).toContain("lat=5.4141"));
  });

  it("drops the KLCC list rather than show it under 'where you are'", async () => {
    // The KLCC answer stays valid while only the ceiling moves, so the slider
    // keeps it. It does not survive a change of origin: the header, the voice
    // line and every distance on screen would go on describing KLCC while
    // saying "where you are", 300 km from the nearest of them.
    geolocationAt(5.4141, 100.3288);
    vi.mocked(api.get).mockImplementation((url: string) =>
      String(url).includes("lat=5.4141")
        ? new Promise(() => {}) // the Penang answer never lands
        : Promise.resolve(RESPONSE),
    );
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Use my location" }));

    expect(await screen.findByText(/Finding what fits today/i)).toBeInTheDocument();
    expect(screen.queryByText("Nasi Kandar Pelita")).not.toBeInTheDocument();
    expect(screen.queryByText(/from where you are/i)).not.toBeInTheDocument();
    expect(screen.queryByText("650 m")).not.toBeInTheDocument();
  });

  it("drops the walking prices rather than show them under a different mode", async () => {
    vi.mocked(api.get).mockImplementation((url: string) =>
      String(url).includes("mode=transit")
        ? new Promise(() => {})
        : Promise.resolve(RESPONSE),
    );
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "LRT" }));

    // RM12.50 is what Nasi Kandar costs on foot; by LRT it is not, and a list
    // labelled "lrt from KLCC" showing walking totals is a wrong price.
    expect(await screen.findByText(/Finding what fits today/i)).toBeInTheDocument();
    expect(screen.queryByText("RM12.50")).not.toBeInTheDocument();
  });

  it("names the origin it is really on when a retry fails after a locate", async () => {
    let fail = false;
    stubGeolocation(
      vi.fn((success, error) => {
        if (fail) {
          error?.({ code: 3, message: "", PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3 });
          return;
        }
        success({ coords: { latitude: 5.4141, longitude: 100.3288 } } as GeolocationPosition);
      }),
    );
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Use my location" }));
    await screen.findByRole("button", { name: "Located" });
    fail = true;
    await user.click(screen.getByRole("button", { name: "Located" }));

    // The first fix is still the origin, so claiming KLCC here would be the
    // same silent lie in the opposite direction.
    expect(await screen.findByText(/still planning from where I last found you/i)).toBeInTheDocument();
    expect(screen.queryByText(/planning from KLCC/i)).not.toBeInTheDocument();
    expect(screen.getByText("Near you")).toBeInTheDocument();
  });

  it("offers KLCC as the way out of an origin with nothing around it", async () => {
    geolocationAt(5.4141, 100.3288);
    vi.mocked(api.get).mockResolvedValue({ ...RESPONSE, nearby_count: 0, matching_count: 0, places: [] });
    renderDayPlan();
    await screen.findByText(/Nothing within range of here/i);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Use my location" }));
    await screen.findByRole("button", { name: "Located" });

    await user.click(screen.getByRole("button", { name: "Plan from KLCC instead" }));

    // The chip and the header both name the origin, so neither may keep
    // claiming a location that is no longer being planned from.
    expect(screen.getByText("Near KLCC")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use my location" })).toBeInTheDocument();
    await waitFor(() => expect(lastRequestedUrl()).toContain("lat=3.1577"));
  });

  it("opens a detail sheet with the cost breakdown and adds it to today", async () => {
    renderDayPlan();
    await screen.findByText("Nasi Kandar Pelita");
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /Nasi Kandar Pelita/ }));
    const sheet = screen.getByRole("dialog", { name: "Nasi Kandar Pelita" });
    expect(within(sheet).getAllByText("RM12.50").length).toBeGreaterThan(0);
    expect(within(sheet).getByText("Meal estimate")).toBeInTheDocument();
    expect(within(sheet).getByText("650 m")).toBeInTheDocument();

    await user.click(within(sheet).getByRole("button", { name: "Add to today" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(await screen.findByText(/added to today/i)).toBeInTheDocument();
  });
});
