import { getPlatform } from "./platform";

declare global {
  interface Window { __POLYMECH_ACCENT__?: unknown }
}
type RGB = [number, number, number];
function luminance(rgb: RGB): number {
  const [r, g, b] = rgb.map((v) => v / 255).map((v) => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a: RGB, b: RGB): number {
  const x = luminance(a), y = luminance(b);
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}
const css = (rgb: RGB) => `rgb(${rgb.join(" ")})`;
function readable(rgb: RGB, background: RGB, target: 0 | 255): RGB {
  for (let step = 0; step <= 20; step++) {
    const adjusted = rgb.map((v) => Math.round(v + (target - v) * step / 20)) as RGB;
    if (contrast(adjusted, background) >= 4.5) return adjusted;
  }
  return [target, target, target];
}
export function applyWindowsAccent(): void {
  const value = window.__POLYMECH_ACCENT__;
  if (getPlatform() !== "windows" || typeof value !== "string" || !/^#[\da-f]{6}$/i.test(value)) return;
  const rgb = [1, 3, 5].map((offset) => Number.parseInt(value.slice(offset, offset + 2), 16)) as RGB;
  const white: RGB = [255, 255, 255], black: RGB = [0, 0, 0];
  const foreground = contrast(rgb, white) >= 4.5 ? white : black;
  const hover = rgb.map((v) => Math.round(v * 0.9 + (foreground === white ? 0 : 255) * 0.1)) as RGB;
  const style = document.documentElement.style;
  style.setProperty("--system-accent-fill", css(rgb));
  style.setProperty("--system-accent-fg", css(foreground));
  style.setProperty("--system-accent-hover", css(hover));
  style.setProperty("--system-accent-light-text", css(readable(rgb, [229, 229, 229], 0)));
  style.setProperty("--system-accent-dark-text", css(readable(rgb, [51, 51, 51], 255)));
}
