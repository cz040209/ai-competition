import type { Activity, DashboardToday, TokenResponse, Transaction } from "@kira/contracts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export const dashboardTodayKey = ["dashboard", "today"] as const;
export const activityKey = ["transactions"] as const;
const activityKeyFor = (category: string | null) => [...activityKey, category] as const;

export function useDashboardToday(enabled: boolean) {
  return useQuery({
    queryKey: dashboardTodayKey,
    queryFn: () => api.get<DashboardToday>("/v1/dashboard/today"),
    enabled,
  });
}

export function useActivity(enabled: boolean, category: string | null = null) {
  return useQuery({
    queryKey: activityKeyFor(category),
    queryFn: () =>
      api.get<Activity>(
        category === null
          ? "/v1/transactions"
          : `/v1/transactions?category=${encodeURIComponent(category)}`,
      ),
    enabled,
    // The chips are the same on every filtered response, so the previous
    // ledger stays put while the next one loads instead of flashing empty.
    placeholderData: (previous) => previous,
  });
}

/**
 * Every one of these moves money, so both the ledger and Today are refetched —
 * a stale safe-to-spend after a confirm would be a wrong number on screen.
 */
function useSettle(action: "confirm" | "discard" | "unconfirm") {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<Transaction>(`/v1/transactions/${id}/${action}`),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: activityKey }),
        queryClient.invalidateQueries({ queryKey: dashboardTodayKey }),
      ]);
    },
  });
}

export function useConfirmDraft() {
  return useSettle("confirm");
}

export function useDiscardDraft() {
  return useSettle("discard");
}

export function useUnconfirm() {
  return useSettle("unconfirm");
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (credentials: { email: string; password: string }) =>
      api.post<TokenResponse>("/v1/auth/login", credentials),
    onSuccess: (token) => {
      api.setAccessToken(token.access_token);
      void queryClient.invalidateQueries({ queryKey: dashboardTodayKey });
      void queryClient.invalidateQueries({ queryKey: activityKey });
    },
  });
}
