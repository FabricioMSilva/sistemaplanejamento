import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { DEFAULT_THEME, REDUCED_MOTION_STORAGE_KEY, THEME_STORAGE_KEY, isThemeId, type ThemeId } from "@/config/themes";

type ThemeContextValue = {
  theme: ThemeId;
  setTheme: (theme: ThemeId) => void;
  reducedMotion: boolean;
  setReducedMotion: (value: boolean) => void;
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<ThemeId>(DEFAULT_THEME);
  const [reducedMotion, setReducedMotionState] = useState(false);

  useEffect(() => {
    const root = document.documentElement;
    const current = root.dataset.theme;
    if (isThemeId(current)) setThemeState(current);
    setReducedMotionState(root.dataset.reducedMotion === "true");
    // Habilita a transição de cores só depois da primeira pintura, para não animar o carregamento.
    const frame = requestAnimationFrame(() => root.classList.add("theme-ready"));
    return () => cancelAnimationFrame(frame);
  }, []);

  const setTheme = useCallback((next: ThemeId) => {
    setThemeState(next);
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem(THEME_STORAGE_KEY, next); } catch { /* armazenamento indisponível */ }
  }, []);

  const setReducedMotion = useCallback((value: boolean) => {
    setReducedMotionState(value);
    if (value) document.documentElement.dataset.reducedMotion = "true";
    else delete document.documentElement.dataset.reducedMotion;
    try { localStorage.setItem(REDUCED_MOTION_STORAGE_KEY, String(value)); } catch { /* armazenamento indisponível */ }
  }, []);

  const value = useMemo(() => ({ theme, setTheme, reducedMotion, setReducedMotion }),
    [theme, setTheme, reducedMotion, setReducedMotion]);
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme deve ser usado dentro de ThemeProvider.");
  return context;
}
