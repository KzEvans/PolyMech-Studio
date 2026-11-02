import { describe, expect, test } from "vitest";
import { fmt, fromMm, mm, show } from "./units";

describe("display units", () => {
  test("SI values are shown in display units", () => {
    expect(show(1.2e6, "Pa")).toBe("1.2 MPa");
    expect(show(2.5e6, "J/m^3")).toBe("2.5 MJ/m³");
    expect(show(298.15, "K")).toBe("25 °C");
    expect(show(0.4e-9, "m/cycle")).toBe("0.4 nm/cycle");
    expect(show(null, "Pa")).toBe("—");
    expect(show(1100, "J/m^2")).toBe("1100 J/m²"); // fatigue thresholds stay in J/m²
    expect(show(91e3, "J/m^2")).toBe("91 kJ/m²"); // toughness switches to kJ/m²
  });
  test("very large/small numbers use exponents, never SI letters", () => {
    expect(fmt(1.5e-7)).toBe("1.500e-7");
    expect(fmt(123456)).toBe("1.235e+5");
    expect(fmt(Number.NaN)).toBe("—");
  });
  test("mm round trip for metadata forms", () => {
    expect(mm(0.001)).toBe("1");
    expect(fromMm("20")).toBeCloseTo(0.02);
    expect(fromMm("  ")).toBeNull();
  });
});
