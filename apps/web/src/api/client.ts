/** Access tokens stay in memory; the httpOnly refresh cookie enables recovery. */

let accessToken: string | null = null;

export function setAccessToken(token: string): void {
  accessToken = token;
}

export function clearAccessToken(): void {
  accessToken = null;
}

export function hasAccessToken(): boolean {
  return accessToken !== null;
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function raw(path: string, init: RequestInit): Promise<Response> {
  return fetch(path, {
    ...init,
    credentials: "include",
    headers: {
      "content-type": "application/json",
      ...(accessToken ? { authorization: `Bearer ${accessToken}` } : {}),
      ...(init.headers ?? {}),
    },
  });
}

async function refresh(): Promise<boolean> {
  const response = await fetch("/v1/auth/refresh", {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) {
    clearAccessToken();
    return false;
  }
  const body = (await response.json()) as { access_token: string };
  setAccessToken(body.access_token);
  return true;
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  let response = await raw(path, init);
  if (response.status === 401 && !path.startsWith("/v1/auth/")) {
    if (await refresh()) {
      response = await raw(path, init);
    }
  }

  if (!response.ok) {
    const detail = await response.text();
    throw new ApiError(response.status, detail || response.statusText);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  setAccessToken,
  clearAccessToken,
  hasAccessToken,
};
