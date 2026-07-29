"use client";

/**
 * Thin fetch wrapper for the CareVo Admin Dashboard.
 *
 * Auth reuses the EXISTING staff login (POST /api/v1/auth/login, form-encoded).
 * There is no admin-specific login endpoint — the same staff JWT is used, and
 * the backend's SUPER_ADMIN role check decides what it can reach.
 */

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TOKEN_KEY = "carevo_admin_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY);
}

/** Thrown for any non-2xx response. `status` lets callers special-case 401/403. */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    const detail = body?.detail;
    if (typeof detail === "string") return detail;
    if (detail) return JSON.stringify(detail);
  } catch {
    // non-JSON body; fall through
  }
  return `${res.status} ${res.statusText}`;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      ...(init.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers ?? {}),
    },
    cache: "no-store",
  });

  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  get: <T,>(path: string) => request<T>(path),
  post: <T,>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "POST",
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
};

/** Staff login. Form-encoded on purpose — the endpoint is OAuth2PasswordRequestForm. */
export async function login(username: string, password: string): Promise<string> {
  const form = new URLSearchParams({ username, password });
  const res = await fetch(`${API_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  });
  if (!res.ok) throw new ApiError(res.status, await parseError(res));
  const data = await res.json();
  const token = data?.access_token;
  if (!token) throw new ApiError(500, "Login response contained no access_token");
  return token as string;
}

// ------------------------------- types -------------------------------------

export type VerificationStatus = "pending_verification" | "active" | "rejected";

export interface AdminMe {
  user_id: string;
  username: string;
  is_super_admin: boolean;
  roles: string[];
}

export interface Outlet {
  id: string;
  location_name: string;
  city: string | null;
  organization_id: string | null;
  organization_name: string | null;
  verification_status: VerificationStatus;
  is_visible: boolean;
  created_at: string | null;
}

export interface LockedOrder {
  order_id: string;
  outlet_id: string;
  outlet_name: string | null;
  status: string;
  failed_attempts: number;
  total_amount: number;
  customer_phone: string | null;
  created_at: string | null;
}

export interface AuditLog {
  id: string;
  actor_username: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  detail: unknown;
  created_at: string;
}

// ------------------------------ endpoints -----------------------------------

export const adminApi = {
  me: () => api.get<AdminMe>("/api/v1/admin/me"),

  outlets: (status?: VerificationStatus) =>
    api.get<Outlet[]>(
      `/api/v1/admin/outlets${status ? `?status=${status}` : ""}`,
    ),
  pendingOutlets: () => api.get<Outlet[]>("/api/v1/admin/outlets/pending"),
  approveOutlet: (id: string, reason?: string) =>
    api.post(`/api/v1/admin/outlets/${id}/approve`, { reason: reason ?? null }),
  rejectOutlet: (id: string, reason?: string) =>
    api.post(`/api/v1/admin/outlets/${id}/reject`, { reason: reason ?? null }),

  lockedOrders: () => api.get<LockedOrder[]>("/api/v1/admin/orders/locked"),
  unlockOrder: (id: string) => api.post(`/api/v1/admin/orders/${id}/unlock`),

  auditLogs: (limit = 100) =>
    api.get<AuditLog[]>(`/api/v1/admin/audit-logs?limit=${limit}`),

  // Admin-assisted onboarding: reuses the public /register flow (same as
  // owner_app self-signup) to create an outlet (pending_verification) + owner.
  registerOutlet: (body: RegisterOutletBody) =>
    api.post<RegisterOutletResult>("/api/v1/register", body),
};

export interface RegisterOutletBody {
  restaurant_name: string;
  city?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  username: string;
  password: string;
  upi_id: string;
}

export interface RegisterOutletResult {
  outlet_id: string;
  username: string;
  verification_status: string;
  message: string;
}
