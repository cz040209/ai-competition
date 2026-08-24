import type { DashboardToday } from "@kira/contracts";

import { fmt } from "../lib/money";

export type Band = "free" | "goal" | "commit" | "buffer";

const SWATCH: Record<Band, string> = {
  free: "linear-gradient(180deg,#FBF7EC,#DFCFA4)",
  goal: "linear-gradient(180deg,#E0BB74,#B58F45)",
  commit: "linear-gradient(180deg,#7FA298,#5B7C74)",
  buffer: "#43635C",
};

type ClaimLineProps = {
  data: DashboardToday;
  picked: Band | null;
  onPick: (band: Band | null) => void;
};

export function ClaimLine({ data, picked, onPick }: ClaimLineProps) {
  const goalCount = data.goals.length;
  const segments: { k: Band; v: number; cls: string; label: string; sub: string }[] = [
    { k: "free", v: data.unclaimed_sen, cls: "seg-free", label: "Unclaimed", sub: "Yours to decide" },
    {
      k: "goal",
      v: data.goal_reserve_sen,
      cls: "seg-goal",
      label: "Goal reserve",
      sub: `${goalCount} goal${goalCount === 1 ? "" : "s"}, accrued this cycle`,
    },
    {
      k: "commit",
      v: data.reserved_sen,
      cls: "seg-commit",
      label: "Committed",
      sub: `${data.commitment_count} bills before payday`,
    },
    { k: "buffer", v: data.buffer_sen, cls: "seg-buffer", label: "Buffer", sub: "Protected, not spendable" },
  ];

  return (
    <div>
      <div className="claim" role="img" aria-label="How your balance is claimed">
        {segments.map((segment, index) => (
          <button
            key={segment.k}
            className={`claim-seg ${segment.cls}`}
            style={{
              flexGrow: Math.max(segment.v, 0),
              animationDelay: `${0.35 + index * 0.09}s`,
              opacity: picked && picked !== segment.k ? 0.45 : 1,
            }}
            onClick={() => onPick(picked === segment.k ? null : segment.k)}
            aria-label={`${segment.label} RM${fmt(segment.v)}`}
          />
        ))}
      </div>
      <div className="claim-legend">
        {segments.map((segment) => (
          <button
            key={segment.k}
            className="leg"
            onClick={() => onPick(picked === segment.k ? null : segment.k)}
            style={{ opacity: picked && picked !== segment.k ? 0.38 : 1 }}
          >
            <i style={{ background: SWATCH[segment.k] }} />
            <span>
              <span className="leg-l">{segment.label}</span>
              <span className="leg-v">{fmt(segment.v)}</span>
            </span>
          </button>
        ))}
      </div>
      {picked && (
        <p
          className="voice"
          style={{
            margin: "13px 0 0",
            fontSize: 13.5,
            color: "rgba(233,237,233,.7)",
            animation: "fadeUp .5s var(--spring) both",
          }}
        >
          {segments.find((segment) => segment.k === picked)?.sub}.
        </p>
      )}
    </div>
  );
}
