import { useCallback, useSyncExternalStore } from "react";

const THEME_KEY = "amj-theme";

function getTheme(): "dark" | "light" {
  if (typeof window === "undefined") return "light";
  const stored = localStorage.getItem(THEME_KEY);
  if (stored === "light" || stored === "dark") return stored;
  const htmlTheme = document.documentElement.getAttribute("data-theme");
  if (htmlTheme === "light" || htmlTheme === "dark") return htmlTheme;
  return "dark";
}

function subscribe(callback: () => void): () => void {
  window.addEventListener("storage", callback);
  return () => window.removeEventListener("storage", callback);
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, getTheme);

  const setTheme = useCallback((t: "dark" | "light") => {
    localStorage.setItem(THEME_KEY, t);
    document.documentElement.setAttribute("data-theme", t);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", t === "light" ? "#e8eaed" : "#1e1f22");
    window.dispatchEvent(new Event("storage"));
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme(theme === "dark" ? "light" : "dark");
  }, [theme, setTheme]);

  return { theme, setTheme, toggleTheme };
}
