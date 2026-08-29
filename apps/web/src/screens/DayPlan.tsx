import { useContext, useEffect, useState } from "react";
import { createPortal } from "react-dom";

import type { Place } from "@kira/contracts";

import { useAddPlanToToday, useDayPlan } from "../api/hooks";
import { IcCheck } from "../components/Icons";
import { Odometer } from "../components/Odometer";
import { Reveal } from "../components/Reveal";
import { Sheet, SheetHostContext } from "../components/Sheet";
import { fmt } from "../lib/money";
import {
  bestFitId,
  SORT_IDS,
  SORTS,
  sortPlaces,
  type SortId,
  type TravelMode,
} from "../lib/placeSort";

// No location yet beats a silent wrong one, so this is where distances and
// travel costs are measured from until the user grants their own.
const KLCC = { lat: 3.1577, lng: 101.712 };

type Mode = TravelMode;

const MODES: { id: Mode; label: string }[] = [
  { id: "walk", label: "Walk" },
  { id: "transit", label: "LRT" },
  { id: "ride", label: "Grab" },
];

const MIN_CAP_SEN = 500;
const CAP_STEP_SEN = 50;

type LocFailure = "unsupported" | "blocked" | "unavailable" | "timeout";
type LocState = "idle" | "asking" | "ok" | LocFailure;

// A cold fix on a laptop is a Wi-Fi scan, not a GPS read, and eight seconds
// was not enough for one in practice. Derived into the copy below so the number
// on screen cannot drift from the number actually waited.
const LOCATE_TIMEOUT_MS = 15_000;

// A failed locate that leaves the chip reading exactly as it did before the tap
// is indistinguishable from never having tapped, so each reason gets its own
// label and its own advice: a blocked permission needs the browser's settings
// changed, where a timeout is only worth another tap.
const LOC_FAILURES: Record<LocFailure, { chip: string; reason: string; advice: string }> = {
  unsupported: {
    chip: "Location unavailable",
    reason: "This browser will not give me your location",
    advice: "",
  },
  blocked: {
    chip: "Location blocked",
    // PERMISSION_DENIED does not say who denied it. The site's own permission
    // can read "allowed" while the system withholds location from the browser
    // itself, and sending someone to a settings page that already says yes is
    // its own small lie -- so name both places rather than guess between them.
    reason: "Location is blocked",
    advice:
      "That may be this site's permission or your system withholding it from the browser, "
      + "so check both, then tap again.",
  },
  unavailable: {
    chip: "Location unavailable",
    reason: "Your device couldn't fix a position",
    advice: "Tap again to retry.",
  },
  timeout: {
    chip: "Location timed out",
    reason: `Locating took longer than ${LOCATE_TIMEOUT_MS / 1000} seconds`,
    advice: "Tap again to retry.",
  },
};

function isLocFailure(state: LocState): state is LocFailure {
  return Object.hasOwn(LOC_FAILURES, state);
}

// GeolocationPositionError codes: 1 PERMISSION_DENIED, 2 POSITION_UNAVAILABLE,
// 3 TIMEOUT. Anything else is a browser inventing a code, and "unavailable" is
// the one reading that promises the user nothing.
function failureFor(code: number): LocFailure {
  return code === 1 ? "blocked" : code === 3 ? "timeout" : "unavailable";
}

function formatKm(km: number): string {
  return km < 1 ? `${Math.round(km * 1000)} m` : `${km.toFixed(1)} km`;
}

/**
 * The distance, and what it was measured on when that is in question.
 *
 * A straight line is measurably optimistic here: one KL journey is 3.7 km of
 * great circle and 8.1 km of road, and the Grab fare doubles with it. So the
 * two must never print identically where they sit side by side. Where a whole
 * list shares one basis there is nothing on the row to tell apart, and the
 * list says it once above instead of twenty-seven times down the page.
 *
 * ``road_km`` is not shown beside this: where the router answered it is the
 * same number as ``km``, and where it did not it is null.
 */
function distanceText(place: Place, nameTheBasis: boolean): string {
  const km = formatKm(place.km);
  if (!nameTheBasis) return km;
  return place.distance_basis === "road" ? `${km} by road` : `${km} straight line`;
}

/**
 * A pin at the point, not a search for the name.
 *
 * Several names in this set belong to two branches, and a quarter of the
 * addresses are a locality rather than a doorstep, so a name search is a coin
 * flip between them. Google's search action takes either a name or a point and
 * not both, so the point takes the query and the name goes where the user
 * actually reads it — on the link.
 */
function mapsUrl(place: Place): string {
  const point = encodeURIComponent(`${place.lat},${place.lng}`);
  return `https://www.google.com/maps/search/?api=1&query=${point}`;
}

type CopyFailure = "unsupported" | "refused";

// A copy that silently did nothing is worse than no copy button, so each way it
// can fail says so and hands the text back to be taken by hand.
const COPY_FAILURES: Record<CopyFailure, string> = {
  // No clipboard object at all: an old browser, a webview, or a page served
  // over plain http, where the API is not exposed.
  unsupported: "This browser won't give me the clipboard.",
  // There and refused: a denied permission, or a write from a tab that had lost
  // focus by the time it ran.
  refused: "The browser turned down the copy.",
};

function Toast({ message }: { message: string }) {
  return (
    <div className="toast" role="status">
      <span className="tick">
        <IcCheck size={17} />
      </span>
      <span style={{ lineHeight: 1.35 }}>{message}</span>
    </div>
  );
}

type DetailSheetProps = {
  place: Place;
  modeLabel: string;
  roomSen: number;
  adding: boolean;
  addFailed: boolean;
  onClose: () => void;
  onAdd: (place: Place) => void;
  onCopied: (message: string) => void;
};

function DetailSheet({
  place,
  modeLabel,
  roomSen,
  adding,
  addFailed,
  onClose,
  onAdd,
  onCopied,
}: DetailSheetProps) {
  const [copyFailure, setCopyFailure] = useState<CopyFailure | null>(null);
  const mealSen = place.total_sen - place.travel_sen;
  const rows: [string, string][] = [
    ["Meal estimate", `RM${fmt(mealSen)}`],
    ["Travel", place.travel_sen > 0 ? `RM${fmt(place.travel_sen)} · ${modeLabel}` : "Free · on foot"],
    ["Total outing", `RM${fmt(place.total_sen)}`],
    // Always named here: this is one place read closely, with a fare hanging
    // off the figure, so which distance produced it is part of the figure.
    ["Distance", distanceText(place, true)],
    ["Confidence", `Estimate · ${place.confidence}`],
  ];

  const overSen = place.total_sen - roomSen;
  // What a person would paste into a search box. Only about three quarters of
  // these addresses are a street address; the rest are a locality, and that is
  // what the field says, so that is what gets copied.
  const details = place.address ? `${place.name}, ${place.address}` : place.name;

  const copyDetails = async () => {
    const clipboard = navigator.clipboard;
    // Absent entirely on http and in some webviews, so this is a real branch
    // and not defensive noise.
    if (!clipboard?.writeText) {
      setCopyFailure("unsupported");
      return;
    }
    try {
      await clipboard.writeText(details);
      setCopyFailure(null);
      onCopied(place.address ? `${place.name} and its address copied.` : `${place.name} copied.`);
    } catch {
      // Nothing reached the clipboard, so nothing here may suggest it did.
      setCopyFailure("refused");
    }
  };

  return (
    <Sheet label={place.name} onClose={onClose}>
      <div className="grab" />
      <div className="sheet-head">
        <div>
          <p className="eyebrow on-ink" style={{ margin: 0 }}>
            {place.kind} · {modeLabel}
          </p>
          <h2 style={{ margin: "5px 0 0", fontSize: 20, fontWeight: 800, letterSpacing: "-.03em" }}>
            {place.name}
          </h2>
        </div>
        <div className="money" style={{ fontSize: 22 }}>RM{fmt(place.total_sen)}</div>
      </div>

      {/* Rendered exactly as the field reads. About a quarter of these name a
          locality rather than a doorstep, which is honest as it stands and is
          not something to dress up into a street address it never had. */}
      {place.address && (
        <p style={{ margin: "-8px 0 14px", fontSize: 12.5, lineHeight: 1.45, color: "rgba(233,237,233,.6)" }}>
          {place.address}
        </p>
      )}

      <p className="voice" style={{ margin: 0, fontSize: 16, lineHeight: 1.45, color: "#F1F4F0" }}>
        {place.band === "ok" &&
          "Comfortable. This leaves most of today's room for whatever else comes up."}
        {place.band === "tight" && place.share !== null &&
          `This works, but it uses ${Math.round(place.share * 100)}% of today's room. The rest of today would need to stay light.`}
        {place.band === "over" &&
          (roomSen > 0
            ? `This is RM${fmt(overSen)} over today's room. I'd have to propose a recovery scenario, and you'd have to approve it.`
            : "Today's room is already spent, so all of this would be borrowed from the days ahead.")}
      </p>

      <div className="evidence" style={{ marginTop: 16 }}>
        <span className="eyebrow on-ink" style={{ marginBottom: 2 }}>Cost breakdown</span>
        {rows.map(([label, value]) => (
          <div className="ev-row" key={label}>
            <span>{label}</span>
            <b>{value}</b>
          </div>
        ))}
      </div>

      {/* The fare above was priced on this distance, so the caveat belongs
          under it rather than only at the top of the list. */}
      {place.distance_basis === "straight_line" && (
        <p style={{ fontSize: 12, color: "rgba(233,237,233,.55)", lineHeight: 1.5, margin: "12px 0 0" }}>
          I don&apos;t have a road distance for this one, so that is the straight line between here
          and there. The road is longer than that
          {place.travel_sen > 0
            ? `, and the RM${fmt(place.travel_sen)} of travel is priced on the short figure.`
            : "."}
        </p>
      )}

      {place.note && (
        <p style={{ fontSize: 12, color: "rgba(233,237,233,.55)", lineHeight: 1.5, margin: "14px 0 0" }}>
          {place.note}
        </p>
      )}

      <div style={{ display: "flex", gap: 9, marginTop: 18 }}>
        <a
          className="btn btn-line btn-sm"
          style={{ flex: 1, textDecoration: "none" }}
          href={mapsUrl(place)}
          target="_blank"
          rel="noopener"
          aria-label={`Open ${place.name} in Google Maps`}
        >
          Open in Maps
        </a>
        <button
          type="button"
          className="btn btn-line btn-sm"
          style={{ flex: 1 }}
          onClick={copyDetails}
        >
          Copy name and address
        </button>
      </div>

      {copyFailure && (
        <p
          role="status"
          style={{ fontSize: 12, color: "rgba(233,237,233,.62)", lineHeight: 1.5, margin: "10px 0 0" }}
        >
          {COPY_FAILURES[copyFailure]} Nothing was copied, so here it is to take by hand:{" "}
          <span style={{ userSelect: "all", color: "#E7ECE7" }}>{details}</span>
        </p>
      )}

      {/* Said before the tap, not only after it. "Add to today" beside a price
          reads like money leaving, and the whole point is that none does. */}
      <p style={{ fontSize: 12, color: "rgba(233,237,233,.55)", lineHeight: 1.5, margin: "16px 0 0" }}>
        Adding this puts a draft in Activity. Today&apos;s money stays where it is until you
        confirm it, once you have actually eaten.
      </p>

      <div style={{ display: "flex", gap: 9, marginTop: 10 }}>
        <button className="btn btn-line btn-sm" style={{ flex: 1 }} onClick={onClose}>
          Close
        </button>
        <button
          type="button"
          className="btn btn-brass btn-sm"
          style={{ flex: 1 }}
          disabled={adding}
          onClick={() => onAdd(place)}
        >
          {adding ? "Adding…" : "Add to today"}
        </button>
      </div>

      {/* The sheet stays open on a failure. Closing it behind a confirmation
          the server never agreed to would leave the user believing there is a
          draft waiting for them that is not there. */}
      {addFailed && (
        <p
          role="status"
          style={{ fontSize: 12, color: "rgba(233,237,233,.62)", lineHeight: 1.5, margin: "10px 0 0" }}
        >
          I couldn&apos;t add that just now. Nothing was written, so nothing is waiting in
          Activity — try again in a moment.
        </p>
      )}
    </Sheet>
  );
}

/**
 * Self-contained on purpose: mode, halal, the spend ceiling, and geolocation
 * are a bigger filter surface than Today or Activity carry, and nothing else
 * in the app needs to share this state.
 */
export function DayPlan() {
  const [mode, setMode] = useState<Mode>("walk");
  // Not persisted, here or anywhere. A sort is a lens on one screen for one
  // look, not something the user told us about themselves — and this app
  // already has the mechanism for the durable kind, `butler_memories` with
  // kind="preference", which is where a real "I always walk, keep it cheap"
  // belongs if it is ever asked for. Quietly growing a second, invisible
  // preference store out of a segmented control is how the two end up
  // disagreeing.
  const [sort, setSort] = useState<SortId>("balanced");
  const [halalOnly, setHalalOnly] = useState(true);
  const [capSen, setCapSen] = useState<number | undefined>(undefined);
  const [origin, setOrigin] = useState({ ...KLCC, real: false });
  const [locState, setLocState] = useState<LocState>("idle");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const sheetHost = useContext(SheetHostContext);
  const addPlan = useAddPlanToToday();

  const { data, isLoading, isError } = useDayPlan({
    lat: origin.lat,
    lng: origin.lng,
    mode,
    halalOnly,
    capSen,
  });

  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(null), 3400);
    return () => clearTimeout(timer);
  }, [toast]);

  const useMyLocation = () => {
    if (!navigator.geolocation) {
      setLocState("unsupported");
      return;
    }
    setLocState("asking");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setOrigin({ lat: position.coords.latitude, lng: position.coords.longitude, real: true });
        setLocState("ok");
      },
      (error) => setLocState(failureFor(error.code)),
      { timeout: LOCATE_TIMEOUT_MS, maximumAge: 60000 },
    );
  };

  // The chip and the "Near you" header both read off the origin, so falling
  // back has to clear the located state too or one of them would still claim
  // a location that is no longer being planned from.
  const planFromKlcc = () => {
    setOrigin({ ...KLCC, real: false });
    setLocState("idle");
  };

  // A wrong number is worse than no number, so neither state guesses.
  if (isLoading || !data) {
    return (
      <div className="pad" style={{ paddingTop: 90 }}>
        <p className="voice" style={{ fontSize: 17 }}>
          {isError ? "I couldn't find places just now." : "Finding what fits today…"}
        </p>
        {isError && (
          <p style={{ fontSize: 13, color: "var(--muted)" }}>
            Nothing has changed on your ledger. Try again in a moment.
          </p>
        )}
      </div>
    );
  }

  // Re-ordered here, over the whole list the API sent — it is never truncated
  // on the way, so nothing is lost by not asking the server again. Ordering is
  // all this does: `sortPlaces` reads the figures and returns the same places,
  // so no ringgit and no minute on the page depends on which sort is on.
  const results = sortPlaces(data.places, sort);
  // Both figures are the server's own, never inferred here: on a day already
  // spent out the room is nil, and dividing to recover it would invent one.
  const roomSen = data.room_sen;
  const sliderValue = capSen ?? data.cap_sen;
  // A range input clamps a value outside its bounds without saying so, leaving
  // the knob somewhere the figure beside it does not read. So the bounds widen
  // to hold the value instead: down to nil on a spent-out day, and off the room
  // rather than off the value, which would double the scale away under a finger
  // dragging to the top.
  const minCapSen = Math.min(MIN_CAP_SEN, sliderValue);
  const maxCapSen = Math.max(roomSen * 2, sliderValue, 6000);
  // A ceiling of nil sitting inside a room of nil is arithmetic, not comfort.
  const capVerdict =
    roomSen === 0
      ? { ok: false, label: "Nothing left in today's room" }
      : sliderValue > roomSen
        ? { ok: false, label: "Above today's room" }
        : { ok: true, label: "Inside today's room" };
  // Stated by the server, never inferred: with the list empty the ceiling is
  // the obvious culprit and the wrong one whenever nothing was in range at all,
  // or whenever the halal filter took out everything that was. The counts nest,
  // so the first one that is nil is the cause.
  const outOfRange = data.nearby_count === 0;
  const filteredOut = !outOfRange && data.matching_count === 0;
  const nearbyCount = data.nearby_count;
  // The basis is per-place: one search routes some destinations and fails on
  // others. Where the whole list fell back there is nothing to tell apart down
  // the rows, and one line above says it better than twenty-seven repetitions;
  // where only some did, every row has to be named or an unlabelled figure
  // beside a labelled one is still a guess.
  const straightLineCount = results.filter(
    (place) => place.distance_basis === "straight_line",
  ).length;
  const everyPlaceFellBack = results.length > 0 && straightLineCount === results.length;
  const someFellBack = straightLineCount > 0 && !everyPlaceFellBack;
  const modeLabel = MODES.find((candidate) => candidate.id === mode)?.label ?? mode;
  const selected = results.find((place) => place.id === selectedId) ?? null;
  // Null on most lists, and that is the point: the badge is a claim, not a
  // label for row one. See bestFitId for the three things that have to hold.
  const bestFit = bestFitId(results, sort, mode);
  // A control over one row has nothing to order, and a control over none has
  // nothing to talk about.
  const canSort = results.length > 1;

  /**
   * The whole outing goes across — meal and travel, the figure on the row —
   * with the place's own confidence band rather than a percentage. What "high"
   * is worth, what date this is, and the wording that says the money has not
   * moved are all the server's, and a screen that restated any of them could
   * disagree with the draft it just made.
   *
   * The sheet closes on the answer, never on the tap: a plan that failed to
   * save must not leave a confirmation behind saying it is waiting.
   */
  const addToToday = (place: Place) => {
    addPlan.mutate(
      { name: place.name, total_sen: place.total_sen, confidence: place.confidence },
      {
        onSuccess: () => {
          setSelectedId(null);
          // Deliberately not the prototype's "pencilled in", which sounds like
          // the money has been set aside. Nothing has been set aside, so the
          // confirmation says where the draft went and what has not happened.
          setToast(
            `RM${fmt(place.total_sen)} for ${place.name} is waiting in Activity as a draft. `
            + "Today's money doesn't change until you confirm it.",
          );
        },
      },
    );
  };

  return (
    <>
      <div className="topbar">
        <div>
          <p className="eyebrow" style={{ margin: 0 }}>Near {origin.real ? "you" : "KLCC"}</p>
          <h1>What today&apos;s money can buy</h1>
        </div>
      </div>

      <div className="pad">
        <Reveal>
          <section className="capbar">
            <div className="cap-row">
              <div>
                <p className="eyebrow on-ink" style={{ margin: 0 }}>Spending ceiling</p>
                <div style={{ marginTop: 9 }}>
                  <Odometer sen={sliderValue} size={34} />
                </div>
              </div>
              <div style={{ textAlign: "right" }}>
                <p className="eyebrow on-ink" style={{ margin: 0 }}>Room today</p>
                <div className="money" style={{ fontSize: 17, color: "#EDF1ED", marginTop: 7 }}>
                  RM{fmt(roomSen)}
                </div>
              </div>
            </div>

            <input
              className="slider"
              type="range"
              min={minCapSen}
              max={maxCapSen}
              step={CAP_STEP_SEN}
              value={sliderValue}
              // The API takes a ceiling above zero, so dragging to the floor
              // asks for RM5 rather than for nothing at all.
              onChange={(event) => setCapSen(Math.max(Number(event.target.value), MIN_CAP_SEN))}
              aria-label="Spending ceiling"
            />
            <div className="cap-ticks">
              <span>RM{fmt(minCapSen)}</span>
              <span style={{ color: capVerdict.ok ? "var(--brass-lit)" : "var(--clay)" }}>
                {capVerdict.label}
              </span>
              <span>RM{fmt(maxCapSen)}</span>
            </div>

            <p className="voice" style={{ margin: "15px 0 0", fontSize: 14.5, color: "rgba(233,237,233,.78)" }}>
              {results.length === 0
                ? outOfRange
                  ? "Distance is what is in the way here, not the ceiling."
                  : filteredOut
                    ? "The halal filter is what is in the way here, not the ceiling."
                    : "Nothing fits that ceiling yet. Drag it up and I'll show you what appears."
                : `${results.length} place${results.length > 1 ? "s" : ""} fit, ${modeLabel.toLowerCase()} from ${origin.real ? "where you are" : "KLCC"}. The price on each place is the whole outing — meal and travel together.`}
            </p>
          </section>
        </Reveal>

        <Reveal delay={50} style={{ marginTop: 14 }}>
          <div className="filters">
            {MODES.map((candidate) => (
              <button
                key={candidate.id}
                type="button"
                className={`fchip ${mode === candidate.id ? "on" : ""}`}
                onClick={() => setMode(candidate.id)}
              >
                {candidate.label}
              </button>
            ))}
            <button
              type="button"
              className={`fchip ${halalOnly ? "on" : ""}`}
              onClick={() => setHalalOnly((current) => !current)}
            >
              Halal
            </button>
            <button
              type="button"
              className={`fchip ${locState === "ok" ? "on" : ""}`}
              onClick={useMyLocation}
              disabled={locState === "asking"}
            >
              {locState === "asking"
                ? "Locating…"
                : locState === "ok"
                  ? "Located"
                  : isLocFailure(locState)
                    ? LOC_FAILURES[locState].chip
                    : "Use my location"}
            </button>
          </div>
          {isLocFailure(locState) && (
            <p
              role="status"
              style={{
                margin: "10px 0 0",
                fontSize: 12,
                color: "var(--muted)",
                lineHeight: 1.5,
              }}
            >
              {/* Named from the origin actually in use: a locate that fails on
                  a second tap leaves the first one's position standing, and
                  claiming KLCC there would be the same silent lie again. */}
              {LOC_FAILURES[locState].reason},{" "}
              {origin.real
                ? "so I'm still planning from where I last found you."
                : "so I'm planning from KLCC."}{" "}
              {LOC_FAILURES[locState].advice}
            </p>
          )}
        </Reveal>

        {/* On the screen rather than tuned behind it. The order the list is in
            is a choice, and a choice the user cannot see is one they can
            neither trust nor overrule — which is exactly how a two-hour walk
            ends up at the top wearing a badge. */}
        {canSort && (
          <Reveal delay={52} style={{ marginTop: 14 }}>
            <div className="filters" style={{ marginTop: 0, alignItems: "center" }}>
              <span className="eyebrow" aria-hidden>Sort</span>
              {/* One choice of three, so radios rather than three toggles: a
                  set of aria-pressed buttons does not say that turning one on
                  turns the others off. */}
              <div
                role="radiogroup"
                aria-label="Sort by"
                style={{ display: "flex", gap: 7, flexWrap: "wrap" }}
              >
                {SORT_IDS.map((id) => (
                  <button
                    key={id}
                    type="button"
                    role="radio"
                    aria-checked={sort === id}
                    className={`fchip ${sort === id ? "on" : ""}`}
                    onClick={() => setSort(id)}
                  >
                    {SORTS[id].label}
                  </button>
                ))}
              </div>
            </div>
            <p style={{ margin: "10px 0 0", fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}>
              {SORTS[sort].explains}
            </p>
          </Reveal>
        )}

        {everyPlaceFellBack && (
          <Reveal delay={55} style={{ marginTop: 14 }}>
            <p
              role="status"
              style={{ margin: 0, fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}
            >
              I don&apos;t have road distances for any of these, so every distance below is a
              straight line. The road is longer than that, and the travel costs here are priced on
              the short figure.
            </p>
          </Reveal>
        )}

        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginTop: 18 }}>
          {results.map((place, index) => (
            <Reveal key={place.id} delay={index * 70}>
              <button
                type="button"
                className={`place ${selectedId === place.id ? "sel" : ""}`}
                // A failure belongs to the place it happened on. Left standing,
                // it would greet the next sheet with a complaint about a shop
                // the user is no longer looking at.
                onClick={() => {
                  addPlan.reset();
                  setSelectedId(place.id);
                }}
              >
                <span className="place-rank">{index + 1}</span>
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
                    <b style={{ fontSize: 15, letterSpacing: "-.02em" }}>{place.name}</b>
                    {place.id === bestFit && <span className="badge badge-best">Best fit</span>}
                    {place.band === "over" && <span className="badge badge-over">Over</span>}
                  </span>
                  <span style={{ display: "block", fontSize: 12, color: "var(--muted)", marginTop: 3 }}>
                    {place.kind} · {distanceText(place, someFellBack)} · {place.minutes} min
                  </span>
                  <span
                    style={{
                      display: "block",
                      fontSize: 12,
                      marginTop: 3,
                      color:
                        place.band === "over"
                          ? "var(--clay)"
                          : place.band === "tight"
                            ? "var(--brass)"
                            : "var(--muted)",
                    }}
                  >
                    {place.share !== null
                      ? `${Math.round(place.share * 100)}% of today's room`
                      : "Nothing left in today's room"}
                    {place.travel_sen > 0 && ` · incl. RM${fmt(place.travel_sen)} travel`}
                  </span>
                </span>
                <span style={{ textAlign: "right", flex: "none" }}>
                  <span className="money" style={{ fontSize: 18, display: "block" }}>
                    RM{fmt(place.total_sen)}
                  </span>
                  <span className="tag" style={{ color: "var(--brass)" }}>Est · {place.confidence}</span>
                </span>
              </button>
            </Reveal>
          ))}

          {results.length === 0 && (
            <Reveal>
              <div className="card-flat empty-map">
                {/* Three empty lists that look identical on screen, and only the
                    server's two counts tell them apart: a ceiling the user can
                    move, a filter the user can switch off, or a distance no
                    ceiling and no toggle will ever close. */}
                {outOfRange ? (
                  <>
                    <p className="voice" style={{ margin: 0, fontSize: 16 }}>
                      Nothing within range of here.
                    </p>
                    <p style={{ margin: "8px 0 0", fontSize: 13, color: "var(--muted)", lineHeight: 1.5 }}>
                      The demo set only covers central KL, so raising the ceiling will not fill this
                      list from where you are.
                    </p>
                    {origin.real && (
                      <button
                        type="button"
                        className="btn btn-line btn-sm"
                        style={{ marginTop: 12 }}
                        onClick={planFromKlcc}
                      >
                        Plan from KLCC instead
                      </button>
                    )}
                  </>
                ) : filteredOut ? (
                  <>
                    <p className="voice" style={{ margin: 0, fontSize: 16 }}>
                      {nearbyCount === 1
                        ? "The one place within range of here is not halal."
                        : `None of the ${nearbyCount} places within range of here are halal.`}
                    </p>
                    <p style={{ margin: "8px 0 0", fontSize: 13, color: "var(--muted)", lineHeight: 1.5 }}>
                      {/* The ceiling is the wrong thing to reach for here: it is
                          not what emptied this list, and dragging it does nothing. */}
                      Raising the ceiling will not change that. Turn Halal off to see what is
                      there, or plan from somewhere else.
                    </p>
                    <button
                      type="button"
                      className="btn btn-line btn-sm"
                      style={{ marginTop: 12 }}
                      onClick={() => setHalalOnly(false)}
                    >
                      Turn Halal off
                    </button>
                  </>
                ) : (
                  <>
                    <p className="voice" style={{ margin: 0, fontSize: 16 }}>
                      {/* The ceiling this list was filtered by, which trails the
                          slider while a newly dragged one is still in flight. */}
                      Nothing under RM{fmt(data.cap_sen)} yet.
                    </p>
                    <p style={{ margin: "8px 0 0", fontSize: 13, color: "var(--muted)", lineHeight: 1.5 }}>
                      Raise the ceiling, walk instead of riding, or eat at home — groceries usually beat
                      a delivered meal on the same money.
                    </p>
                  </>
                )}
              </div>
            </Reveal>
          )}
        </div>

        <Reveal delay={60} style={{ marginTop: 16 }}>
          <p style={{ fontSize: 11.5, color: "var(--muted-2)", lineHeight: 1.5, margin: 0 }}>
            Prices are estimates from price level and past history, never live menu prices. Places come
            from a fixed demo set here; in the build they arrive through the Maps adapter.
          </p>
        </Reveal>
      </div>

      {selected && (
        <DetailSheet
          place={selected}
          modeLabel={modeLabel}
          roomSen={roomSen}
          adding={addPlan.isPending}
          addFailed={addPlan.isError}
          onClose={() => setSelectedId(null)}
          onAdd={addToToday}
          onCopied={setToast}
        />
      )}

      {toast &&
        (sheetHost?.current ? createPortal(<Toast message={toast} />, sheetHost.current) : (
          <Toast message={toast} />
        ))}
    </>
  );
}
