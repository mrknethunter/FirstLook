import i18n from "../i18n";

export class ApiError extends Error {
  constructor(readonly status: number) {
    super(`Request failed (${status})`);
  }
}

function safePath(path: string): string {
  if (!path.startsWith("/api/") || path.includes("#") || path.includes("shlink:")) {
    throw new Error("Invalid API path");
  }
  return path;
}

async function csrf(): Promise<string> {
  const response = await fetch("/api/v1/auth/csrf", {
    credentials: "same-origin", cache: "no-store", headers: { "Accept-Language": i18n.language },
  });
  if (!response.ok) throw new ApiError(response.status);
  const body: { csrf_token: string } = await response.json();
  return body.csrf_token;
}

export async function apiResponse(path: string, init: RequestInit = {}): Promise<Response> {
  const method = (init.method ?? "GET").toUpperCase();
  const headers = new Headers(init.headers);
  headers.set("Accept-Language", i18n.language);
  if (method !== "GET" && method !== "HEAD") {
    headers.set("X-CSRF-Token", await csrf());
  }
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(safePath(path), {
    ...init, method, headers, credentials: "same-origin", cache: "no-store",
  });
  if (!response.ok) throw new ApiError(response.status);
  return response;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await apiResponse(path, init);
  if (response.status === 204) return undefined as T;
  return await response.json() as T;
}

export function jsonBody(value: unknown): string {
  return JSON.stringify(value);
}

export type Principal = {
  user_id: string;
  tenant: string;
  role: "patient" | "responder" | "ed_staff" | "clinician" | "org_admin";
  org_id: string | null;
  locale: string;
  theme: string;
};

export async function getPrincipal(): Promise<Principal | null> {
  try {
    return await api<Principal>("/api/v1/me");
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}
