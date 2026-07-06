import type { Config } from "tailwindcss";
import typography from "@tailwindcss/typography";

export default {
  darkMode: "class",
  content: [
    "./components/**/*.{vue,ts}",
    "./composables/**/*.ts",
    "./layouts/**/*.vue",
    "./pages/**/*.vue",
    "./app.vue",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#f0f9ff",
          100: "#e0f2fe",
          200: "#bae6fd",
          300: "#7dd3fc",
          400: "#38bdf8",
          500: "#0ea5e9",
          600: "#0284c7",
          700: "#0369a1",
          800: "#075985",
          900: "#0c4a6e",
        },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      typography: {
        DEFAULT: {
          css: {
            maxWidth: "none",
            color: "inherit",
            a: { color: "#0284c7", textDecoration: "none", "&:hover": { textDecoration: "underline" } },
            "h1,h2,h3,h4": { color: "inherit", fontWeight: "600" },
            code: { color: "#0ea5e9", background: "none", fontWeight: "400" },
            "pre code": { color: "inherit" },
            "code::before": { content: '""' },
            "code::after": { content: '""' },
          },
        },
        invert: {
          css: {
            color: "inherit",
            a: { color: "#38bdf8" },
            "h1,h2,h3,h4": { color: "inherit" },
            code: { color: "#38bdf8" },
          },
        },
      },
    },
  },
  plugins: [typography],
} satisfies Config;
