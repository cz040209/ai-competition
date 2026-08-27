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

/**
 * A response whose body is read as it arrives. Used for the Butler's SSE
 * stream, which is a POST with a bearer header — neither of which
 * `EventSource` supports.
 */
async function stream(path: string, body?: unknown): Promise<Response> {
  const init: RequestInit = {
    method: "POST",
    headers: { accept: "text/event-stream" },
    body: body === undefined ? undefined : JSON.stringify(body),
  };
  let response = await raw(path, init);
  if (response.status === 401 && (await refresh())) {
    response = await raw(path, init);
  }
  if (!response.ok) {
    throw new ApiError(response.status, (await response.text()) || response.statusText);
  }
  return response;
}

/** Multipart, for the bytes a camera or a microphone produced. */
async function upload<T>(path: string, form: FormData): Promise<T> {
  // The browser sets the multipart boundary; sending our own content-type breaks it.
  const init: RequestInit = { method: "POST", body: form, headers: { "content-type": "" } };
  let response = await fetch(path, {
    ...init,
    credentials: "include",
    headers: accessToken ? { authorization: `Bearer ${accessToken}` } : {},
  });
  if (response.status === 401 && (await refresh())) {
    response = await fetch(path, {
      ...init,
      credentials: "include",
      headers: accessToken ? { authorization: `Bearer ${accessToken}` } : {},
    });
  }
  if (!response.ok) {
    throw new ApiError(response.status, (await response.text()) || response.statusText);
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
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "PATCH",
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  delete: <T>(path: string) => request<T>(path, { method: "DELETE" }),
  stream,
  upload,
  setAccessToken,
  clearAccessToken,
  hasAccessToken,
};
