import { useCallback, useSyncExternalStore } from "react";

export function useLocalStorage<T>(key: string, defaultValue: T): [T, (val: T | ((prev: T) => T)) => void] {
  const getSnapshot = useCallback((): T => {
    try {
      const raw = localStorage.getItem(key);
      if (raw === null) return defaultValue;
      return JSON.parse(raw) as T;
    } catch {
      return defaultValue;
    }
  }, [key]);

  const subscribe = useCallback(
    (callback: () => void): (() => void) => {
      window.addEventListener("storage", callback);
      return () => window.removeEventListener("storage", callback);
    },
    []
  );

  const value = useSyncExternalStore(subscribe, getSnapshot);

  const setValue = useCallback(
    (val: T | ((prev: T) => T)) => {
      const next = typeof val === "function" ? (val as (prev: T) => T)(getSnapshot()) : val;
      localStorage.setItem(key, JSON.stringify(next));
      window.dispatchEvent(new Event("storage"));
    },
    [key, getSnapshot]
  );

  return [value, setValue];
}
