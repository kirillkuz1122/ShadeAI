const API_KEY_STORAGE = "shade_api_key";

export interface Health {
  status: string;
  uptime: number;
  ha_connected: boolean;
  llm_status: string;
  db_size: string;
  db_connected: boolean;
  db_size_bytes: number | null;
  ha_status: string;
  services: Record<string, string>;
}

export interface DeviceState {
  entity_id: string;
  name: string;
  state: string;
  type: string;
  attributes: Record<string, unknown>;
  last_changed: string;
  last_updated: string;
}

export interface CommandResult {
  status: "success";
  entity_id: string;
  new_state: string | null;
  state_observed: boolean;
  executed_at: string;
  event_id: number;
}

export interface JournalEvent {
  id: number;
  timestamp: string;
  source: string;
  type: string;
  payload: Record<string, string | null>;
}

export interface NotificationItem {
  id: number;
  app_name: string;
  title: string;
  text: string;
  timestamp: string;
  priority: string;
  category: string | null;
  event_id: string | null;
  status: "stored" | "processed";
  processed_data: Record<string, unknown> | null;
  created_at: string;
}

export interface NotificationsResponse {
  items: NotificationItem[];
  total: number;
}

export function getApiKey(): string {
  return localStorage.getItem(API_KEY_STORAGE) ?? "";
}

export function setApiKey(key: string): void {
  localStorage.setItem(API_KEY_STORAGE, key);
}

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(`HTTP ${status}`);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getApiKey()}`,
      ...init?.headers,
    },
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => null);
    throw new ApiError(resp.status, body?.detail ?? null);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/api/v1/health"),
  notifications: (limit = 50, offset = 0, category?: string) => {
    const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (category) query.set("category", category);
    return request<NotificationsResponse>(`/api/v1/notifications?${query}`);
  },
  notification: (id: number) => request<NotificationItem>(`/api/v1/notifications/${id}`),
  devices: (domain?: string) => request<{ devices: DeviceState[] }>(
    `/api/v1/devices${domain ? `?domain=${encodeURIComponent(domain)}` : ""}`),
  deviceState: (entityId: string) => request<DeviceState>(
    `/api/v1/devices/${encodeURIComponent(entityId)}/state`),
  command: (entityId: string, action: string, params: Record<string, unknown> = {}) =>
    request<CommandResult>(`/api/v1/devices/${encodeURIComponent(entityId)}/command`, {
      method: "POST", body: JSON.stringify({ action, params }),
    }),
  events: (limit = 100, offset = 0, type?: string) => {
    const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (type) query.set("type", type);
    return request<{ events: JournalEvent[]; total: number }>(`/api/v1/events?${query}`);
  },
};
