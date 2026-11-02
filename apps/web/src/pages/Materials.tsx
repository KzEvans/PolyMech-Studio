import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { FileUp } from "lucide-react";
import { api } from "@/lib/api";
import { DISPLAY, METHOD_LABELS, PROPERTY_LABELS, fmt, show } from "@/lib/units";
import { rich } from "@/lib/rich";
import { Chart, type Series } from "@/components/Chart";
import { StatusLine } from "@/components/common";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { Toolbar } from "@/components/shell/AppShell";
import { EmptyState, Panel } from "@/components/common";
import { ComparabilityDialog } from "@/components/compare";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Material = { id: number; name: string; origin: string; polymer_type: string; structure_type: string; n_properties: number };
type Source = {
  kind: string; entry: string; run_id?: number; extraction_method?: string; page?: string; figure?: string; table?: string;
  title?: string; authors?: string; year?: number | null; doi?: string | null; notes?: string;
  experiment_id?: number; specimen?: string; method?: string; version?: number; status?: string; created_at?: string; params?: Record<string, unknown>;
};
type Prop = { id: number; quantity: string; value: number | null; unit: string; uncertainty: number | null; lower_bound: number | null; upper_bound: number | null; conditions: Record<string, unknown>; source: Source };
type Detail = { name: string; origin: string; polymer_type: string; structure_type: string; phase_structure: string; description: string; properties: Prop[] };

/** Fractions stored as SI "1" that readers expect in percent. */
const PERCENT = new Set(["elongation_at_break", "residual_strain"]);
// test_type and analysis parameters are shown once in the entry header, not on every row
const HIDDEN = new Set(["record_key", "reported_text", "reported_unit", "approximate", "test_type", "modulus_stretch_range"]);
const COND_LABELS: Record<string, [string, (v: number) => string]> = {
  temperature_k: ["温度", (v) => `${fmt(v - 273.15)} °C`],
  frequency_hz: ["频率", (v) => `${fmt(v)} Hz`],
  height_m: ["H0", (v) => `${fmt(v * 1e3)} mm`],
  width_m: ["宽度", (v) => `${fmt(v * 1e3)} mm`],
  notch_length_m: ["预切裂纹", (v) => `${fmt(v * 1e3)} mm`],
  hard_region_width_m: ["硬区宽度", (v) => `${fmt(v * 1e3)} mm`],
  stretch_rate_per_s: ["拉伸速率", (v) => `${fmt(v, 3)} s⁻¹`],
  detection_limit_m_per_cycle: ["检测限", (v) => `${fmt(v * 1e9)} nm/cycle`],
  recovery_time_s: ["恢复时间", (v) => (v >= 3600 ? `${fmt(v / 3600)} h` : `${fmt(v / 60)} min`)],
};

function value(p: Prop, v: number | null): string {
  if (v === null) return "—";
  return PERCENT.has(p.quantity) ? `${fmt(v * 100)} %` : show(v, p.unit);
}

function conditions(c: Record<string, unknown>): string {
  return Object.entries(c)
    .filter(([k, v]) => v !== null && v !== "" && !HIDDEN.has(k))
    .map(([k, v]) => {
      const lab = COND_LABELS[k];
      if (lab && typeof v === "number") return `${lab[0]} ${lab[1](v)}`;
      return `${k}=${typeof v === "number" ? Number(v.toPrecision(4)) : String(v)}`;
    })
    .join("；");
}

function SourceCell({ p }: { p: Prop }) {
  const s = p.source;
  if (s.kind === "analysis") return <>分析 #{s.run_id}</>;
  const loc = [`p.${s.page}`, s.figure, s.table].filter(Boolean).join("，");
  return (
    <div className="space-y-0.5">
      <div>{s.authors} {s.year}，《{s.title}》{loc}</div>
      <div className="text-fg-2">
        <Badge variant="outline" className="mr-1">{s.extraction_method === "reported" ? "文献报告值" : "图形数字化估计值"}</Badge>
        {typeof p.conditions.reported_text === "string" && <>原文：{p.conditions.reported_text}</>}
        {p.conditions.approximate === true && <>（约值）</>}
      </div>
      {s.notes && <div className="text-fg-2">{s.notes}</div>}
    </div>
  );
}

type Entry = { key: string; source: Source; props: Prop[] };

/** One entry per analysis version or literature record (newest analyses first). */
function entriesOf(props: Prop[]): Entry[] {
  const map = new Map<string, Entry>();
  for (const p of props) {
    const e = map.get(p.source.entry) ?? { key: p.source.entry, source: p.source, props: [] };
    e.props.push(p);
    map.set(p.source.entry, e);
  }
  const rank = (e: Entry) => (e.source.kind === "analysis" ? -(e.source.run_id ?? 0) : 1e9);
  return [...map.values()].sort((a, b) => rank(a) - rank(b));
}

function entryTitle(s: Source): string {
  if (s.kind === "analysis") return `${s.specimen ?? ""} · ${METHOD_LABELS[s.method ?? ""] ?? s.method} v${s.version}`;
  return `${s.authors?.split(/[,，]/)[0] ?? ""} ${s.year ?? ""}`.trim();
}

function paramsText(params: Record<string, unknown> = {}): string {
  const out: string[] = [];
  const r = params.modulus_stretch_range;
  if (Array.isArray(r)) out.push(`模量拟合 λ ${r[0]}–${r[1]}`);
  if (typeof params.break_stretch === "number") out.push(`人工断裂点 λ ${params.break_stretch}`);
  if (typeof params.smoothing_window === "number") out.push(`平滑 ${params.smoothing_window} 点`);
  return out.join(" · ");
}

function entrySubtitle(s: Source): string {
  if (s.kind === "analysis") {
    const date = s.created_at ? new Date(s.created_at).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
    return [`分析 #${s.run_id}`, date, paramsText(s.params)].filter(Boolean).join(" · ");
  }
  return [s.extraction_method === "reported" ? "文献报告值" : "图形数字化估计值", s.page ? `p.${s.page}` : "", s.figure, s.table].filter(Boolean).join(" · ");
}

function EntryView({ entry, onCompare }: { entry: Entry; onCompare: (p: Prop) => void }) {
  const s = entry.source;
  return (
    <Panel
      title={entryTitle(s)}
      actions={s.kind === "analysis" && s.experiment_id ? (
        <Button size="sm" variant="ghost" asChild><Link to={`/analysis/${s.experiment_id}?run=${s.run_id}`}>打开分析</Link></Button>
      ) : undefined}
    >
      <p className="mb-2 text-fg-2">
        {entrySubtitle(s)}
        {s.status && s.status !== "ok" && <Badge variant="outline" className="ml-2 text-warning">临时</Badge>}
      </p>
      {s.kind === "literature" && <div className="mb-2 text-callout"><SourceCell p={entry.props[0]} /></div>}
      <table className="w-full text-body">
        <thead><tr className="border-b text-left text-fg-2">{["性能", "数值", "区间", "条件", ""].map((h) => <th key={h} className="py-1 pr-3 font-medium">{h}</th>)}</tr></thead>
        <tbody>
          {entry.props.map((p) => (
            <tr key={p.id} className="border-b align-top">
              <td className="py-1 pr-3">{PROPERTY_LABELS[p.quantity] ?? p.quantity}</td>
              <td className="tnum whitespace-nowrap py-1 pr-3">
                {rich(value(p, p.value))}
                {p.uncertainty !== null && <span className="text-fg-2"> ± {rich(value(p, p.uncertainty))}</span>}
              </td>
              <td className="tnum whitespace-nowrap py-1 pr-3 text-fg-2">
                {p.lower_bound !== null || p.upper_bound !== null ? `${p.lower_bound === null ? "" : `≥ ${value(p, p.lower_bound)}`}${p.lower_bound !== null && p.upper_bound !== null ? "，" : ""}${p.upper_bound === null ? "" : `≤ ${value(p, p.upper_bound)}`}` : ""}
              </td>
              <td className="py-1 pr-3 text-callout text-fg-2">{conditions(p.conditions)}</td>
              <td className="py-1"><Button size="sm" variant="ghost" onClick={() => onCompare(p)} aria-label={`检查${PROPERTY_LABELS[p.quantity] ?? p.quantity}的可比性`}>可比性…</Button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

type Quantity = { quantity: string; unit: string; n: number };
type PairPoint = { material_id: number; material: string; origin: string; label: string; x: number; y: number; same_entry: boolean };
type Pairs = { x_unit: string; y_unit: string; points: PairPoint[]; omitted: string[]; caution: string };

/** SI value → display (factor, offset, unit label) for a property. */
function displayOf(q: string, unit: string): [number, number, string] {
  if (PERCENT.has(q)) return [100, 0, "%"];
  const d = DISPLAY[unit];
  return d ? [d[1], d[2], d[0]] : [1, 0, unit];
}

const qLabel = (q: string) => PROPERTY_LABELS[q] ?? q;

/** Ashby-style chart: any two properties, one point per entry (or per material pairing). */
function PropertyChart() {
  const quantities = useQuery({ queryKey: ["property-quantities"], queryFn: () => api.get<Quantity[]>("/properties/quantities") });
  const qs = quantities.data ?? [];
  const [x, setX] = useState("");
  const [y, setY] = useState("");
  const [logX, setLogX] = useState(true);
  const [logY, setLogY] = useState(true);
  const [pairing, setPairing] = useState<"entry" | "material">("entry");
  const [latest, setLatest] = useState(true);
  const [labels, setLabels] = useState(true);
  useEffect(() => {
    if (!qs.length || x) return;
    const has = (q: string) => qs.some((v) => v.quantity === q);
    setX(has("elastic_modulus") ? "elastic_modulus" : qs[0].quantity);
    setY(has("work_of_fracture") ? "work_of_fracture" : (qs.find((v) => v.quantity !== qs[0].quantity)?.quantity ?? ""));
  }, [qs.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const pairs = useQuery({
    queryKey: ["property-pairs", x, y, pairing, latest],
    queryFn: () => api.get<Pairs>(`/properties/pairs?${new URLSearchParams({ x, y, pairing, latest_only: String(latest) })}`),
    enabled: !!x && !!y && x !== y,
  });
  const d = pairs.data;
  const [fx, ox, ux] = d ? displayOf(x, d.x_unit) : [1, 0, ""];
  const [fy, oy, uy] = d ? displayOf(y, d.y_unit) : [1, 0, ""];
  const series: Series[] = useMemo(() => {
    const byMat = new Map<string, PairPoint[]>();
    for (const p of d?.points ?? []) byMat.set(p.material, [...(byMat.get(p.material) ?? []), p]);
    return [...byMat.entries()].map(([name, pts]) => ({
      name: pts[0].origin === "literature" ? `${name}（文献）` : name,
      x: pts.map((p) => p.x * fx + ox),
      y: pts.map((p) => p.y * fy + oy),
      mode: labels ? "text+markers" : "markers",
      // literature points use material names; own analyses also retain their version
      text: labels ? pts.map((p) => (p.origin === "literature" ? name : p.label)) : undefined,
      marker: pts[0].origin === "literature" ? "triangle-up" : "circle",
      markerSize: 11,
    }));
  }, [d, fx, ox, fy, oy, labels]);
  // padded ranges so labels at the edge stay inside the plot (log axes: in decades)
  const padded = (vals: number[], log: boolean): [number | null, number | null] => {
    const v = vals.filter((a) => Number.isFinite(a) && (!log || a > 0));
    if (!v.length) return [null, null];
    const lo = Math.min(...v), hi = Math.max(...v);
    if (log) {
      const k = 10 ** Math.max(0.25, 0.12 * Math.log10(hi / lo));
      return [lo / k, hi * k];
    }
    const pad = (hi - lo || Math.abs(hi) || 1) * 0.1;
    return [lo - pad, hi + pad];
  };
  const xr = padded(series.flatMap((s) => s.x as number[]), logX);
  const yr = padded(series.flatMap((s) => s.y as number[]), logY);
  const pick = (id: string, value: string, set: (v: string) => void, other: string) => (
    <Select value={value} onValueChange={set}>
      <SelectTrigger id={id} className="h-7 w-48"><SelectValue placeholder="选择性能" /></SelectTrigger>
      <SelectContent>{qs.map((q) => <SelectItem key={q.quantity} value={q.quantity} disabled={q.quantity === other}>{qLabel(q.quantity)}（{q.n}）</SelectItem>)}</SelectContent>
    </Select>
  );
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <div className="flex items-center gap-2"><Label htmlFor="px">横轴</Label>{pick("px", x, setX, y)}<label className="flex items-center gap-1.5 text-fg-2"><Switch checked={logX} onCheckedChange={setLogX} aria-label="横轴对数" />对数</label></div>
        <div className="flex items-center gap-2"><Label htmlFor="py">纵轴</Label>{pick("py", y, setY, x)}<label className="flex items-center gap-1.5 text-fg-2"><Switch checked={logY} onCheckedChange={setLogY} aria-label="纵轴对数" />对数</label></div>
        <Select value={pairing} onValueChange={(v) => setPairing(v as "entry" | "material")}>
          <SelectTrigger aria-label="配对方式" className="h-7 w-56"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="entry">同一条目配对（同一样品、同一次分析）</SelectItem>
            <SelectItem value="material">同一材料配对（可跨实验）</SelectItem>
          </SelectContent>
        </Select>
        <label className="flex items-center gap-1.5"><Switch checked={latest} onCheckedChange={setLatest} />每个实验只用最新版本</label>
        <label className="flex items-center gap-1.5"><Switch checked={labels} onCheckedChange={setLabels} />显示标签</label>
      </div>
      {qs.length < 2 ? (
        <EmptyState title="数据库中的性能不足两项">完成分析或导入文献记录后，可在这里比较任意两项性能。</EmptyState>
      ) : pairs.isError ? (
        <StatusLine severity="error">{(pairs.error as Error).message}</StatusLine>
      ) : d && d.points.length === 0 ? (
        <EmptyState title="没有同时具有这两项性能的条目">{pairing === "entry" ? "可改为“同一材料配对”，用同一材料不同实验的数值。" : "换一组性能试试。"}</EmptyState>
      ) : (
        d && (
          <Panel>
            <Chart ariaLabel={`${qLabel(x)}–${qLabel(y)}性能对比图`} series={series} height={560} logX={logX} logY={logY} legendBelow xRange={xr} yRange={yr}
              xTitle={ux ? `${qLabel(x)} (${ux})` : qLabel(x)} yTitle={uy ? `${qLabel(y)} (${uy})` : qLabel(y)} />
          </Panel>
        )
      )}
      {d && (
        <div className="space-y-1">
          <StatusLine severity="info">{d.caution}。圆点为本软件分析结果，三角为文献记录；临时结果不计入。</StatusLine>
          {d.omitted.length > 0 && <StatusLine severity="warning">未绘出（只有上/下界）：{d.omitted.join("；")}</StatusLine>}
        </div>
      )}
    </div>
  );
}

export default function Materials() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [origin, setOrigin] = useState<"" | "experiment" | "literature">("");
  const [sel, setSel] = useState<number | null>(null);
  const [entryKey, setEntryKey] = useState<string | null>(null);
  const [cmp, setCmp] = useState<Prop | null>(null);
  const file = useRef<HTMLInputElement>(null);
  const params = new URLSearchParams({ ...(q ? { q } : {}), ...(origin ? { origin } : {}) }).toString();
  const list = useQuery({ queryKey: ["materials", q, origin], queryFn: () => api.get<Material[]>(`/materials${params ? `?${params}` : ""}`) });
  const detail = useQuery({ queryKey: ["material", sel], queryFn: () => api.get<Detail>(`/materials/${sel}`), enabled: sel !== null });
  const entries = useMemo(() => entriesOf(detail.data?.properties ?? []), [detail.data]);
  const entry = entries.find((e) => e.key === entryKey) ?? entries[0];
  const importLit = useMutation({
    mutationFn: async (f: File) => api.post<{ records_added: number; records_updated: number; records_skipped: number; materials_created: number }>("/literature/import", JSON.parse(await f.text())),
    onSuccess: (r) => {
      toast.success(`文献记录：新增 ${r.records_added} 条，更正 ${r.records_updated} 条，未变化 ${r.records_skipped} 条，新建材料 ${r.materials_created} 个`);
      qc.invalidateQueries({ queryKey: ["materials"] });
      qc.invalidateQueries({ queryKey: ["material"] });
    },
    onError: (e: Error) => toast.error(e instanceof SyntaxError ? "文件不是有效的 JSON" : e.message),
  });
  return (
    <>
      <Toolbar title="材料数据库">
        <div className="flex gap-1" role="radiogroup" aria-label="材料来源">
          {([["", "全部"], ["experiment", "实验"], ["literature", "文献"]] as const).map(([v, label]) => (
            <Button key={v} size="sm" variant={origin === v ? "secondary" : "ghost"} role="radio" aria-checked={origin === v} onClick={() => setOrigin(v)}>{label}</Button>
          ))}
        </div>
        <Input aria-label="搜索材料" placeholder="搜索材料名称" className="h-7 w-56" value={q} onChange={(e) => setQ(e.target.value)} />
        <input ref={file} type="file" accept=".json,application/json" className="hidden" aria-hidden tabIndex={-1}
          onChange={(e) => { const f = e.target.files?.[0]; if (f) importLit.mutate(f); e.target.value = ""; }} />
        <Button size="sm" variant="outline" disabled={importLit.isPending} onClick={() => file.current?.click()}>
          <FileUp className="size-4" aria-hidden />导入文献记录…
        </Button>
      </Toolbar>
      <div className="flex min-h-0 flex-1">
        <nav aria-label="材料列表" className="w-64 shrink-0 overflow-auto border-r bg-inspector p-2">
          <ul className="space-y-0.5">
            {list.data?.map((m) => (
              <li key={m.id}>
                <button type="button" onClick={() => { setSel(m.id); setEntryKey(null); }} aria-current={m.id === sel} className={cn("flex w-full items-center justify-between gap-2 rounded-md px-2 py-1 text-left hover:bg-hover", m.id === sel && "bg-hover font-medium")}>
                  <span className="truncate">{m.name}</span>
                  <span className="flex shrink-0 items-center gap-1">
                    {m.origin === "literature" && <Badge variant="outline">文献</Badge>}
                    <span className="tnum text-fg-2">{m.n_properties}</span>
                  </span>
                </button>
              </li>
            ))}
            {list.data?.length === 0 && <li className="px-2 text-fg-2">没有匹配的材料</li>}
          </ul>
        </nav>
        <main className="min-w-0 flex-1 overflow-auto p-3">
          <Tabs defaultValue="entries">
            <TabsList className="mb-3">
              <TabsTrigger value="entries">按条目查看</TabsTrigger>
              <TabsTrigger value="chart">性能对比图</TabsTrigger>
            </TabsList>
            <TabsContent value="entries">
              {!sel ? (
                <EmptyState title="选择材料查看性能">每次分析（每个版本）和每条文献记录是一个单独的条目；每个数值都关联单位、测试条件与来源。文献记录只登记原文明确给出的数值，缺失的指标留空。</EmptyState>
              ) : detail.data && (
                <div className="space-y-2">
                  <div>
                    <h2 className="text-title3 font-semibold">{detail.data.name}</h2>
                    <p className="text-fg-2">{[detail.data.polymer_type, detail.data.structure_type, detail.data.phase_structure, detail.data.description].filter(Boolean).join(" · ")}</p>
                  </div>
                  {entries.length === 0 ? <p className="text-fg-2">这个材料还没有性能数值。</p> : (
                    <div className="flex items-start gap-3">
                      <ul aria-label="条目" className="w-64 shrink-0 space-y-0.5">
                        {entries.map((e) => (
                          <li key={e.key}>
                            <button type="button" onClick={() => setEntryKey(e.key)} aria-current={e.key === entry?.key}
                              className={cn("w-full rounded-md px-2 py-1.5 text-left hover:bg-hover", e.key === entry?.key && "bg-hover")}>
                              <span className="flex items-center justify-between gap-2">
                                <span className={cn("truncate", e.key === entry?.key && "font-medium")}>{entryTitle(e.source)}</span>
                                {e.source.kind === "literature" ? <Badge variant="outline">文献</Badge> : e.source.status !== "ok" ? <Badge variant="outline" className="text-warning">临时</Badge> : null}
                              </span>
                              <span className="block truncate text-subhead text-fg-2">{entrySubtitle(e.source)}</span>
                            </button>
                          </li>
                        ))}
                      </ul>
                      <div className="min-w-0 flex-1">{entry && <EntryView entry={entry} onCompare={setCmp} />}</div>
                    </div>
                  )}
                </div>
              )}
            </TabsContent>
            <TabsContent value="chart"><PropertyChart /></TabsContent>
          </Tabs>
        </main>
      </div>
      {cmp && <ComparabilityDialog refId={cmp.id} quantity={cmp.quantity} onClose={() => setCmp(null)} />}
    </>
  );
}
