import { useEffect, useRef, useState } from "react";

import type { ButlerThread, Capture } from "@kira/contracts";
import { useQueryClient } from "@tanstack/react-query";

import { ask, decide, type ButlerEvent, type EvidenceRow } from "../api/butler";
import { activityKey, butlerThreadKey, dashboardTodayKey, memoriesKey } from "../api/hooks";
import { IcArrow, IcCam, IcImg, IcMic } from "../components/Icons";
import { ScanSheet } from "../components/ScanSheet";
import { VoiceSheet } from "../components/VoiceSheet";
import { takeButlerHandoff } from "../lib/butlerHandoff";

type Attachment = (Capture & { preview?: string }) | null;

type Turn = {
  role: "user" | "kira";
  text: string;
  evidence: EvidenceRow[];
  attachment?: Attachment;
  approval?: { id: string; summary: string; tool: string } | null;
  applied?: boolean;
};

/** What the graph is doing right now, before there is an answer to show. */
type Live = {
  thinking: string;
  tools: string[];
  evidence: EvidenceRow[];
  text: string;
  approval: { id: string; summary: string; tool: string } | null;
};

const EMPTY: Live = { thinking: "", tools: [], evidence: [], text: "", approval: null };

const PROMPTS = [
  "Can I afford RM60 dinner tonight?",
  "Why did safe-to-spend drop?",
  "How is my wedding goal doing?",
  "What bills are due?",
];

type ButlerProps = {
  thread: ButlerThread | undefined;
  isLoading: boolean;
};

export function Butler({ thread, isLoading }: ButlerProps) {
  const queryClient = useQueryClient();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [live, setLive] = useState<Live | null>(null);
  const [text, setText] = useState("");
  const [sheet, setSheet] = useState<"scan" | "voice" | null>(null);
  const [attachment, setAttachment] = useState<Attachment>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const loaded = useRef(false);

  // The thread is the record; the local turns are this session's view of it.
  useEffect(() => {
    if (!thread || loaded.current) return;
    loaded.current = true;
    const pending = thread.pending_approvals.at(-1);
    setTurns(
      thread.messages.map((message, index) => ({
        role: message.role === "user" ? "user" : "kira",
        text: message.content,
        evidence: message.evidence as EvidenceRow[],
        attachment: (message.attachment as Attachment) ?? null,
        approval:
          pending && index === thread.messages.length - 1 && message.role !== "user"
            ? { id: pending.id, summary: pending.summary, tool: pending.tool }
            : null,
      })),
    );
  }, [thread]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns, live]);

  const consume = async (events: AsyncGenerator<ButlerEvent>) => {
    let state: Live = { ...EMPTY };
    setLive(state);
    for await (const event of events) {
      switch (event.type) {
        case "thinking":
          state = { ...state, thinking: event.text };
          break;
        case "tool":
          state = { ...state, tools: [...state.tools, event.label] };
          break;
        case "evidence":
          state = { ...state, evidence: [...state.evidence, ...event.rows] };
          break;
        case "token":
          state = { ...state, text: state.text + event.text };
          break;
        case "approval":
          state = {
            ...state,
            approval: { id: event.approval_id, summary: event.summary, tool: event.tool },
          };
          break;
        case "done":
          setTurns((previous) => [
            ...previous,
            {
              role: "kira",
              text: event.answer || state.text,
              evidence: event.evidence.length ? event.evidence : state.evidence,
              approval: state.approval,
              applied: Boolean(event.applied),
            },
          ]);
          break;
        case "error":
          setTurns((previous) => [
            ...previous,
            { role: "kira", text: `Something broke: ${event.message}`, evidence: [] },
          ]);
          break;
      }
      setLive({ ...state });
    }
    setLive(null);
    // A turn may have applied a write, so every number on screen is suspect.
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: dashboardTodayKey }),
      queryClient.invalidateQueries({ queryKey: activityKey }),
      queryClient.invalidateQueries({ queryKey: memoriesKey }),
      queryClient.invalidateQueries({ queryKey: butlerThreadKey }),
    ]);
  };

  const send = (question: string, attached: Attachment = attachment) => {
    const trimmed = question.trim();
    if (!trimmed || live) return;
    setSheet(null);
    setAttachment(null);
    setText("");
    setTurns((previous) => [
      ...previous,
      { role: "user", text: trimmed, evidence: [], attachment: attached },
    ]);
    void consume(ask(trimmed, attached ?? undefined));
  };

  /**
   * A question handed over from another screen, asked as though it were typed
   * here — because it was, a tab ago, and re-wording it would be answering a
   * sentence the user never wrote.
   *
   * Held until the history has arrived: the effect above replaces the turns
   * wholesale on first load, and a question sent before it would drop out of
   * the conversation the moment the thread landed. The slot empties on the
   * take, so the re-runs a strict-mode mount causes find nothing left.
   */
  useEffect(() => {
    if (isLoading) return;
    const handed = takeButlerHandoff();
    if (handed) send(handed);
  }, [isLoading]);

  const respond = (id: string, action: "accept" | "reject") => {
    if (live) return;
    setTurns((previous) =>
      previous.map((turn) => (turn.approval?.id === id ? { ...turn, approval: null } : turn)),
    );
    void consume(decide({ id }, action));
  };

  const busy = live !== null;

  return (
    <>
      <div className="topbar" style={{ paddingBottom: 10 }}>
        <div>
          <p className="eyebrow on-ink" style={{ margin: 0 }}>
            Butler
          </p>
          <h1 style={{ color: "#EDF1ED" }}>Ask me anything about your money</h1>
        </div>
      </div>

      <div
        className="pad"
        style={{ paddingBottom: 176, display: "flex", flexDirection: "column", gap: 20 }}
      >
        {turns.length === 0 && !isLoading && (
          <p
            className="voice"
            style={{
              fontSize: 20,
              lineHeight: 1.45,
              color: "rgba(233,237,233,.82)",
              margin: "6px 0 0",
            }}
          >
            I answer from your confirmed transactions only, and I show you the numbers I used.
            I can&rsquo;t move money — that isn&rsquo;t mine to do.
          </p>
        )}

        {turns.map((turn, index) =>
          turn.role === "user" ? (
            <div className="bubble-user" key={index}>
              {turn.attachment && <AttachmentTag attachment={turn.attachment} />}
              <span style={{ display: "block" }}>{turn.text}</span>
            </div>
          ) : (
            <div className="bubble-kira" key={index}>
              <Answer text={turn.text} />
              <Evidence rows={turn.evidence} />
              {turn.approval && (
                <Approval
                  summary={turn.approval.summary}
                  busy={busy}
                  onAccept={() => respond(turn.approval!.id, "accept")}
                  onReject={() => respond(turn.approval!.id, "reject")}
                />
              )}
            </div>
          ),
        )}

        {live && (
          <div className="bubble-kira">
            {live.tools.map((label, index) => (
              <p className="tool-line" key={`${label}-${index}`} style={{ margin: "0 0 7px" }}>
                <span className="dot" />
                {label}
              </p>
            ))}
            {live.text ? (
              <Answer text={live.text} />
            ) : (
              <span className="thinking" aria-label={live.thinking || "Thinking"}>
                <i />
                <i />
                <i />
              </span>
            )}
            <Evidence rows={live.evidence} />
          </div>
        )}

        <div ref={endRef} />

        {turns.length === 0 && !isLoading && (
          <div className="chips" style={{ marginTop: 4 }}>
            {PROMPTS.map((prompt) => (
              <button className="chip" key={prompt} onClick={() => send(prompt)}>
                {prompt}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="composer">
        {attachment && <AttachmentTag attachment={attachment} />}
        <input
          value={text}
          placeholder="Ask, speak, or show me a receipt…"
          aria-label="Ask Kira"
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") send(text);
          }}
        />
        <button
          className="cbtn"
          onClick={() => setSheet("scan")}
          disabled={busy}
          aria-label="Scan a receipt"
        >
          <IcCam size={18} w={1.9} />
        </button>
        <button
          className="cbtn"
          onClick={() => setSheet("voice")}
          disabled={busy}
          aria-label="Record a voice note"
        >
          <IcMic size={18} w={1.9} />
        </button>
        <button className="send" onClick={() => send(text)} disabled={busy} aria-label="Send">
          <IcArrow size={18} w={2.1} />
        </button>
      </div>

      {sheet === "scan" && (
        <ScanSheet
          onClose={() => setSheet(null)}
          onAsk={(question, read) => send(question, read)}
        />
      )}
      {sheet === "voice" && (
        <VoiceSheet
          onClose={() => setSheet(null)}
          onAsk={(question, read) => send(question, read)}
        />
      )}
    </>
  );
}

/** The first line is the answer; the rest is the reasoning behind it. */
function Answer({ text }: { text: string }) {
  const [head, ...rest] = text.split("\n");
  return (
    <>
      <p className="kira-say">{head}</p>
      {rest.length > 0 && <p className="kira-sub">{rest.join(" ")}</p>}
    </>
  );
}

/**
 * Built from the rows executed tools returned, never written by the model.
 * That is what stops the panel drifting from what actually happened.
 */
function Evidence({ rows }: { rows: EvidenceRow[] }) {
  if (rows.length === 0) return null;
  return (
    <div className="evidence">
      <span className="eyebrow on-ink" style={{ marginBottom: 2 }}>
        What I used
      </span>
      {rows.map(([label, value], index) => (
        <div className="ev-row" key={`${label}-${index}`}>
          <span>{label}</span>
          <b>{value}</b>
        </div>
      ))}
    </div>
  );
}

function Approval({
  summary,
  busy,
  onAccept,
  onReject,
}: {
  summary: string;
  busy: boolean;
  onAccept: () => void;
  onReject: () => void;
}) {
  return (
    <div className="approval">
      <span className="eyebrow on-ink" style={{ color: "var(--brass-lit)" }}>
        Proposed change · not applied
      </span>
      <p style={{ margin: "10px 0 0", fontSize: 14.5, lineHeight: 1.5 }}>{summary}</p>
      <div style={{ display: "flex", gap: 8, marginTop: 14 }}>
        <button className="btn btn-brass btn-sm" style={{ flex: 1 }} disabled={busy} onClick={onAccept}>
          Approve
        </button>
        <button className="btn btn-sm btn-ghost" disabled={busy} onClick={onReject}>
          Reject
        </button>
      </div>
      <p style={{ margin: "11px 0 0", fontSize: 11.5, color: "rgba(233,237,233,.45)", lineHeight: 1.45 }}>
        Nothing changes until you approve. Your buffer and protected bills are off limits either way.
      </p>
    </div>
  );
}

function AttachmentTag({ attachment }: { attachment: Attachment }) {
  if (!attachment) return null;
  if (attachment.preview) {
    return <img className="att-img" src={attachment.preview} alt="The receipt you sent" />;
  }
  return (
    <span className="att">
      {attachment.kind === "voice" ? <IcMic size={14} /> : <IcImg size={14} />}
      {attachment.kind === "voice" ? "Voice note" : "Receipt"} · {attachment.merchant}
    </span>
  );
}
