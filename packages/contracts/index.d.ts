import type { components } from "./src/schema";

export type Schemas = components["schemas"];
export type Activity = Schemas["ActivityResponse"];
export type ActivityDay = Schemas["ActivityDayResponse"];
export type CategorySummary = Schemas["CategorySummaryResponse"];
export type DashboardToday = Schemas["DashboardTodayResponse"];
export type GoalSummary = Schemas["GoalSummaryResponse"];
export type NextCommitment = Schemas["NextCommitmentResponse"];
export type TokenResponse = Schemas["TokenResponse"];
export type Transaction = Schemas["TransactionResponse"];
export type UserResponse = Schemas["UserResponse"];
export type { components, paths } from "./src/schema";
