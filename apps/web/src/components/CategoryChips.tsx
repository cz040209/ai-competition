import { useCallback, useEffect, useRef, useState } from "react";

import type { CategorySummary } from "@kira/contracts";

import { fmt } from "../lib/money";

type CategoryChipsProps = {
  categories: CategorySummary[];
  active: string | null;
  onPick: (slug: string | null) => void;
  totalSen: number;
};

/**
 * One chip per category present this cycle. Radio semantics, not buttons:
 * exactly one filter is in force at a time, and a screen reader should say so.
 */
export function CategoryChips({ categories, active, onPick, totalSen }: CategoryChipsProps) {
  const barRef = useRef<HTMLDivElement>(null);
  const [edges, setEdges] = useState({ start: false, end: false });

  const measure = useCallback(() => {
    const bar = barRef.current;
    if (!bar) return;
    const hidden = bar.scrollWidth - bar.clientWidth;
    setEdges({
      start: bar.scrollLeft > 4,
      end: hidden > 4 && bar.scrollLeft < hidden - 4,
    });
  }, []);

  useEffect(() => {
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [measure, categories.length]);

  const chips: [string | null, string, number][] = [
    [null, "All", totalSen],
    ...categories.map(
      (category) =>
        [category.slug, category.label, category.spent_this_cycle_sen] as [string, string, number],
    ),
  ];

  return (
    <div
      ref={barRef}
      className={`catbar ${edges.start ? "fade-start" : ""} ${edges.end ? "fade-end" : ""}`.trim()}
      role="radiogroup"
      aria-label="Filter by category"
      onScroll={measure}
    >
      {chips.map(([slug, label, sen]) => (
        <button
          key={slug ?? "all"}
          type="button"
          role="radio"
          aria-checked={active === slug}
          className={`cat ${active === slug ? "on" : ""}`}
          onClick={() => onPick(slug)}
        >
          {label}
          <span className="cat-sen">RM{fmt(sen)}</span>
        </button>
      ))}
    </div>
  );
}
