import type { Config } from "tailwindcss";

const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;
const scale = (family: string, shades: number[]) =>
  Object.fromEntries(shades.map((shade) => [shade, token(`${family}-${shade}`)]));

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx}",
    "./components/**/*.{js,ts,jsx,tsx}",
    "./lib/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Tokens semânticos do design system (definidos por tema em styles/themes.css).
        background: token("background"),
        foreground: token("foreground"),
        surface: { DEFAULT: token("surface"), elevated: token("surface-elevated"), sunken: token("surface-sunken") },
        card: { DEFAULT: token("card"), foreground: token("card-foreground") },
        primary: { DEFAULT: token("primary"), foreground: token("primary-foreground") },
        secondary: { DEFAULT: token("secondary"), foreground: token("secondary-foreground") },
        muted: { DEFAULT: token("muted"), foreground: token("muted-foreground") },
        border: token("border"),
        input: token("input"),
        ring: token("ring"),
        success: token("success"),
        warning: token("warning"),
        danger: token("danger"),
        info: token("info"),
        header: { DEFAULT: token("header"), foreground: token("header-foreground") },
        chart: { 1: token("chart-1"), 2: token("chart-2"), 3: token("chart-3"), 4: token("chart-4"), 5: token("chart-5") },
        michelin: {
          blue: token("michelin-blue"),
          "dark-blue": token("michelin-dark-blue"),
          yellow: token("michelin-yellow"),
          green: token("michelin-green"),
          gray: token("michelin-gray"),
        },
        // Escalas usadas pelas telas existentes, agora dependentes do tema ativo.
        white: token("white"),
        black: token("black"),
        accent: {
          DEFAULT: token("accent"),
          foreground: token("accent-foreground"),
          ...scale("accent", [300, 400, 500]),
        },
        navy: scale("navy", [700, 800, 900, 950]),
        slate: scale("slate", [100, 200, 300, 400, 500, 600, 950]),
        sky: scale("sky", [100, 200, 300, 400, 500]),
        emerald: scale("emerald", [100, 200, 300, 400]),
        amber: scale("amber", [100, 200, 300, 400]),
        rose: scale("rose", [100, 200, 300, 400, 500, 950]),
        violet: scale("violet", [300, 400]),
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: ["Segoe UI", "system-ui", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgb(var(--shadow-color) / var(--shadow-strength)), 0 8px 24px rgb(var(--shadow-color) / var(--shadow-strength))",
      },
    },
  },
  plugins: [],
};

export default config;
