import type {
  Activity,
  ButlerThread,
  Capture,
  CaptureAvailability,
  Category,
  DashboardToday,
  ForesightResponse,
  Memory,
  TokenResponse,
  Transaction,
} from "@kira/contracts";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

export const dashboardTodayKey = ["dashboard", "today"] as const;
export const activityKey = ["transactions"] as const;
export const foresightKey = ["foresight"] as const;
const activityKeyFor = (category: string | null) => [...activityKey, category] as const;

export function useDashboardToday(enabled: boolean) {
  return useQuery({
    queryKey: dashboardTodayKey,
    queryFn: () => api.get<DashboardToday>("/v1/dashboard/today"),
    enabled,
  });
}

export function useForesight(enabled: boolean, horizon?: number) {
  return useQuery({
    queryKey: [...foresightKey, horizon ?? "default"],
    queryFn: () =>
      api.get<ForesightResponse>(
        horizon === undefined ? "/v1/foresight" : `/v1/foresight?horizon=${horizon}`,
      ),
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

export const butlerThreadKey = ["butler", "thread"] as const;
export const memoriesKey = ["butler", "memories"] as const;

export function useButlerThread(enabled: boolean) {
  return useQuery({
    queryKey: butlerThreadKey,
    queryFn: () => api.get<ButlerThread>("/v1/butler/thread"),
    enabled,
  });
}

export function useMemories(enabled: boolean) {
  return useQuery({
    queryKey: memoriesKey,
    queryFn: () => api.get<Memory[]>("/v1/butler/memories"),
    enabled,
  });
}

export function useCorrectMemory() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, fact }: { id: string; fact: string }) =>
      api.patch<Memory>(`/v1/butler/memories/${id}`, { fact }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: memoriesKey }),
  });
}

export function useForgetMemory() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.delete<void>(`/v1/butler/memories/${id}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: memoriesKey }),
  });
}

/** Whether the camera and microphone affordances should be offered at all. */
export function useCategories(enabled: boolean) {
  return useQuery({
    queryKey: ["categories"],
    queryFn: () => api.get<Category[]>("/v1/categories"),
    enabled,
    staleTime: Infinity,
  });
}

export function useCaptureAvailability(enabled: boolean) {
  return useQuery({
    queryKey: ["capture"],
    queryFn: () => api.get<CaptureAvailability>("/v1/capture"),
    enabled,
    staleTime: Infinity,
  });
}

export function useReadCapture(kind: "receipt" | "voice") {
  return useMutation({
    mutationFn: (file: Blob) => {
      const form = new FormData();
      form.append(kind === "receipt" ? "image" : "audio", file, `capture.${kind}`);
      return api.upload<Capture>(`/v1/capture/${kind}`, form);
    },
  });
}

/** Save what was read. It becomes a draft, which is not yet the ledger. */
export function useCreateDraft() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (draft: {
      merchant: string;
      amount_sen: number;
      occurred_on: string;
      category?: string;
      source?: string;
      confidence?: number | null;
      note?: string;
    }) => api.post<Transaction>("/v1/transactions", draft),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: activityKey }),
        queryClient.invalidateQueries({ queryKey: dashboardTodayKey }),
      ]);
    },
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
      void queryClient.invalidateQueries({ queryKey: activityKey });
      void queryClient.invalidateQueries({ queryKey: butlerThreadKey });
    },
  });
}
