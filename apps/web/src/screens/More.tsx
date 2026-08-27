import { useState } from "react";

import type { Memory } from "@kira/contracts";

import { useCorrectMemory, useForgetMemory } from "../api/hooks";
import { IcTrash } from "../components/Icons";
import { Reveal } from "../components/Reveal";

const KIND_BLURB: Record<string, string> = {
  preference: "how you want to be told things",
  constraint: "a rule you set",
  context: "something true about your life",
  person: "someone in your money",
  pattern: "something I noticed",
};

const WHEN = new Intl.DateTimeFormat("en-MY", { day: "numeric", month: "short" });

type MoreProps = {
  memories: Memory[] | undefined;
  isLoading: boolean;
};

/**
 * Everything Kira believes about you, in one list you can edit.
 *
 * Memory that cannot be read back is memory you have to trust blindly, so the
 * correction and the delete are the feature as much as the remembering is.
 */
export function More({ memories, isLoading }: MoreProps) {
  return (
    <>
      <div className="topbar">
        <div>
          <p className="eyebrow" style={{ margin: 0 }}>
            More
          </p>
          <h1>What Kira remembers</h1>
        </div>
      </div>

      <div className="pad">
        <Reveal>
          <section className="card">
            <p className="voice" style={{ margin: 0, fontSize: 15.5, lineHeight: 1.5 }}>
              These shape every answer. If one of them is wrong, correct it — I would rather be
              told than keep repeating it.
            </p>
          </section>
        </Reveal>

        <Reveal delay={80} style={{ marginTop: 14 }}>
          <section className="card">
            {isLoading && <p className="mem-meta">Reading…</p>}
            {!isLoading && (memories?.length ?? 0) === 0 && (
              <p className="mem-meta" style={{ margin: 0 }}>
                Nothing yet. Tell me something in the Butler and it will land here.
              </p>
            )}
            {memories?.map((memory) => (
              <MemoryRow key={memory.id} memory={memory} />
            ))}
          </section>
        </Reveal>

        <Reveal delay={160} style={{ marginTop: 14 }}>
          <section className="card">
            <p className="eyebrow" style={{ margin: 0 }}>
              Still to come
            </p>
            <p style={{ margin: "9px 0 0", fontSize: 13.5, color: "var(--muted)", lineHeight: 1.5 }}>
              Bills, accounts, and the full audit trail.
            </p>
          </section>
        </Reveal>
      </div>
    </>
  );
}

function MemoryRow({ memory }: { memory: Memory }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(memory.fact);
  const correct = useCorrectMemory();
  const forget = useForgetMemory();

  return (
    <div className="mem">
      <div className="mem-head">
        <span className="mem-kind">{memory.kind}</span>
        <span className="mem-meta" style={{ margin: 0 }}>
          {memory.confidence}% sure
        </span>
      </div>

      {editing ? (
        <>
          <input
            className="mem-input"
            style={{ marginTop: 7 }}
            value={draft}
            aria-label="Correct this memory"
            onChange={(event) => setDraft(event.target.value)}
          />
          <div className="mem-acts">
            <button
              className="btn btn-brass btn-sm"
              disabled={correct.isPending || !draft.trim()}
              onClick={() =>
                correct.mutate(
                  { id: memory.id, fact: draft.trim() },
                  { onSuccess: () => setEditing(false) },
                )
              }
            >
              Save
            </button>
            <button
              className="btn btn-sm btn-ghost"
              onClick={() => {
                setDraft(memory.fact);
                setEditing(false);
              }}
            >
              Cancel
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="mem-fact">{memory.fact}</p>
          <p className="mem-meta">
            {KIND_BLURB[memory.kind] ?? memory.kind} · learned {WHEN.format(new Date(memory.created_at))}
          </p>
          <div className="mem-acts">
            <button className="btn btn-sm btn-ghost" onClick={() => setEditing(true)}>
              Correct
            </button>
            <button
              className="btn btn-sm btn-ghost"
              disabled={forget.isPending}
              aria-label={`Forget: ${memory.fact}`}
              onClick={() => forget.mutate(memory.id)}
            >
              <IcTrash size={14} /> Forget
            </button>
          </div>
        </>
      )}
    </div>
  );
}
