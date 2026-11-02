import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { KeyValue } from "./common";

describe("KeyValue", () => {
  it("never breaks between a number and its unit, only before separators", () => {
    const { container } = render(
      <KeyValue items={[["断裂功 W_f", "0.2597 MJ/m³（数值积分误差 7.7e-11 MJ/m³）"], ["初始模量 E", "0.1329 MPa ± 7.1e-4 MPa"]]} />,
    );
    const [work, modulus] = [...container.querySelectorAll("dd")];
    const parts = (dd: Element) => [...dd.querySelectorAll("span.whitespace-nowrap")].map((s) => s.textContent);
    expect(parts(work)).toEqual(["0.2597 MJ/m³", "（数值积分误差 7.7×10−11 MJ/m³）"]);
    expect(parts(modulus)).toEqual(["0.1329 MPa", " ± 7.1×10−4 MPa"]);
    expect(work.querySelectorAll("wbr")).toHaveLength(1);
  });
});

describe("rich", () => {
  it("renders subscripts and powers of ten, leaving hashes alone", async () => {
    const { rich, richHtml } = await import("@/lib/rich");
    const { container } = render(<p>{rich("断裂拉伸比 λ_b = 1.329e-4 MPa, σ_{nom}, hash 6252460f8eb087e6")}</p>);
    expect(container.querySelector("sub")?.textContent).toBe("b");
    expect(container.querySelectorAll("sub")[1].textContent).toBe("nom");
    expect(container.querySelector("sup")?.textContent).toBe("−4");
    expect(container.textContent).toContain("1.329×10−4 MPa");
    expect(container.textContent).toContain("6252460f8eb087e6");
    expect(richHtml("W(λ) = ∫σ_nom dλ")).toBe("W(λ) = ∫σ<sub>nom</sub> dλ");
    expect(rich("no tokens")).toBe("no tokens");
  });
});
