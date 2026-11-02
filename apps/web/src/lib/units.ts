/** SI → display conversions; mirrors packages/plotting DISPLAY_UNITS. */
export const DISPLAY: Record<string, [string, number, number]> = {
  Pa: ["MPa", 1e-6, 0],
  "J/m^3": ["MJ/m³", 1e-6, 0],
  "J/m^2": ["J/m²", 1, 0],
  m: ["mm", 1e3, 0],
  "m/cycle": ["nm/cycle", 1e9, 0],
  N: ["N", 1, 0],
  K: ["°C", 1, -273.15],
  s: ["s", 1, 0],
  "1": ["", 1, 0],
};

export function fmt(v: number | null | undefined, digits = 4): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a !== 0 && (a >= 1e5 || a < 1e-3)) return v.toExponential(Math.max(digits - 1, 1));
  return Number(v.toPrecision(digits)).toString();
}

/** Format an SI value in its display unit, e.g. (1.2e6, "Pa") → "1.2 MPa". */
export function show(v: number | null | undefined, si: string, digits = 4): string {
  if (v === null || v === undefined) return "—";
  if (si === "J/m^2" && Math.abs(v) >= 1e4) return `${fmt(v * 1e-3, digits)} kJ/m²`; // toughness range
  const [unit, f, o] = DISPLAY[si] ?? [si, 1, 0];
  const t = fmt(v * f + o, digits);
  return unit ? `${t} ${unit}` : t;
}

export const mm = (m: number | null | undefined) => (m === null || m === undefined ? "" : String(Number((m * 1e3).toPrecision(6))));
export const fromMm = (s: string) => (s.trim() === "" ? null : Number(s) / 1e3);

export const PROPERTY_LABELS: Record<string, string> = {
  elastic_modulus: "弹性模量",
  tensile_strength: "最大应力",
  break_stress: "断裂应力（名义）",
  true_break_stress: "断裂真实应力",
  ultimate_stretch: "断裂拉伸比",
  elongation_at_break: "断裂伸长率",
  work_of_fracture: "断裂功",
  fracture_toughness: "断裂韧性",
  fatigue_threshold: "疲劳阈值",
  hysteresis_energy: "滞后能",
  residual_strain: "残余应变",
  storage_modulus: "储能模量",
  loss_modulus: "损耗模量",
  loss_factor: "损耗因子",
  interfacial_toughness: "界面韧性",
  glass_transition_temperature: "玻璃化转变温度 Tg",
};

export const METHOD_LABELS: Record<string, string> = {
  uniaxial: "单轴拉伸",
  cyclic: "循环拉伸",
  pure_shear: "纯剪切断裂韧性",
  fatigue_steady: "疲劳：稳态能量",
  crack_growth: "疲劳：裂纹扩展速率",
  fatigue_threshold: "疲劳阈值",
  dma: "DMA",
};
