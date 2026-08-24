import type { Tab } from "../App";

type TodayProps = {
  data: unknown;
  isLoading: boolean;
  isError: boolean;
  go: (tab: Tab) => void;
};

// Replaced in full by the live dashboard in Task 13.
export function Today(_: TodayProps) {
  return <div className="pad">Today</div>;
}
