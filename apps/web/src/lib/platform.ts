/** The desktop shell supplies its platform before navigation; browsers use their UA. */
export type Platform = "macos" | "windows" | "other";

declare global {
  interface Window {
    __POLYMECH_PLATFORM__?: unknown;
  }
}

export function getPlatform(): Platform {
  const desktop = window.__POLYMECH_PLATFORM__;
  if (desktop === "macos" || desktop === "windows") return desktop;
  const ua = navigator.userAgent;
  if (/Windows/i.test(ua)) return "windows";
  if (/Macintosh|Mac OS X/i.test(ua)) return "macos";
  return "other";
}

export function hasPrimaryKey(event: Pick<KeyboardEvent, "metaKey" | "ctrlKey">): boolean {
  return getPlatform() === "macos" ? event.metaKey : event.ctrlKey;
}

export function shortcut(key: string, { alt = false, shift = false } = {}): string {
  return getPlatform() === "macos"
    ? `⌘${alt ? "⌥" : ""}${shift ? "⇧" : ""}${key}`
    : `Ctrl${alt ? "+Alt" : ""}${shift ? "+Shift" : ""}+${key}`;
}
