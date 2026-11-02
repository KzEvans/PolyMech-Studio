import { afterEach, describe, expect, it, vi } from "vitest";
import { getPlatform, hasPrimaryKey, shortcut } from "./platform";

afterEach(() => {
  vi.unstubAllGlobals();
  delete window.__POLYMECH_PLATFORM__;
});

describe("platform commands", () => {
  it("uses Control on Windows and formats the same key shown in the UI", () => {
    vi.stubGlobal("navigator", { userAgent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" });
    expect(getPlatform()).toBe("windows");
    expect(shortcut("R")).toBe("Ctrl+R");
    expect(shortcut("S", { alt: true })).toBe("Ctrl+Alt+S");
    expect(hasPrimaryKey({ ctrlKey: true, metaKey: false })).toBe(true);
    expect(hasPrimaryKey({ ctrlKey: false, metaKey: true })).toBe(false);
  });

  it("keeps macOS commands and prefers the trusted desktop platform", () => {
    vi.stubGlobal("navigator", { userAgent: "Mozilla/5.0 (Windows NT 10.0)" });
    window.__POLYMECH_PLATFORM__ = "macos";
    expect(getPlatform()).toBe("macos");
    expect(shortcut("R", { shift: true })).toBe("⌘⇧R");
    expect(shortcut("S", { alt: true })).toBe("⌘⌥S");
    expect(hasPrimaryKey({ ctrlKey: false, metaKey: true })).toBe(true);
    expect(hasPrimaryKey({ ctrlKey: true, metaKey: false })).toBe(false);
  });
});
