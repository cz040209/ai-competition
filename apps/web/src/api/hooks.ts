import type { DashboardToday, TokenResponse } from "@kira/contracts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export const dashboardTodayKey = ["dashboard", "today"] as const;

export function useDashboardToday(enabled: boolean) {
  return useQuery({
    queryKey: dashboardTodayKey,
    queryFn: () => api.get<DashboardToday>("/v1/dashboard/today"),
    enabled,
  });
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (credentials: { email: string; password: string }) =>
      api.post<TokenResponse>("/v1/auth/login", credentials),
    onSuccess: (token) => {
      api.setAccessToken(token.access_token);
      void queryClient.invalidateQueries({ queryKey: dashboardTodayKey });
    },
  });
}
