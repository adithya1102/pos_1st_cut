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
  // PATCH is how a campaign is edited AND how it is switched on/off — the
  // backend audits the toggle distinctly, so no separate verb is needed here.
  patch: <T,>(path: string, body?: unknown) =>
    request<T>(path, {
      method: "PATCH",
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
  /** Area within the city (migration 012). Null for outlets created before it;
   *  required at signup from now on. Shown next to the name because it is half
   *  of the key the approval duplicate guard rejects on. */
  locality: string | null;
  // Null for every outlet created before migration 009 added the column.
  phone_number: string | null;
  organization_id: string | null;
  organization_name: string | null;
  verification_status: VerificationStatus;
  is_visible: boolean;
  created_at: string | null;
  deactivated_at: string | null;
  is_deactivated: boolean;
  /** Owner's login username, for support recovering a forgotten login.
   *  Read-only; no password material is ever exposed. */
  owner_username: string | null;
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

/** One row of the read-only customer directory. `name` is usually null —
 *  sign-in only ever captures a verified phone number. */
// phone_number and email are both nullable since migration 008: OTP customers
// have no email, Google customers have no phone. At least one is always set.
export interface CustomerRow {
  id: string;
  phone_number: string | null;
  email: string | null;
  name: string | null;
  order_count: number;
  created_at: string | null;
  // Loyalty + plan (migration 010). plan is derived server-side from
  // premium_until; premium_until is null for everyone who never had a trial.
  points_balance: number;
  premium_until: string | null;
  plan: string;
  // Order stats, from PAID orders only.
  total_order_value: number;
  top_dish: string | null;
  top_outlet: string | null;
  last_order_at: string | null;
  days_since_last_order: number | null;
  /** HEURISTIC recency bucket, not a churn prediction. See backend service.py. */
  activity_status: "No orders" | "Active" | "At Risk" | "Churned" | string;
}

/** A city in the canonical list (migration 013). */
export interface City {
  id: string;
  name: string;
  status: "active" | "pending" | "rejected" | string;
  created_at: string | null;
  decided_at: string | null;
  /** Which outlet's signup requested it; null for seeded/admin-added rows. */
  requested_by_outlet_id: string | null;
  requested_by_outlet_name: string | null;
}

// -------------------------- promotions (migration 016) ----------------------

/** Who pays. Derived from nothing else — `scope` IS the funding decision.
 *  The admin dashboard only ever creates CAREVO_CAMPAIGN rows; RESTAURANT_OFFER
 *  appears in this union only because the two share a table and a type. */
export type PromotionScope = "CAREVO_CAMPAIGN" | "RESTAURANT_OFFER";
export type DiscountType = "PERCENT" | "FLAT";

export interface Promotion {
  id: string;
  code: string | null;
  label: string;
  scope: PromotionScope;
  /** Null = platform-wide. Set = campaign aimed at one restaurant. */
  outlet_id: string | null;
  outlet_name: string | null;
  discount_type: DiscountType;
  discount_value: number;
  max_discount_amount: number | null;
  min_order_value: number | null;
  creator_name: string | null;
  max_redemptions_total: number | null;
  max_redemptions_per_customer: number;
  is_active: boolean;
  created_by_user_id: string | null;
  created_at: string | null;
  /** V1 analytics: a count, nothing more. */
  redemption_count: number;
  /** Server-rendered one-liner, so the dashboard and the customer app never
   *  word the same campaign differently. */
  benefit_text: string;
}

export interface PromotionCreateBody {
  label: string;
  code?: string | null;
  outlet_id?: string | null;
  discount_type: DiscountType;
  discount_value: number;
  max_discount_amount?: number | null;
  min_order_value?: number | null;
  creator_name?: string | null;
  max_redemptions_total?: number | null;
  max_redemptions_per_customer?: number;
  is_active?: boolean;
}

/** One order in the admin log (GET /admin/orders). Separate from CustomerRow
 *  on purpose — the Customers directory is per-person, this is per-order, and
 *  its columns are left untouched. */
export interface AdminOrderItem {
  name: string | null;
  quantity: number;
}

export interface AdminOrder {
  order_id: string;
  pickup_code: string | null;
  status: string;
  payment_status: string | null;
  created_at: string | null;
  customer_name: string | null;
  customer_phone: string | null;
  customer_email: string | null;
  outlet_name: string | null;
  items: AdminOrderItem[];
  total_amount: number;
  discount_amount: number;
  promotion_label: string | null;
  promotion_code: string | null;
  promotion_discount: number | null;
  /** Null when the customer never shared an origin — render "—", not 0. */
  distance_km: number | null;
}

export interface AdminOrderPage {
  total: number;
  limit: number;
  offset: number;
  orders: AdminOrder[];
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

// -------------------- prediction engine (shadow mode) ----------------------

export interface PredictionOverview {
  shadow_mode: boolean;
  read_only: boolean;
  graduation_threshold: number;
  orders_analyzed: number;
  progress_pct: number;
  promise_kept: number;
  promise_kept_rate: number | null;
  trusted_travel_observations: number;
  trusted_kitchen_observations: number;
  total_events: number;
  orders_predicted: number;
  avg_interval_score: number | null;
  graduated_outlets: number;
}

export interface OutletQuality {
  outlet_id: string;
  outlet_name: string | null;
  outcomes: number;
  promise_kept: number;
  promise_kept_rate: number | null;
  avg_interval_score: number | null;
  avg_kitchen_trust: number | null;
  avg_travel_trust: number | null;
  avg_customer_trust: number | null;
  trusted_order_count: number;
  tap_discipline: number | null;
  shadow_mode: boolean;
}

export interface PredictionOrderRow {
  order_id: string;
  status: string;
  outlet_id: string | null;
  outlet_name: string | null;
  risk_level: string | null;
  travel_source: string | null;
  degraded: boolean | null;
  interval_score: number | null;
  promise_kept: boolean | null;
  event_count: number;
  created_at: string | null;
}

export interface TimelineEvent {
  seq: number;
  event_type: string;
  actor_type: string;
  source: string;
  occurred_at: string;
  payload: Record<string, unknown> | null;
}

export interface TimelinePrediction {
  predictor: string;
  model_version: string;
  mu_seconds: number | null;
  sigma_seconds: number | null;
  output: unknown;
  predicted_at: string;
}

export interface OrderTimeline {
  order_id: string;
  status: string;
  outlet_id: string | null;
  outlet_name: string | null;
  total_amount: number;
  created_at: string | null;
  events: TimelineEvent[];
  twin: {
    promise_start: string | null;
    promise_end: string | null;
    shadow_range_min: [number, number] | null;
    risk_level: string | null;
    travel_source: string | null;
    degraded: boolean | null;
    ready_sigma_s: number | null;
    hold_tolerance_s: number | null;
    last_recomputed_at: string | null;
  } | null;
  predictions: TimelinePrediction[];
  outcome: {
    actual_prep_s: number | null;
    actual_travel_s: number | null;
    actual_hold_s: number | null;
    counter_wait_s: number | null;
    promise_kept: boolean | null;
    interval_score: number | null;
    wait_feedback: string | null;
    kitchen_trust: number;
    travel_trust: number;
    customer_trust: number;
    trust_failures: string[];
  } | null;
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
  deactivateOutlet: (id: string, reason?: string) =>
    api.post(`/api/v1/admin/outlets/${id}/deactivate`, { reason: reason ?? null }),
  reactivateOutlet: (id: string) =>
    api.post(`/api/v1/admin/outlets/${id}/reactivate`),

  lockedOrders: () => api.get<LockedOrder[]>("/api/v1/admin/orders/locked"),
  unlockOrder: (id: string) => api.post(`/api/v1/admin/orders/${id}/unlock`),

  customers: (limit = 200) =>
    api.get<CustomerRow[]>(`/api/v1/admin/customers?limit=${limit}`),

  cities: (status?: string) =>
    api.get<City[]>(
      `/api/v1/admin/cities${status ? `?status=${encodeURIComponent(status)}` : ""}`,
    ),
  approveCity: (id: string) =>
    api.post<City>(`/api/v1/admin/cities/${id}/approve`, {}),
  rejectCity: (id: string) =>
    api.post<City>(`/api/v1/admin/cities/${id}/reject`, {}),

  orders: (limit = 50, offset = 0) =>
    api.get<AdminOrderPage>(`/api/v1/admin/orders?limit=${limit}&offset=${offset}`),

  auditLogs: (limit = 100) =>
    api.get<AuditLog[]>(`/api/v1/admin/audit-logs?limit=${limit}`),

  // CareVo Campaigns (migration 016). CareVo-funded and CareVo-created; the
  // restaurants' own offers live in owner_app and are never listed here.
  promotions: () => api.get<Promotion[]>("/api/v1/admin/promotions"),
  createPromotion: (body: PromotionCreateBody) =>
    api.post<Promotion>("/api/v1/admin/promotions", body),
  updatePromotion: (id: string, body: Partial<PromotionCreateBody>) =>
    api.patch<Promotion>(`/api/v1/admin/promotions/${id}`, body),
  setPromotionActive: (id: string, is_active: boolean) =>
    api.patch<Promotion>(`/api/v1/admin/promotions/${id}`, { is_active }),

  // Prediction engine (shadow-mode observability, read-only).
  predictionOverview: () =>
    api.get<PredictionOverview>("/api/v1/admin/prediction/overview"),
  predictionOutlets: () =>
    api.get<OutletQuality[]>("/api/v1/admin/prediction/outlets"),
  predictionOrders: (limit = 50) =>
    api.get<PredictionOrderRow[]>(`/api/v1/admin/prediction/orders?limit=${limit}`),
  orderTimeline: (orderId: string) =>
    api.get<OrderTimeline>(`/api/v1/admin/prediction/orders/${orderId}/timeline`),

  // Admin-assisted onboarding: reuses the public /register flow (same as
  // owner_app self-signup) to create an outlet (pending_verification) + owner.
  registerOutlet: (body: RegisterOutletBody) =>
    api.post<RegisterOutletResult>("/api/v1/register", body),
};

export interface RegisterOutletBody {
  restaurant_name: string;
  /** Must be an already-approved city. The server rejects both-or-neither of
   *  city / requested_city, so exactly one is sent. */
  city?: string | null;
  /** Area within the city (migration 012). REQUIRED server-side — a body
   *  without it is rejected 422, which is what this form used to do. */
  locality: string;
  /** Required server-side: admins had no reliable way to reach an outlet
   *  during verification without it. */
  phone_number: string;
  /** Required server-side (migration 015) — it is what makes the owner's
   *  forgot-password flow possible. */
  email: string;
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
