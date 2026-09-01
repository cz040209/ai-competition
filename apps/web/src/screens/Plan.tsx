import { useState } from "react";

import { DayPlan } from "./DayPlan";
import { GoalPlanner } from "./goals/GoalPlanner";

export type PlanView = "daily" | "goals";

/** Shared PLAN shell. Daily remains the existing planner; Goals arrives next. */
export function Plan({ initialView = "daily" }: { initialView?: PlanView }) {
  const [view, setView] = useState<PlanView>(initialView);

  return (
    <>
      <div className="plan-view-switch">
        <div className="seg-toggle" role="tablist" aria-label="Plan view">
          <span
            className="seg-thumb"
            aria-hidden="true"
            style={{
              transform:
                view === "goals" ? "translateX(calc(100% + 5px))" : "translateX(0)",
            }}
          />
          <button
            id="plan-daily-tab"
            className={`seg-btn ${view === "daily" ? "on" : ""}`}
            type="button"
            role="tab"
            aria-selected={view === "daily"}
            aria-controls="plan-daily-panel"
            onClick={() => setView("daily")}
          >
            Daily
          </button>
          <button
            id="plan-goals-tab"
            className={`seg-btn ${view === "goals" ? "on" : ""}`}
            type="button"
            role="tab"
            aria-selected={view === "goals"}
            aria-controls="plan-goals-panel"
            onClick={() => setView("goals")}
          >
            Goals
          </button>
        </div>
      </div>

      {view === "daily" ? (
        <div id="plan-daily-panel" role="tabpanel" aria-labelledby="plan-daily-tab">
          <DayPlan />
        </div>
      ) : (
        <div
          id="plan-goals-panel"
          role="tabpanel"
          aria-labelledby="plan-goals-tab"
        >
          <GoalPlanner />
        </div>
      )}
    </>
  );
}
