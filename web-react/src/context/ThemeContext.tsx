import { createContext, useContext, useEffect, type ReactNode } from "react";
import { useTheme } from "@/hooks/useTheme";

interface ThemeContextValue {
  theme: "dark" | "light";
  setTheme: (t: "dark" | "light") => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const ctx = useTheme();

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", ctx.theme);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      meta.setAttribute("content", ctx.theme === "light" ? "#FAFAF9" : "#111111");
    }
  }, [ctx.theme]);

  return <ThemeContext.Provider value={ctx}>{children}</ThemeContext.Provider>;
}

export function useThemeContext(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) throw new Error("useThemeContext must be used within ThemeProvider");
  return ctx;
}
