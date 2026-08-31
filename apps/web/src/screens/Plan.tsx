import { useState } from "react";

import type { ForesightDriver, ForesightResponse, GoalSummary } from "@kira/contracts";

import { FanChart } from "../components/FanChart";
import { Reveal } from "../components/Reveal";
import { Ring } from "../components/Ring";
import { fmt } from "../lib/money";

type PlanProps = {
  data: ForesightResponse | undefined;
  goals?: GoalSummary[];
  isLoading: boolean;
  isError: boolean;
  onDriver: (driver: ForesightDriver) => void;
};

const SHORT = "#4E8F79";
const LONG = "#A9853F";

function percent(basisPoints: number): string {
  return `${Math.round(basisPoints / 100)}%`;
}

function formatDate(iso: string): string {
  return new Intl.DateTimeFormat("en-MY", {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(`${iso}T00:00:00`));
}

function driverCopy(driver: ForesightDriver, goalNames: Map<string, string>): string {
  const amount = `RM${fmt(Math.abs(driver.lever.delta.sen))}`;
  if (driver.lever.kind === "goal_monthly") {
    const name = goalNames.get(driver.lever.target_id) ?? "this goal";
    return `${driver.lever.delta.sen >= 0 ? "Put" : "Take"} ${amount} ${driver.lever.delta.sen >= 0 ? "more into" : "out of"} ${name} each month`;
  }
  if (driver.lever.kind === "daily_spend") {
    return `Spend ${amount} ${driver.lever.delta.sen < 0 ? "less" : "more"} each day`;
  }
  return `${driver.lever.delta.sen < 0 ? "Reduce" : "Raise"} a commitment by ${amount}`;
}

export function Plan({ data, goals = [], isLoading, isError, onDriver }: PlanProps) {
  const [section, setSection] = useState<"overview" | "foresight">("overview");

  const names = new Map(goals.map((goal) => [goal.id, goal.name]));
  const details = new Map(goals.map((goal) => [goal.id, goal]));
  const notReady = !data || data.profile_days < 14 || data.outlooks.length === 0;

  return (
    <>
      <div className="topbar">
        <div>
          <p className="eyebrow" style={{ margin: 0 }}>Plan</p>
          <h1>{section === "overview" ? "Your money, deliberately" : "The road ahead"}</h1>
        </div>
        {section === "foresight" && data && <span className="plan-horizon">{data.horizon_days} days</span>}
      </div>

      <div className="pad">
        {section === "overview" ? (
          <Reveal>
            <section className="plan-empty" aria-label="Plan overview">
              <p className="eyebrow" style={{ margin: 0 }}>Your commitments and goals</p>
              <h2>Keep the next move clear.</h2>
              <p>
                Your daily number protects bills, your buffer and the goals you are building toward.
                Foresight is available when you want to explore possible futures.
              </p>
              {goals.length > 0 && (
                <div style={{ display: "grid", gap: 9, marginTop: 18 }}>
                  {goals.map((goal) => (
                    <div
                      key={goal.id}
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        gap: 12,
                        paddingTop: 10,
                        borderTop: "1px solid rgba(35,52,45,.1)",
                      }}
                    >
                      <span>
                        <b style={{ display: "block", fontSize: 14 }}>{goal.name}</b>
                        <small style={{ color: "var(--muted)" }}>
                          RM{fmt(goal.monthly_sen)} each month
                        </small>
                      </span>
                      <b style={{ fontSize: 13.5, whiteSpace: "nowrap" }}>
                        RM{fmt(goal.saved_sen)} saved
                      </b>
                    </div>
                  ))}
                </div>
              )}
              <button
                className="btn btn-primary btn-sm"
                style={{ marginTop: 20 }}
                onClick={() => setSection("foresight")}
              >
                Open Foresight
              </button>
            </section>
          </Reveal>
        ) : isLoading || !data ? (
          <div style={{ paddingTop: 28 }}>
            <button className="btn btn-ghost btn-sm" onClick={() => setSection("overview")}>
              Back to plan
            </button>
            <p className="voice" style={{ fontSize: 17, marginTop: 24 }}>
              {isError ? "I couldn't reach your forecast just now." : "Looking ahead…"}
            </p>
            {isError && (
              <p style={{ fontSize: 13, color: "var(--muted)" }}>
                Nothing has changed. Pull down to try again.
              </p>
            )}
          </div>
        ) : notReady ? (
          <>
            <button className="btn btn-ghost btn-sm" onClick={() => setSection("overview")}>
              Back to plan
            </button>
            <Reveal style={{ marginTop: 18 }}>
              <section className="plan-empty">
                <p className="eyebrow" style={{ margin: 0 }}>Still learning</p>
                <h2>Not enough history to forecast yet.</h2>
                <p>
                  Confirmed spending gives Kira a pattern to learn. Once there is enough of it,
                  this will show a range of plausible futures — not a made-up certainty.
                </p>
              </section>
            </Reveal>
          </>
        ) : (
          <>
            <button className="btn btn-ghost btn-sm" onClick={() => setSection("overview")}>
              Back to plan
            </button>
            <Reveal style={{ marginTop: 18 }}>
              <section className="plan-forecast">
                <div className="plan-card-head">
                  <div>
                    <p className="eyebrow" style={{ margin: 0 }}>Balance forecast</p>
                    <h2>There is more than one future.</h2>
                  </div>
                  <span className="plan-key"><i /> likely range</span>
                </div>
                <FanChart dates={data.dates} p10={data.p10} p50={data.p50} p90={data.p90} />
              </section>
            </Reveal>

            <Reveal delay={45} style={{ marginTop: 18 }}>
              <section className="plan-goals">
                <div className="plan-card-head">
                  <div>
                    <p className="eyebrow" style={{ margin: 0 }}>Goal outlook</p>
                    <h2>What your plan is likely to reach</h2>
                  </div>
                </div>
                <div className="plan-goal-grid">
                  {data.outlooks.map((outlook) => {
                    const goal = details.get(outlook.goal_id);
                    const name = names.get(outlook.goal_id) ?? "Your goal";
                    return (
                      <article className="plan-goal" key={outlook.goal_id}>
                        <div className="plan-ring">
                          <Ring
                            pct={outlook.probability_bp / 10000}
                            size={76}
                            stroke={goal?.horizon === "short" ? SHORT : LONG}
                          />
                          <b>{percent(outlook.probability_bp)}</b>
                        </div>
                        <div>
                          <b>{name}</b>
                          <span>by {formatDate(outlook.target_date)}</span>
                          {outlook.median_shortfall.sen > 0 && (
                            <small>Typical gap: RM{fmt(outlook.median_shortfall.sen)}</small>
                          )}
                        </div>
                      </article>
                    );
                  })}
                </div>
                <p className="plan-assumption">{data.assumption}</p>
              </section>
            </Reveal>

            <Reveal delay={85} style={{ marginTop: 18 }}>
              <section className="plan-drivers">
                <div className="plan-card-head">
                  <div>
                    <p className="eyebrow" style={{ margin: 0 }}>Changes worth considering</p>
                    <h2>What moves the first goal most</h2>
                  </div>
                </div>
                {data.drivers.length === 0 ? (
                  <p className="plan-muted">There is no useful change to suggest from this forecast yet.</p>
                ) : (
                  <div className="driver-list">
                    {data.drivers.map((driver) => (
                      <article className="driver" key={`${driver.lever.kind}-${driver.lever.target_id}-${driver.lever.delta.sen}`}>
                        <div>
                          <b>{driverCopy(driver, names)}</b>
                          <span>{percent(driver.probability_bp_before)} → {percent(driver.probability_bp_after)}</span>
                        </div>
                        <button className="btn btn-line btn-sm" onClick={() => onDriver(driver)}>
                          Let Kira do it
                        </button>
                      </article>
                    ))}
                  </div>
                )}
              </section>
            </Reveal>
          </>
        )}
      </div>
    </>
  );
}
