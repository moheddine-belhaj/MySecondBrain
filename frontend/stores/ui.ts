import { defineStore } from "pinia";
import type { Theme } from "~/types";

export const useUiStore = defineStore("ui", () => {
  const theme = ref<Theme>("system");
  const sidebarOpen = ref(true);

  function setTheme(t: Theme) {
    theme.value = t;
    if (import.meta.client) {
      localStorage.setItem("theme", t);
      applyTheme(t);
    }
  }

  function applyTheme(t: Theme) {
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const isDark = t === "dark" || (t === "system" && prefersDark);
    document.documentElement.classList.toggle("dark", isDark);
  }

  function initTheme() {
    if (!import.meta.client) return;
    const stored = (localStorage.getItem("theme") as Theme | null) ?? "system";
    theme.value = stored;
    applyTheme(stored);
  }

  function toggleSidebar() {
    sidebarOpen.value = !sidebarOpen.value;
  }

  return { theme, sidebarOpen, setTheme, initTheme, toggleSidebar };
});
