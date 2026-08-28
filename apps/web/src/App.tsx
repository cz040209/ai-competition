import { useEffect, useRef, useState, type CSSProperties } from "react";

import {
  useActivity,
  useButlerThread,
  useConfirmDraft,
  useDashboardToday,
  useDiscardDraft,
  useMemories,
  useUnconfirm,
} from "./api/hooks";
import { IcActivity, IcMore, IcPlan, IcSpark, IcToday } from "./components/Icons";
import { Motes } from "./components/Motes";
import { NavItem } from "./components/NavItem";
import { ScrollContext } from "./components/Reveal";
import { SheetHostContext } from "./components/Sheet";
import { Activity } from "./screens/Activity";
import { Butler } from "./screens/Butler";
import { DayPlan } from "./screens/DayPlan";
import { Login } from "./screens/Login";
import { More } from "./screens/More";
import { Today } from "./screens/Today";

export type Tab = "today" | "activity" | "butler" | "plan" | "more";

const TABS: Tab[] = ["today", "activity", "butler", "plan", "more"];

export function App() {
  const [tab, setTab] = useState<Tab>("today");
  const [dir, setDir] = useState(0);
  const [boot, setBoot] = useState(true);
  const [signedIn, setSignedIn] = useState(false);
  const viewRef = useRef<HTMLDivElement>(null);
  const screenRef = useRef<HTMLDivElement>(null);
  const dashboard = useDashboardToday(signedIn);
  const [category, setCategory] = useState<string | null>(null);
  const activity = useActivity(signedIn && tab === "activity", category);
  // The thread is fetched once the user signs in, not on first open: the
  // Butler tab should already have its history when it appears.
  const butler = useButlerThread(signedIn);
  const memories = useMemories(signedIn && tab === "more");
  const confirm = useConfirmDraft();
  const discard = useDiscardDraft();
  const unconfirm = useUnconfirm();
  const settlingId =
    [confirm, discard, unconfirm].find((mutation) => mutation.isPending)?.variables ?? null;

  useEffect(() => {
    const timer = setTimeout(() => setBoot(false), 2500);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    viewRef.current?.scrollTo?.({ top: 0, behavior: "auto" });
  }, [tab]);

  // Scroll-linked parallax: write a CSS variable, never re-render.
  useEffect(() => {
    const view = viewRef.current;
    const screen = screenRef.current;
    if (!view || !screen) return;
    let frame = 0;
    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        screen.style.setProperty("--sy", String(view.scrollTop));
        frame = 0;
      });
    };
    view.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      view.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(frame);
    };
  }, [tab]);

  const go = (next: Tab) => {
    if (next === tab) return;
    const from = TABS.indexOf(tab);
    const to = TABS.indexOf(next);
    setDir(next === "butler" || tab === "butler" ? 0 : to > from ? 1 : -1);
    setTab(next);
  };

  const dark = tab === "butler";

  return (
    <div className="kira-root">
      <div className="stage-head">
        <div className="lockup">
          <b>Kira</b>
          <span>AI money butler</span>
        </div>
      </div>

      <div className="device">
        <div
          className={`screen ${dark ? "dim" : ""}`}
          ref={screenRef}
          style={{ "--dir": dir } as CSSProperties}
        >
          <Motes />

          {boot && (
            <div className="boot">
              <div style={{ textAlign: "center" }}>
                <div className="boot-mark">
                  {"KIRA".split("").map((character, index) => (
                    <span key={index} style={{ animationDelay: `${0.07 * index}s` }}>{character}</span>
                  ))}
                </div>
                <div className="boot-rule" />
                <p className="boot-sub">AI money butler</p>
              </div>
            </div>
          )}

          <div className="statusbar">
            <span>12:47</span>
            <span style={{ display: "flex", gap: 7, alignItems: "center" }}>
              <span className="sb-dots"><i /><i /><i /><i /></span>
              <span className="sb-batt" />
            </span>
          </div>

          <SheetHostContext.Provider value={screenRef}>
            <ScrollContext.Provider value={viewRef}>
              <div className="viewport" ref={viewRef}>
                <div className="page" key={signedIn ? tab : "login"}>
                  {!signedIn && <Login onSignedIn={() => setSignedIn(true)} />}
                  {signedIn && tab === "today" && (
                    <Today
                      data={dashboard.data}
                      isLoading={dashboard.isLoading}
                      isError={dashboard.isError}
                      go={go}
                    />
                  )}
                  {signedIn && tab === "activity" && (
                    <Activity
                      data={activity.data}
                      isLoading={activity.isLoading}
                      isError={activity.isError}
                      onConfirm={confirm.mutate}
                      onDiscard={discard.mutate}
                      onUnconfirm={unconfirm.mutate}
                      settlingId={settlingId}
                      category={category}
                      onCategory={setCategory}
                      go={go}
                    />
                  )}
                  {signedIn && tab === "butler" && (
                    <Butler thread={butler.data} isLoading={butler.isLoading} />
                  )}
                  {signedIn && tab === "plan" && <DayPlan />}
                  {signedIn && tab === "more" && (
                    <More memories={memories.data} isLoading={memories.isLoading} />
                  )}
                </div>
              </div>
            </ScrollContext.Provider>
          </SheetHostContext.Provider>

          {signedIn && (
            <nav className="nav">
              <NavItem id="today" tab={tab} go={go} Icon={IcToday} label="Today" />
              <NavItem id="activity" tab={tab} go={go} Icon={IcActivity} label="Activity" />
              <button
                className={`nav-butler ${tab === "butler" ? "active" : ""}`}
                onClick={() => go("butler")}
              >
                <span className="butler-orb"><IcSpark size={25} /></span>
                <span>Butler</span>
              </button>
              <NavItem id="plan" tab={tab} go={go} Icon={IcPlan} label="Plan" />
              <NavItem id="more" tab={tab} go={go} Icon={IcMore} label="More" />
            </nav>
          )}
        </div>
      </div>
    </div>
  );
}
