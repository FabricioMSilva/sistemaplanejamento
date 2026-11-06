export const THEMES = [
  {
    id: "michelin-professional",
    name: "Michelin Professional",
    description: "Claro e institucional, com cabeçalho azul Michelin.",
    preview: { background: "#F1F4F9", header: "#27509B", card: "#FFFFFF", accent: "#FCE500" },
  },
  {
    id: "command-center",
    name: "Command Center",
    description: "Escuro azul-marinho para acompanhamento prolongado.",
    preview: { background: "#051026", header: "#00205B", card: "#0B1E3F", accent: "#FCE500" },
  },
  {
    id: "executive-light",
    name: "Executive Light",
    description: "Minimalista para reuniões e análise gerencial.",
    preview: { background: "#FAFBFC", header: "#FFFFFF", card: "#FFFFFF", accent: "#27509B" },
  },
] as const;

export type ThemeId = (typeof THEMES)[number]["id"];

export const DEFAULT_THEME: ThemeId = "michelin-professional";
export const THEME_STORAGE_KEY = "psm-theme";
export const REDUCED_MOTION_STORAGE_KEY = "psm-reduced-motion";

export const isThemeId = (value: unknown): value is ThemeId =>
  THEMES.some((theme) => theme.id === value);

// Executado antes da hidratação (em _document) para evitar flash do tema errado.
export const THEME_BOOT_SCRIPT = `(function(){try{var d=document.documentElement;var t=localStorage.getItem("${THEME_STORAGE_KEY}");var ok=${JSON.stringify(THEMES.map((theme) => theme.id))};d.dataset.theme=ok.indexOf(t)>=0?t:"${DEFAULT_THEME}";if(localStorage.getItem("${REDUCED_MOTION_STORAGE_KEY}")==="true"){d.dataset.reducedMotion="true";}}catch(e){document.documentElement.dataset.theme="${DEFAULT_THEME}";}})();`;
