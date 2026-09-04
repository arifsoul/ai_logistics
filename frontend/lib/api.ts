/**
 * API client for the FastAPI backend.
 *
 * The token lives in localStorage because the backend issues a bearer JWT and
 * the two apps sit on different origins, so an httpOnly cookie would need a
 * shared domain plus CSRF handling.
 * ponytail: upgrade to an httpOnly cookie + same-site proxy when both halves
 * are deployed behind one domain.
 */

export const API_URL = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000"
).replace(/\/$/, "");

const TOKEN_KEY = "logistics_token";
const ROLE_KEY = "logistics_role";

export type Role = "user" | "admin" | "superadmin";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getRole(): Role | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(ROLE_KEY) as Role | null;
}

export function setSession(token: string, role: string) {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(ROLE_KEY, role);
}

export function clearSession() {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(ROLE_KEY);
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/** Raw fetch with the bearer token attached. Callers handle the response. */
export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(`${API_URL}${path}`, { ...init, headers });
}

/** JSON request that throws ApiError on a non-2xx response. */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await apiFetch(path, { ...init, headers });
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new ApiError(data?.detail ?? `Request failed (${response.status})`, response.status);
  }
  return data as T;
}

export async function login(username: string, password: string) {
  // The token endpoint is OAuth2 password flow: form-encoded, not JSON.
  const body = new URLSearchParams({ username, password });
  const response = await fetch(`${API_URL}/api/auth/token`, {
    method: "POST",
    body,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new ApiError(data?.detail ?? "Login failed", response.status);
  }
  setSession(data.access_token, data.role);
  return data as { access_token: string; role: Role };
}

export async function register(username: string, password: string) {
  const body = new URLSearchParams({ username, password });
  const response = await fetch(`${API_URL}/api/auth/register`, {
    method: "POST",
    body,
  });
  const data = await response.json();
  if (!response.ok) {
    throw new ApiError(data?.detail ?? "Registration failed", response.status);
  }
  return data as { username: string; role: Role };
}

export type Me = { id: number; username: string; role: Role };

export const me = () => api<Me>("/api/users/me");
