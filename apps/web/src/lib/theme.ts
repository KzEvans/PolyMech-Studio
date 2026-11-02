import { useEffect } from "react";

export type ThemeSetting = "system" | "light" | "dark";

/** Apply theme + reduced-transparency to <html>; "system" follows prefers-color-scheme live. */
export function useApplyTheme(theme: ThemeSetting, reduceTransparency: boolean) {
  useEffect(() => {
    const root = document.documentElement;
    root.dataset.reduceTransparency = String(reduceTransparency);
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      root.dataset.theme = theme === "system" ? (mq.matches ? "dark" : "light") : theme;
    };
    apply();
    mq.addEventListener("change", apply);
    return () => mq.removeEventListener("change", apply);
  }, [theme, reduceTransparency]);
}

export function currentTheme(): "light" | "dark" {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}
