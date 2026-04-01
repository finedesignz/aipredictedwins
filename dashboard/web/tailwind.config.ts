import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        "bg-primary": "#0a0e17",
        "bg-secondary": "#111827",
        "bg-card": "#1a2332",
        "bg-card-hover": "#1e293b",
        "bg-input": "#0f172a",
        "border-primary": "#1e293b",
        "border-subtle": "#151d2b",
        "text-primary": "#f1f5f9",
        "text-secondary": "#94a3b8",
        "text-muted": "#64748b",
        "accent-blue": "#60a5fa",
        "accent-blue-dim": "#1e3a5f",
        "profit-green": "#4ade80",
        "profit-green-bg": "#052e16",
        "loss-red": "#f87171",
        "loss-red-bg": "#450a0a",
        "warning-amber": "#fbbf24",
        "warning-amber-bg": "#451a03",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "-apple-system", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
