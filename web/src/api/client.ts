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
  processing_status?: "pending" | "processing" | "processed" | "failed";
  processing_attempts?: number;
  processing_error_code?: string | null;
  processing_started_at?: string | null;
  processing_finished_at?: string | null;
  processed_data: Record<string, unknown> | null;
  created_at: string;
}

export interface NotificationsResponse {
  items: NotificationItem[];
  total: number;
}

export function getApiKey(): string {
  try {
    return localStorage.getItem(API_KEY_STORAGE) ?? "";
  } catch {
    return "";
  }
}

export function setApiKey(key: string): boolean {
  try {
    if (key) localStorage.setItem(API_KEY_STORAGE, key);
    else localStorage.removeItem(API_KEY_STORAGE);
    return true;
  } catch {
    return false;
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: unknown,
  ) {
    super(`HTTP ${status}`);
    this.name = "ApiError";
  }
}

export interface RequestOptions {
  signal?: AbortSignal;
  apiKey?: string;
}

async function request<T>(
  path: string,
  options: RequestOptions = {},
  init?: RequestInit,
  acceptedStatus?: number,
): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (options.signal?.aborted) abort();
  options.signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, 12000);
  try {
    const resp = await fetch(path, {
      ...init,
      signal: controller.signal,
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        ...(options.apiKey
          ? { Authorization: `Bearer ${options.apiKey}` }
          : {}),
      },
    });
    if (!resp.ok && resp.status !== acceptedStatus) {
      const body = await resp.json().catch(() => null);
      throw new ApiError(resp.status, body?.detail ?? null);
    }
    return (await resp.json()) as T;
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", abort);
  }
}

export const api = {
  health: (signal?: AbortSignal) =>
    request<Health>("/api/v1/health", { signal }, undefined, 503),
  notifications: (options: RequestOptions, limit = 20, offset = 0) => {
    const query = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    return request<NotificationsResponse>(
      `/api/v1/notifications?${query}`,
      options,
    );
  },
  notification: (options: RequestOptions, id: number) =>
    request<NotificationItem>(`/api/v1/notifications/${id}`, options),
  devices: (options: RequestOptions, domain?: string) =>
    request<{ devices: DeviceState[] }>(
      `/api/v1/devices${domain ? `?domain=${encodeURIComponent(domain)}` : ""}`,
      options,
    ),
  deviceState: (options: RequestOptions, entityId: string) =>
    request<DeviceState>(
      `/api/v1/devices/${encodeURIComponent(entityId)}/state`,
      options,
    ),
  command: (
    options: RequestOptions,
    entityId: string,
    action: string,
    params: Record<string, unknown> = {},
  ) =>
    request<CommandResult>(
      `/api/v1/devices/${encodeURIComponent(entityId)}/command`,
      options,
      {
        method: "POST",
        body: JSON.stringify({ action, params }),
      },
    ),
  events: (options: RequestOptions, limit = 20, offset = 0, type?: string) => {
    const query = new URLSearchParams({
      limit: String(limit),
      offset: String(offset),
    });
    if (type) query.set("type", type);
    return request<{ events: JournalEvent[]; total: number }>(
      `/api/v1/events?${query}`,
      options,
    );
  },
};
