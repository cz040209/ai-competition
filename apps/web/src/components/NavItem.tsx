import type { ComponentType } from "react";

import type { Tab } from "../App";

type NavItemProps = {
  id: Tab;
  tab: Tab;
  go: (next: Tab) => void;
  Icon: ComponentType<{ size?: number }>;
  label: string;
  active?: boolean;
};

export function NavItem({ id, tab, go, Icon, label, active }: NavItemProps) {
  const on = active ?? tab === id;
  return (
    <button className={`nav-item ${on ? "active" : ""}`} onClick={() => go(id)}>
      <Icon />
      <span>{label}</span>
      {on && <i className="nav-dot" />}
    </button>
  );
}
