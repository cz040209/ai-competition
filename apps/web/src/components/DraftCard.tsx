import { useState } from "react";

import type { Transaction } from "@kira/contracts";

import { fmt } from "../lib/money";
import { SourceIcon, sourceLabel } from "./TxnRow";

type DraftCardProps = {
  draft: Transaction;
  onConfirm: (id: string) => void;
  onDiscard: (id: string) => void;
  settling: boolean;
};

/** A read Kira is not yet sure enough to count. Every field is visible before it does. */
export function DraftCard({ draft, onConfirm, onDiscard, settling }: DraftCardProps) {
  const [open, setOpen] = useState(false);
  const confidence = draft.confidence ?? 100;

  return (
    <div className="draft">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <span className="tag" style={{ color: "var(--brass)" }}>
            <SourceIcon source={draft.source} size={11} /> {sourceLabel(draft.source)}
          </span>
          <b style={{ display: "block", fontSize: 15.5, letterSpacing: "-.02em", marginTop: 5 }}>
            {draft.merchant}
          </b>
          <span style={{ fontSize: 12.5, color: "var(--muted)" }}>{draft.category_label}</span>
        </div>
        <div className="money" style={{ fontSize: 20 }}>RM{fmt(draft.amount_sen)}</div>
      </div>

      <div className="conf">
        <i style={{ width: `${confidence}%` }} />
      </div>
      <p className="voice" style={{ margin: "9px 0 0", fontSize: 13, color: "var(--muted)" }}>
        {confidence}% sure. {draft.note}
      </p>

      {open && (
        <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
          {(
            [
              ["Merchant", draft.merchant],
              ["Amount", `RM${fmt(draft.amount_sen)}`],
              ["Category", draft.category],
              ["Date", draft.occurred_on],
            ] as [string, string][]
          ).map(([label, value], index) => (
            <div
              key={label}
              style={{
                display: "flex",
                justifyContent: "space-between",
                padding: "10px 12px",
                background: "rgba(15,28,26,.04)",
                borderRadius: 11,
                fontSize: 13,
                animation: `rowIn .45s var(--spring) ${index * 60}ms both`,
              }}
            >
              <span style={{ color: "var(--muted)" }}>{label}</span>
              <b>{value}</b>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        <button
          className="btn btn-primary btn-sm"
          style={{ flex: 1 }}
          disabled={settling}
          onClick={() => onConfirm(draft.id)}
        >
          Confirm
        </button>
        <button className="btn btn-line btn-sm" onClick={() => setOpen((shown) => !shown)}>
          {open ? "Close" : "Details"}
        </button>
        <button className="btn btn-ghost btn-sm" disabled={settling} onClick={() => onDiscard(draft.id)}>
          Discard
        </button>
      </div>
    </div>
  );
}
