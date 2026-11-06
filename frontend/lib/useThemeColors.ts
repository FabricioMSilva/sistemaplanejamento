import { useEffect, useState } from "react";
import { useTheme } from "@/providers/ThemeProvider";

const TOKENS = ["chart-1", "chart-2", "chart-3", "chart-4", "chart-5", "foreground", "muted-foreground",
  "border", "surface-elevated", "accent", "primary"] as const;
type Token = (typeof TOKENS)[number];

// Cores de fallback (tema padrão) para o primeiro render no servidor.
const FALLBACK: Record<Token, string> = {
  "chart-1": "rgb(39 80 155)", "chart-2": "rgb(252 196 0)", "chart-3": "rgb(74 138 0)", "chart-4": "rgb(0 32 91)",
  "chart-5": "rgb(120 132 150)", foreground: "rgb(10 28 64)", "muted-foreground": "rgb(83 86 90)",
  border: "rgb(214 222 235)", "surface-elevated": "rgb(255 255 255)", accent: "rgb(252 229 0)", primary: "rgb(39 80 155)",
};

/** Cores do tema ativo prontas para SVG/Recharts, que não resolvem var(--token) em atributos. */
export function useThemeColors() {
  const { theme } = useTheme();
  const [colors, setColors] = useState(FALLBACK);
  useEffect(() => {
    const style = getComputedStyle(document.documentElement);
    setColors(Object.fromEntries(TOKENS.map((token) => {
      const value = style.getPropertyValue(`--${token}`).trim();
      return [token, value ? `rgb(${value})` : FALLBACK[token]];
    })) as Record<Token, string>);
  }, [theme]);
  return colors;
}
