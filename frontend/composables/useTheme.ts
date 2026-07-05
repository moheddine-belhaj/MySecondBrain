import { useUiStore } from "~/stores/ui";
import type { Theme } from "~/types";

export function useTheme() {
  const ui = useUiStore();

  const isDark = computed(() => {
    if (ui.theme === "dark") return true;
    if (ui.theme === "light") return false;
    // system
    if (import.meta.client) {
      return window.matchMedia("(prefers-color-scheme: dark)").matches;
    }
    return false;
  });

  function toggle() {
    ui.setTheme(isDark.value ? "light" : "dark");
  }

  function set(t: Theme) {
    ui.setTheme(t);
  }

  return { theme: readonly(toRef(ui, "theme")), isDark, toggle, set };
}
