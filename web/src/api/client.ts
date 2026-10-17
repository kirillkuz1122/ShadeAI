const API_KEY_STORAGE = "shade_api_key";

export interface Health {
  status: string;
  uptime: number;
  ha_connected: boolean;
  llm_status: string;
  db_size: string;
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
    throw new Error(`HTTP ${resp.status}`);
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
};
