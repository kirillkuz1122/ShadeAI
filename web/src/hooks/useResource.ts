import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api/client";

type Loader<T> = (signal: AbortSignal) => Promise<T>;
interface Snapshot<T> {
  source: Loader<T>;
  data: T | null;
  error: unknown;
  loading: boolean;
  updatedAt: Date | null;
}

export function useResource<T>(load: Loader<T>, interval = 10000) {
  const [version, setVersion] = useState(0);
  const [state, setState] = useState<Snapshot<T>>({
    source: load,
    data: null,
    error: null,
    loading: true,
    updatedAt: null,
  });
  const refresh = useCallback(() => setVersion((v) => v + 1), []);
  useEffect(() => {
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    async function run() {
      setState((old) =>
        old.source === load
          ? { ...old, loading: true }
          : {
              source: load,
              data: null,
              error: null,
              loading: true,
              updatedAt: null,
            },
      );
      try {
        const data = await load(controller.signal);
        if (!disposed)
          setState({
            source: load,
            data,
            error: null,
            loading: false,
            updatedAt: new Date(),
          });
      } catch (error) {
        if (!disposed)
          setState((old) => ({
            ...old,
            error,
            loading: false,
            data:
              error instanceof ApiError && (error.status === 401 || error.status === 404)
                ? null
                : old.data,
          }));
      } finally {
        if (!disposed && interval) timer = setTimeout(tick, interval);
      }
    }
    function tick() {
      if (document.visibilityState === "visible") void run();
      else timer = setTimeout(tick, interval);
    }
    void run();
    window.addEventListener("online", refresh);
    const visible = () => {
      if (document.visibilityState === "visible") refresh();
    };
    document.addEventListener("visibilitychange", visible);
    return () => {
      disposed = true;
      controller.abort();
      clearTimeout(timer);
      window.removeEventListener("online", refresh);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [load, interval, refresh, version]);
  // Не показывать данные прежнего ключа/страницы даже до cleanup эффекта.
  const current =
    state.source === load
      ? state
      : { data: null, error: null, loading: true, updatedAt: null };
  return { ...current, refresh };
}
