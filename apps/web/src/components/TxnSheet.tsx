import type { Transaction } from "@kira/contracts";

import { fmt } from "../lib/money";
import { SourceIcon, sourceLabel } from "./TxnRow";

const DAY = new Intl.DateTimeFormat("en-MY", { weekday: "long", day: "numeric", month: "long" });

type TxnSheetProps = {
  txn: Transaction;
  onUnconfirm: (id: string) => void;
  onClose: () => void;
  busy: boolean;
};

export function TxnSheet({ txn, onUnconfirm, onClose, busy }: TxnSheetProps) {
  const rows: [string, string][] = [
    ["Category", txn.category_label],
    ["Day", DAY.format(new Date(`${txn.occurred_on}T00:00:00`))],
    ["Captured by", sourceLabel(txn.source)],
    ...(txn.note ? ([["Kira's note", txn.note]] as [string, string][]) : []),
  ];

  return (
    <>
      <div className="sheet-head">
        <div>
          <span className="tag" style={{ color: "var(--brass)" }}>
            <SourceIcon source={txn.source} size={11} /> On your ledger
          </span>
          <h2 style={{ margin: "6px 0 0", fontSize: 21, letterSpacing: "-.03em" }}>
            {txn.merchant}
          </h2>
        </div>
        <div className="money" style={{ fontSize: 22 }}>RM{fmt(txn.amount_sen)}</div>
      </div>

      <div style={{ display: "grid", gap: 8 }}>
        {rows.map(([label, value], index) => (
          <div
            key={label}
            style={{
              display: "flex",
              justifyContent: "space-between",
              gap: 14,
              padding: "11px 13px",
              background: "rgba(233,237,233,.07)",
              borderRadius: 11,
              fontSize: 13,
              animation: `rowIn .45s var(--spring) ${index * 55}ms both`,
            }}
          >
            <span style={{ color: "rgba(233,237,233,.6)", flex: "none" }}>{label}</span>
            <b style={{ textAlign: "right" }}>{value}</b>
          </div>
        ))}
      </div>

      <p
        style={{
          fontSize: 12.5,
          color: "rgba(233,237,233,.62)",
          margin: "14px 0 0",
          lineHeight: 1.5,
        }}
      >
        Counted since {DAY.format(new Date(`${txn.occurred_on}T00:00:00`))}. Move it back and
        today&apos;s safe-to-spend returns to what it was.
      </p>

      <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
        <button
          className="btn btn-brass btn-sm"
          style={{ flex: 1 }}
          disabled={busy}
          onClick={() => onUnconfirm(txn.id)}
        >
          {busy ? "Moving…" : "Move back to drafts"}
        </button>
        <button className="btn btn-line btn-sm" onClick={onClose}>
          Close
        </button>
      </div>
    </>
  );
}
