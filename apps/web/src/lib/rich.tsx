/** Display-only typography for formula-like text: “λ_b” → λ with subscript b, “1.3e-4” → 1.3×10⁻⁴.
 * Stored values, CSV and reports keep the plain text. */
import { Fragment, type ReactNode } from "react";

// a standalone number in e-notation (not inside a hash like “087e6f”), or a symbol followed by
// _sub / _{sub}
const TOKEN = /(?<![0-9A-Za-z.])(\d+(?:\.\d+)?)e([+-]?\d+)(?![0-9A-Za-z])|([A-Za-zα-ωΑ-Ω])_(\{[^}]+\}|[A-Za-z0-9]+)/g;

type Piece = { text: string } | { mantissa: string; exp: string } | { base: string; sub: string };

function pieces(s: string): Piece[] {
  const out: Piece[] = [];
  let last = 0;
  for (const m of s.matchAll(TOKEN)) {
    if (m.index! > last) out.push({ text: s.slice(last, m.index) });
    if (m[1] !== undefined) {
      const e = Number(m[2]);
      out.push({ mantissa: m[1], exp: e < 0 ? `−${-e}` : String(e) });
    } else {
      out.push({ base: m[3], sub: m[4].replace(/^\{|\}$/g, "") });
    }
    last = m.index! + m[0].length;
  }
  if (last < s.length) out.push({ text: s.slice(last) });
  return out;
}

/** React rendering (sub/sup elements). Non-string input is returned unchanged. */
export function rich(v: ReactNode): ReactNode {
  if (typeof v !== "string" || !TOKEN.test(v)) return v;
  TOKEN.lastIndex = 0;
  return pieces(v).map((p, i) => (
    <Fragment key={i}>
      {"text" in p && p.text}
      {"mantissa" in p && <>{p.mantissa}×10<sup>{p.exp}</sup></>}
      {"base" in p && <>{p.base}<sub>{p.sub}</sub></>}
    </Fragment>
  ));
}

/** Same as `rich` for Plotly, which accepts <sub>/<sup> in names and titles. */
export function richHtml(s: string): string {
  return pieces(s)
    .map((p) => ("text" in p ? p.text : "mantissa" in p ? `${p.mantissa}×10<sup>${p.exp}</sup>` : `${p.base}<sub>${p.sub}</sub>`))
    .join("");
}
