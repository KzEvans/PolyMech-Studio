import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { ArrowDown, ArrowUp, FileJson, GripVertical, ImageDown, LayoutTemplate, Plus, RotateCcw, Save, Send, Sheet, Trash2, X } from "lucide-react";
import { api } from "@/lib/api";
import { METHOD_LABELS } from "@/lib/units";
import { cn } from "@/lib/utils";
import { Toolbar } from "@/components/shell/AppShell";
import { Chart, seriesColor, type ChartLegend, type Series } from "@/components/Chart";
import { EmptyState, StatusLine } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { FormatPicker, OriginJobProgress, useOriginStatus, type OriginJob } from "@/components/origin";
import { hasPrimaryKey, shortcut } from "@/lib/platform";

// mirrors packages/plotting/spec.py DISPLAY_UNITS
const DISPLAY_UNITS: Record<string, Record<string, [number, number]>> = {
  Pa: { Pa: [1, 0], kPa: [1e-3, 0], MPa: [1e-6, 0], GPa: [1e-9, 0] },
  "J/m^3": { "J/m³": [1, 0], "kJ/m³": [1e-3, 0], "MJ/m³": [1e-6, 0] },
  "J/m^2": { "J/m²": [1, 0], "kJ/m²": [1e-3, 0] },
  m: { m: [1, 0], mm: [1e3, 0], "μm": [1e6, 0] },
  "m/cycle": { "m/cycle": [1, 0], "nm/cycle": [1e9, 0], "μm/cycle": [1e6, 0] },
  N: { N: [1, 0], mN: [1e3, 0], kN: [1e-3, 0] },
  "N/m": { "N/m": [1, 0], "kN/m": [1e-3, 0] },
  K: { K: [1, 0], "°C": [1, -273.15] },
  s: { s: [1, 0], min: [1 / 60, 0], h: [1 / 3600, 0] },
  Hz: { Hz: [1, 0] },
  "1": { "": [1, 0], "%": [100, 0] },
  cycle: { "": [1, 0] },
};

type Axis = { label: string; si_unit: string; unit: string; scale: "linear" | "log"; min: number | null; max: number | null };
type Source = { run_id?: number | null; x_key?: string | null; y_key?: string | null; y_err_key?: string | null; x?: number[] | null; y?: number[] | null; y_err?: number[] | null };
type Marker = "circle" | "square" | "triangle" | "diamond" | "cross" | "none";
type SeriesSpec = { name: string; source: Source; kind: "line" | "scatter" | "line+markers"; color: string | null; line_width: number; line_style: "solid" | "dash" | "dot" | "dashdot"; marker: Marker; marker_size: number; marker_filled: boolean; y_axis: "y" | "y2"; error_bars: boolean; visible: boolean; note: string };
type PanelSpec = { id: string; template_id: string; title: string; x: Axis; y: Axis; y2: Axis | null; series: SeriesSpec[]; legend: ChartLegend; annotations: unknown[] };
type Layout = { rows: number; cols: number; width_mm: number; height_mm: number; dpi: number; panel_labels: boolean };
type PlotSpec = { spec_version: string; template_id: string; template_version: string; title: string; panels: PanelSpec[]; layout: Layout; style: Record<string, unknown> };
type Template = { id: string; name: string; x_key: string | null; y_key: string | null; x_property: string | null; y_property: string | null; description: string };
type RunRow = { id: number; experiment_id: number; method: string; version: number; status: string; material_name: string };
type Saved = { id: number; name: string; kind: string; template_id: string; n_panels: number; updated_at: string };

const STYLE_KEYS = ["color", "line_width", "line_style", "kind", "marker", "marker_size", "marker_filled", "error_bars", "visible", "name"] as const;
const PLOTLY_SYMBOL: Record<Marker, string> = { circle: "circle", square: "square", triangle: "triangle-up", diamond: "diamond", cross: "x", none: "circle" };
const MARKER_LABELS: Record<Marker, string> = { circle: "圆", square: "方", triangle: "三角", diamond: "菱形", cross: "叉", none: "无" };
const conv = (a: Axis): [number, number] => DISPLAY_UNITS[a.si_unit]?.[a.unit] ?? [1, 0];
const letter = (k: number) => `(${String.fromCharCode(97 + k)})`;

/** Default series colour exactly as the exported figure picks it (PlotSpec.color_of): by series
 * count from style.palette_by_count, else by position from style.palette. Saved figures from
 * before 2026-10-27 have no palette_by_count and keep their Okabe–Ito colours. */
function specColor(style: PlotSpec["style"], i: number, n: number): string | undefined {
  const byCount = (style.palette_by_count ?? {}) as Record<string, string[]>;
  const p = byCount[String(n)] ?? (style.palette as string[] | undefined);
  return p?.length ? p[i % p.length] : undefined;
}

/** Smallest rows × cols grid (shrinking the current one) that still holds n panels. */
function fitLayout(rows: number, cols: number, n: number): { rows: number; cols: number } {
  while (rows > 1 && (rows - 1) * cols >= n) rows--;
  while (cols > 1 && rows * (cols - 1) >= n) cols--;
  return { rows, cols };
}
const runsOf = (p: PanelSpec) => [...new Set(p.series.map((s) => s.source.run_id).filter((x): x is number => typeof x === "number"))];

/** Keep the user's styling for series that survive a rebuild (same run, same axis). */
function carryStyles(next: PanelSpec, prev: PanelSpec | undefined): PanelSpec {
  if (!prev) return next;
  const series = next.series.map((s) => {
    const old = prev.series.find((o) => o.source.run_id === s.source.run_id && o.y_axis === s.y_axis && o.source.y_key === s.source.y_key);
    if (!old) return s;
    const keep: Partial<SeriesSpec> = {};
    for (const k of STYLE_KEYS) (keep as Record<string, unknown>)[k] = old[k];
    return { ...s, ...keep };
  });
  prev.series.forEach((s, i) => { if (s.source.run_id == null) series.splice(i, 0, s); });
  return {
    ...next,
    id: prev.id,
    title: prev.title,
    series,
  };
}

export default function PlotStudio() {
  const [params] = useSearchParams();
  const qc = useQueryClient();
  const templates = useQuery({ queryKey: ["plot-templates"], queryFn: () => api.get<Template[]>("/plot-templates") });
  const runs = useQuery({ queryKey: ["analyses", "all"], queryFn: () => api.get<RunRow[]>("/analyses?limit=200") });
  const configs = useQuery({ queryKey: ["plot-configs", "config"], queryFn: () => api.get<Saved[]>("/plot-configs") });
  const styleTemplates = useQuery({ queryKey: ["plot-configs", "template"], queryFn: () => api.get<Saved[]>("/plot-configs?kind=template") });
  const [spec, setSpec] = useState<PlotSpec | null>(null);
  const [active, setActive] = useState(0);
  const [configId, setConfigId] = useState<number | null>(null);
  const [configName, setConfigName] = useState("");
  const [notes, setNotes] = useState<string[]>([]);
  const [dragSeries, setDragSeries] = useState<number | null>(null);
  const [originOpen, setOriginOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (spec && hasPrimaryKey(event) && event.key.toLowerCase() === "e" && !event.altKey && !event.shiftKey) {
        event.preventDefault();
        setExportOpen(true);
      }
    };
    const onMenu = (event: Event) => {
      if (spec && (event as CustomEvent<string>).detail === "export_figure") setExportOpen(true);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("polymech:menu", onMenu);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("polymech:menu", onMenu);
    };
  }, [spec]);

  const tpl = (id: string) => templates.data?.find((t) => t.id === id);
  const runLabel = (id: number) => {
    const r = runs.data?.find((x) => x.id === id);
    return r ? `${r.material_name} v${r.version}` : `#${id}`;
  };
  const panel = spec?.panels[active];

  /** Build one panel from a template and runs (or from the materials DB for comparison templates). */
  const buildPanel = async (templateId: string, runIds: number[]): Promise<{ panel: PanelSpec; base: PlotSpec; notes: string[] } | null> => {
    const t = tpl(templateId);
    if (!t) return null;
    if (t.x_property) {
      const out = await api.post<{ spec: PlotSpec; omitted: string[]; caution: string }>("/plots/property-spec", { template_id: templateId });
      return { panel: out.spec.panels[0], base: out.spec, notes: [out.caution, ...out.omitted] };
    }
    if (!runIds.length) return null;
    const s = await api.post<PlotSpec>("/plots/spec", { template_id: templateId, runs: runIds.map((id) => [id, runLabel(id)]) });
    return { panel: s.panels[0], base: s, notes: [] };
  };

  const setPanel = (k: number, next: PanelSpec | null, base?: PlotSpec) => {
    setSpec((cur) => {
      if (!cur) {
        if (!next || !base) return cur;
        return { ...base, panels: [{ ...next, id: "a" }] };
      }
      const panels = [...cur.panels];
      if (next) panels[k] = next;
      else panels.splice(k, 1);
      return { ...cur, panels, template_id: panels[0]?.template_id || cur.template_id };
    });
  };

  const rebuild = useMutation({
    mutationFn: async ({ k, templateId, runIds, keepStyle }: { k: number; templateId: string; runIds: number[]; keepStyle: boolean }) => {
      const r = await buildPanel(templateId, runIds);
      return { k, r, keepStyle };
    },
    onSuccess: ({ k, r, keepStyle }) => {
      if (!r) {
        if (spec) setPanel(k, { ...spec.panels[k], series: [] });
        return;
      }
      const prev = spec?.panels[k];
      const next = keepStyle ? carryStyles(r.panel, prev) : { ...r.panel, id: prev?.id ?? "a", title: prev?.title ?? "" };
      setPanel(k, next, r.base);
      setNotes(r.notes);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  // deep link from the analysis page: /plots?run=12&template=...
  useEffect(() => {
    const run = params.get("run");
    if (templates.data && runs.data && !spec && run) {
      rebuild.mutate({ k: 0, templateId: params.get("template") || "nominal_stress_stretch", runIds: [Number(run)], keepStyle: false });
    }
  }, [!!templates.data, !!runs.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const resolved = useQuery({
    queryKey: ["resolve", JSON.stringify(spec?.panels.map((p) => p.series.map((s) => s.source)))],
    queryFn: () => api.post<PlotSpec>("/plots/resolve", spec),
    enabled: !!spec && spec.panels.some((p) => p.series.length > 0),
  });

  const legacyPalette = !!spec && !Object.keys((spec.style.palette_by_count ?? {}) as object).length;
  const chartSeries = (k: number): Series[] => {
    const p = spec?.panels[k];
    const rp = resolved.data?.panels[k];
    if (!p || !rp) return [];
    const [fx, ox] = conv(p.x);
    return p.series.flatMap((s, i) => {
      const src = rp.series[i]?.source;
      if (!s.visible || !src?.x || !src?.y) return [];
      const ax = s.y_axis === "y2" && p.y2 ? p.y2 : p.y;
      const [fy, oy] = conv(ax);
      return [{
        name: s.name,
        x: src.x.map((v) => v * fx + ox),
        y: src.y.map((v) => v * fy + oy),
        yErr: s.error_bars && src.y_err ? src.y_err.map((v) => v * fy) : undefined,
        mode: s.kind === "line" ? "lines" : s.kind === "scatter" ? "markers" : "lines+markers",
        dash: s.line_style,
        yaxis: s.y_axis,
        // same rule as the export; the default style is left to the chart (dark-mode aware)
        color: s.color ?? (legacyPalette ? specColor(spec!.style, i, p.series.length) : undefined),
        lineWidth: s.line_width * 1.5,
        marker: PLOTLY_SYMBOL[s.marker] + (s.marker_filled || s.marker === "cross" ? "" : "-open"),
        markerSize: s.marker_size * 1.5,
      } as Series];
    });
  };

  const patchPanel = (p: Partial<PanelSpec>) => spec && panel && setPanel(active, { ...panel, ...p });
  const patchAxis = (k: "x" | "y" | "y2", a: Partial<Axis>) => panel?.[k] && patchPanel({ [k]: { ...panel[k]!, ...a } });
  const patchSeries = (i: number, s: Partial<SeriesSpec>) => panel && patchPanel({ series: panel.series.map((x, j) => (j === i ? { ...x, ...s } : x)) });
  const moveSeries = (from: number, to: number) => {
    if (!panel || to < 0 || to >= panel.series.length || from === to) return;
    const list = [...panel.series];
    const [s] = list.splice(from, 1);
    list.splice(to, 0, s);
    patchPanel({ series: list });
  };
  const patchLayout = (l: Partial<Layout>) => spec && setSpec({ ...spec, layout: { ...spec.layout, ...l } });

  const addRun = (k: number, runId: number) => {
    const p = spec?.panels[k];
    const templateId = p?.template_id || spec?.template_id || "nominal_stress_stretch";
    if (tpl(templateId)?.x_property) return toast.error("材料性能对比面板的数据来自材料数据库，不能添加分析结果");
    const ids = p ? runsOf(p) : [];
    if (ids.includes(runId)) return;
    rebuild.mutate({ k, templateId, runIds: [...ids, runId], keepStyle: true });
  };
  const removeSeries = (i: number) => {
    if (!panel) return;
    const runId = panel.series[i].source.run_id;
    // removing a run removes all its series in this panel (e.g. both axes of a double-y plot)
    patchPanel({ series: panel.series.filter((s, j) => (runId != null ? s.source.run_id !== runId : j !== i)) });
  };
  const addPanel = () => {
    if (!spec) return;
    const { rows, cols } = spec.layout;
    const n = spec.panels.length + 1;
    const layout = n > rows * cols ? (cols <= rows ? { cols: cols + 1 } : { rows: rows + 1 }) : {};
    const blank: PanelSpec = { ...spec.panels[active], id: String.fromCharCode(96 + n), title: "", series: [] };
    setSpec({ ...spec, panels: [...spec.panels, blank], layout: { ...spec.layout, ...layout, width_mm: Math.max(spec.layout.width_mm, 170) } });
    setActive(n - 1);
  };
  const removePanel = () => {
    if (!spec || spec.panels.length < 2) return;
    // shrink the grid so the remaining panels fill it (no empty cell in preview or export),
    // and relabel panels (a), (b)… in order
    const panels = spec.panels.filter((_, k) => k !== active).map((p, k) => ({ ...p, id: String.fromCharCode(97 + k) }));
    setSpec({
      ...spec,
      panels,
      template_id: panels[0].template_id || spec.template_id,
      layout: { ...spec.layout, ...fitLayout(spec.layout.rows, spec.layout.cols, panels.length) },
    });
    setActive(Math.max(0, active - 1));
  };

  const exportFig = (format: "png" | "svg" | "pdf") =>
    api.download("/plots/export", { spec, format, filename: configName || spec?.template_id || "figure" }, `figure.${format}`).catch((e: Error) => toast.error(e.message));
  const exportData = () => api.download("/plots/data.csv", { spec }, "plot_data.csv").catch((e: Error) => toast.error(e.message));
  const downloadSpec = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(spec, null, 2)], { type: "application/json" }));
    a.download = `${configName || spec?.template_id || "figure"}.plotspec.json`;
    a.click();
  };

  const save = useMutation({
    mutationFn: (kind: "config" | "template") => {
      const body = { name: configName || tpl(spec!.template_id)?.name || "图表", spec, kind, analysis_run_id: spec ? (runsOf(spec.panels[0])[0] ?? null) : null };
      return kind === "config" && configId ? api.put<{ id: number }>(`/plot-configs/${configId}`, body) : api.post<{ id: number }>("/plot-configs", body);
    },
    onSuccess: (r, kind) => {
      if (kind === "config") setConfigId(r.id);
      qc.invalidateQueries({ queryKey: ["plot-configs"] });
      toast.success(kind === "config" ? "绘图配置已保存，可在下次打开时恢复" : "已保存为自定义模板：版式、坐标轴与系列样式可套用到其他数据");
    },
    onError: (e: Error) => toast.error(e.message),
  });
  const load = async (id: number) => {
    try {
      const c = await api.get<{ id: number; name: string; spec: PlotSpec }>(`/plot-configs/${id}`);
      setSpec(c.spec);
      setActive(0);
      setConfigId(c.id);
      setConfigName(c.name);
      setNotes([]);
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  /** Apply a saved style template: layout, style, axes, legend and series styling by position; data stays. */
  const applyTemplate = async (id: number) => {
    if (!spec) return;
    try {
      const t = (await api.get<{ spec: PlotSpec }>(`/plot-configs/${id}`)).spec;
      const panels = spec.panels.map((p, k) => {
        const tp = t.panels[Math.min(k, t.panels.length - 1)];
        const sameAxes = tp.x.si_unit === p.x.si_unit && tp.y.si_unit === p.y.si_unit;
        return {
          ...p,
          title: tp.title || p.title,
          legend: tp.legend,
          ...(sameAxes ? { x: tp.x, y: tp.y, y2: p.y2 && tp.y2 && tp.y2.si_unit === p.y2.si_unit ? tp.y2 : p.y2 } : {}),
          series: p.series.map((s, i) => {
            const ts = tp.series[i];
            if (!ts) return s;
            const keep: Partial<SeriesSpec> = {};
            for (const key of STYLE_KEYS) if (key !== "name") (keep as Record<string, unknown>)[key] = ts[key];
            return { ...s, ...keep };
          }),
        };
      });
      setSpec({ ...spec, panels, layout: { ...t.layout, rows: Math.max(t.layout.rows, spec.layout.rows), cols: Math.max(t.layout.cols, spec.layout.cols) }, style: t.style });
      toast.success("已套用自定义模板（坐标轴单位不一致的面板保留原坐标轴）");
    } catch (e) {
      toast.error((e as Error).message);
    }
  };
  const removeSaved = async (id: number) => {
    await api.delete(`/plot-configs/${id}`).catch((e: Error) => toast.error(e.message));
    if (id === configId) setConfigId(null);
    qc.invalidateQueries({ queryKey: ["plot-configs"] });
  };

  const activeTemplate = panel ? tpl(panel.template_id || spec!.template_id) : undefined;
  const retainedData = !activeTemplate?.x_property && !!panel?.series.some((s) => s.source.run_id == null);
  const panelRuns = useMemo(() => (panel ? runsOf(panel) : []), [panel]);
  const hasErr = (i: number) => !!resolved.data?.panels[active]?.series[i]?.source.y_err;

  return (
    <>
      <Toolbar title="绘图工作室" subtitle={activeTemplate?.name}>
        <Button size="sm" variant="ghost" disabled={!panel || retainedData || rebuild.isPending} title={retainedData ? "此面板使用保留的曲线数据，请直接调整样式" : "当前面板恢复模板默认样式（数据不变）"}
          onClick={() => panel && rebuild.mutate({ k: active, templateId: panel.template_id || spec!.template_id, runIds: panelRuns, keepStyle: false })}>
          <RotateCcw className="size-4" aria-hidden />恢复默认
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild><Button size="sm" variant="ghost" disabled={!spec}><FileJson className="size-4" aria-hidden />导出数据与配置</Button></DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={exportData}><Sheet className="size-4" aria-hidden />图中数据（CSV，完整分辨率）</DropdownMenuItem>
            <DropdownMenuItem onSelect={downloadSpec}><FileJson className="size-4" aria-hidden />绘图配置（JSON）</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <Button size="sm" variant="ghost" disabled={!spec || save.isPending} onClick={() => save.mutate("template")} title="保存版式、坐标轴与系列样式，套用到其他数据">
          <LayoutTemplate className="size-4" aria-hidden />保存为模板
        </Button>
        <Button size="sm" variant="outline" disabled={!spec || save.isPending} onClick={() => save.mutate("config")}><Save className="size-4" aria-hidden />{configId ? "更新配置" : "保存配置"}</Button>
        <Button size="sm" variant="outline" disabled={!spec} onClick={() => setOriginOpen(true)} title="在 Origin 中生成与当前图一致、可编辑的图页">
          <Send className="size-4" aria-hidden />导出到 Origin…
        </Button>
        <DropdownMenu open={exportOpen} onOpenChange={setExportOpen}>
          <DropdownMenuTrigger asChild>
            <Button size="sm" disabled={!spec} title={`导出图片（${shortcut("E")}）`}><ImageDown className="size-4" aria-hidden />导出图片</Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => exportFig("png")}>PNG（{spec?.layout.dpi ?? 600} dpi）</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => exportFig("svg")}>SVG（文字可编辑）</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => exportFig("pdf")}>PDF</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </Toolbar>
      {originOpen && spec && <PlotOriginDialog spec={spec} name={configName} onClose={() => setOriginOpen(false)} />}
      <div className="flex min-h-0 flex-1">
        <nav aria-label="模板与数据" className="w-64 shrink-0 space-y-3 overflow-auto border-r bg-inspector p-2">
          <section>
            <h2 className="px-1 pb-1 text-subhead font-medium text-fg-2">模板{spec && spec.panels.length > 1 ? `（应用到面板 ${letter(active)}）` : ""}</h2>
            <ul className="space-y-0.5">
              {templates.data?.map((t) => (
                <li key={t.id}>
                  <button type="button" aria-current={t.id === panel?.template_id}
                    onClick={() => rebuild.mutate({ k: active, templateId: t.id, runIds: t.x_property ? [] : panelRuns.length ? panelRuns : [], keepStyle: false })}
                    disabled={retainedData || (!t.x_property && !panelRuns.length && !!spec)}
                    className={cn("w-full rounded-md px-2 py-1 text-left hover:bg-hover disabled:opacity-50", t.id === panel?.template_id && "bg-hover font-medium")}
                    title={retainedData ? "此面板使用保留的曲线数据，请在新面板中选择其他模板" : !t.x_property && !panelRuns.length && spec ? "先向该面板添加分析结果" : t.description}>
                    {t.name}{t.x_property && <span className="ml-1 text-fg-2">· 材料库</span>}
                  </button>
                </li>
              ))}
            </ul>
          </section>
          <section>
            <h2 className="px-1 pb-1 text-subhead font-medium text-fg-2">分析结果（拖到面板，或点 + 添加）</h2>
            <ul className="space-y-0.5">
              {runs.data?.map((r) => (
                <li key={r.id} draggable onDragStart={(e) => { e.dataTransfer.setData("application/x-polymech-run", String(r.id)); e.dataTransfer.effectAllowed = "copy"; }}
                  className={cn("flex cursor-grab items-center gap-1 rounded-md px-1 py-0.5 hover:bg-hover", panelRuns.includes(r.id) && "font-medium")}>
                  <GripVertical className="size-3.5 shrink-0 text-fg-3" aria-hidden />
                  <span className="min-w-0 flex-1 truncate" title={r.material_name}>{r.material_name} · {METHOD_LABELS[r.method] ?? r.method} v{r.version}</span>
                  <Button size="icon" variant="ghost" className="size-6" aria-label={`把 ${runLabel(r.id)} 添加到${spec ? `面板 ${letter(active)}` : "新图"}`}
                    disabled={panelRuns.includes(r.id)}
                    onClick={() => (spec ? addRun(active, r.id) : rebuild.mutate({ k: 0, templateId: "nominal_stress_stretch", runIds: [r.id], keepStyle: false }))}>
                    <Plus className="size-3.5" aria-hidden />
                  </Button>
                </li>
              ))}
            </ul>
          </section>
          {(configs.data?.length ?? 0) > 0 && (
            <section>
              <h2 className="px-1 pb-1 text-subhead font-medium text-fg-2">已保存的图</h2>
              <ul className="space-y-0.5">
                {configs.data!.map((c) => (
                  <li key={c.id} className="group flex items-center">
                    <button type="button" onClick={() => load(c.id)} className={cn("min-w-0 flex-1 truncate rounded-md px-2 py-1 text-left hover:bg-hover", c.id === configId && "bg-hover font-medium")}>
                      {c.name}{c.n_panels > 1 && <span className="text-fg-2"> · {c.n_panels} 面板</span>}
                    </button>
                    <Button size="icon" variant="ghost" className="size-6 opacity-0 group-hover:opacity-100 focus-visible:opacity-100" aria-label={`删除已保存的图 ${c.name}`} onClick={() => removeSaved(c.id)}><X className="size-3.5" aria-hidden /></Button>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {(styleTemplates.data?.length ?? 0) > 0 && (
            <section>
              <h2 className="px-1 pb-1 text-subhead font-medium text-fg-2">自定义模板（套用样式）</h2>
              <ul className="space-y-0.5">
                {styleTemplates.data!.map((c) => (
                  <li key={c.id} className="group flex items-center">
                    <button type="button" disabled={!spec} onClick={() => applyTemplate(c.id)} className="min-w-0 flex-1 truncate rounded-md px-2 py-1 text-left hover:bg-hover disabled:opacity-50">{c.name}</button>
                    <Button size="icon" variant="ghost" className="size-6 opacity-0 group-hover:opacity-100 focus-visible:opacity-100" aria-label={`删除自定义模板 ${c.name}`} onClick={() => removeSaved(c.id)}><X className="size-3.5" aria-hidden /></Button>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </nav>

        <main className="min-w-0 flex-1 overflow-auto p-3">
          {!spec ? (
            <EmptyState title="把左侧的分析结果拖到这里，或点 + 开始">也可以选择“材料库”对比模板，直接用材料数据库中的性能数值作图。预览使用保形下采样；导出总是使用完整数据。</EmptyState>
          ) : (
            <div className="space-y-2">
              {resolved.isError && <StatusLine severity="error">{(resolved.error as Error).message}</StatusLine>}
              {notes.map((n) => <StatusLine key={n} severity="info">{n}</StatusLine>)}
              <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${spec.layout.cols}, minmax(0, 1fr))` }}>
                {spec.panels.map((p, k) => (
                  <section key={k} aria-label={`面板 ${letter(k)}`}
                    onClick={() => setActive(k)}
                    onDragOver={(e) => { if (e.dataTransfer.types.includes("application/x-polymech-run")) { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; } }}
                    onDrop={(e) => { const id = Number(e.dataTransfer.getData("application/x-polymech-run")); if (id) { e.preventDefault(); setActive(k); addRun(k, id); } }}
                    className={cn("rounded-lg border bg-content p-2 transition-shadow duration-[var(--dur-micro)]", k === active && spec.panels.length > 1 ? "ring-2 ring-[var(--accent-text)]" : "")}>
                    <div className="flex items-center gap-2 px-1 text-callout text-fg-2">
                      {spec.panels.length > 1 && spec.layout.panel_labels && <span className="font-semibold text-fg-1">{letter(k)}</span>}
                      <span className="truncate">{p.title || tpl(p.template_id)?.name}</span>
                    </div>
                    {p.series.length === 0 ? (
                      <div className="grid h-60 place-items-center text-fg-2">把分析结果拖到这个面板</div>
                    ) : (
                      <Chart
                        ariaLabel={`面板 ${letter(k)}：${tpl(p.template_id)?.name ?? "图表"}预览`}
                        series={chartSeries(k)}
                        xTitle={axisTitle(p.x)}
                        yTitle={axisTitle(p.y)}
                        y2Title={p.y2 ? axisTitle(p.y2) : undefined}
                        logX={p.x.scale === "log"}
                        logY={p.y.scale === "log"}
                        xRange={[p.x.min, p.x.max]}
                        yRange={[p.y.min, p.y.max]}
                        legend={p.legend}
                        height={spec.panels.length > 1 ? 320 : 460}
                      />
                    )}
                  </section>
                ))}
              </div>
              <p className="text-subhead text-fg-2">
                输出 {spec.layout.width_mm}×{spec.layout.height_mm} mm · {spec.layout.rows}×{spec.layout.cols} 版面 · 配色 {legacyPalette ? "Okabe–Ito（色盲友好）" : "论文图配色（按曲线条数）"} · 预览为屏幕近似，导出由 Matplotlib 按图中样式生成
              </p>
            </div>
          )}
        </main>

        <aside aria-label="图表属性" className="w-80 shrink-0 space-y-4 overflow-auto border-l bg-inspector p-3">
          {spec && panel && (
            <>
              <div className="space-y-1">
                <Label htmlFor="cfgname">名称</Label>
                <Input id="cfgname" className="h-7" value={configName} placeholder={activeTemplate?.name} onChange={(e) => setConfigName(e.target.value)} />
              </div>
              <fieldset className="space-y-2">
                <legend className="text-headline font-semibold">版面</legend>
                <div className="grid grid-cols-2 gap-2">
                  <Num label="行" value={spec.layout.rows} min={1} step={1} onChange={(v) => v * spec.layout.cols >= spec.panels.length && patchLayout({ rows: v })} />
                  <Num label="列" value={spec.layout.cols} min={1} step={1} onChange={(v) => v * spec.layout.rows >= spec.panels.length && patchLayout({ cols: v })} />
                  <Num label="宽度 (mm)" value={spec.layout.width_mm} min={20} step={5} onChange={(v) => patchLayout({ width_mm: v })} />
                  <Num label="高度 (mm)" value={spec.layout.height_mm} min={20} step={5} onChange={(v) => patchLayout({ height_mm: v })} />
                </div>
                <label className="flex items-center gap-2"><Switch checked={spec.layout.panel_labels} onCheckedChange={(c) => patchLayout({ panel_labels: c })} />面板标号 (a)(b)…</label>
                <div className="flex gap-2">
                  <Button size="sm" variant="outline" onClick={addPanel}><Plus className="size-4" aria-hidden />添加面板</Button>
                  <Button size="sm" variant="ghost" disabled={spec.panels.length < 2} onClick={removePanel}><Trash2 className="size-4" aria-hidden />删除面板 {letter(active)}</Button>
                </div>
                <p className="text-subhead text-fg-2">单栏约 85 mm，双栏约 170–180 mm。</p>
              </fieldset>
              {spec.panels.length > 1 && (
                <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="正在编辑的面板">
                  {spec.panels.map((_, k) => <Button key={k} size="sm" variant={k === active ? "secondary" : "ghost"} role="radio" aria-checked={k === active} onClick={() => setActive(k)}>{letter(k)}</Button>)}
                </div>
              )}
              <div className="space-y-1">
                <Label htmlFor="ptitle">面板标题</Label>
                <Input id="ptitle" className="h-7" value={panel.title} placeholder="（无）" onChange={(e) => patchPanel({ title: e.target.value })} />
              </div>
              {(["x", "y", "y2"] as const).map((k) =>
                panel[k] ? (
                  <fieldset key={k} className="space-y-2">
                    <legend className="text-headline font-semibold">{k === "x" ? "X 轴" : k === "y" ? "Y 轴" : "右 Y 轴"}</legend>
                    <Input aria-label={`${k} 轴标题`} className="h-7" value={panel[k]!.label} onChange={(e) => patchAxis(k, { label: e.target.value })} />
                    <div className="flex items-center gap-2">
                      <Select value={panel[k]!.unit} onValueChange={(u) => patchAxis(k, { unit: u, min: null, max: null })}>
                        <SelectTrigger aria-label={`${k} 轴单位`} className="h-7 w-28"><SelectValue placeholder="无量纲" /></SelectTrigger>
                        <SelectContent>{Object.keys(DISPLAY_UNITS[panel[k]!.si_unit] ?? { "": 0 }).map((u) => <SelectItem key={u || "none"} value={u}>{u || "无量纲"}</SelectItem>)}</SelectContent>
                      </Select>
                      <label className="flex items-center gap-1.5 text-callout">
                        <Switch checked={panel[k]!.scale === "log"} onCheckedChange={(c) => patchAxis(k, { scale: c ? "log" : "linear" })} aria-label={`${k} 轴对数坐标`} />对数
                      </label>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <Input aria-label={`${k} 轴最小值`} type="number" step="any" className="tnum h-7" placeholder="最小（自动）" value={panel[k]!.min ?? ""} onChange={(e) => patchAxis(k, { min: e.target.value === "" ? null : Number(e.target.value) })} />
                      <Input aria-label={`${k} 轴最大值`} type="number" step="any" className="tnum h-7" placeholder="最大（自动）" value={panel[k]!.max ?? ""} onChange={(e) => patchAxis(k, { max: e.target.value === "" ? null : Number(e.target.value) })} />
                    </div>
                  </fieldset>
                ) : null,
              )}
              <fieldset className="space-y-2">
                <legend className="text-headline font-semibold">图例</legend>
                <label className="flex items-center gap-2"><Switch checked={panel.legend.show} onCheckedChange={(c) => patchPanel({ legend: { ...panel.legend, show: c } })} />显示图例</label>
                <label className="flex items-center gap-2"><Switch checked={panel.legend.frame} onCheckedChange={(c) => patchPanel({ legend: { ...panel.legend, frame: c } })} />图例边框</label>
                <Select value={panel.legend.position} onValueChange={(v) => {
                  const position = (["best", "upper left", "upper right", "lower left", "lower right", "outside"] as const).find((p) => p === v);
                  if (position) patchPanel({ legend: { ...panel.legend, position } });
                }}>
                  <SelectTrigger aria-label="图例位置" className="h-7 w-full"><SelectValue /></SelectTrigger>
                  <SelectContent>{["best", "upper left", "upper right", "lower left", "lower right", "outside"].map((p) => <SelectItem key={p} value={p}>{{ best: "自动", "upper left": "左上", "upper right": "右上", "lower left": "左下", "lower right": "右下", outside: "图外右侧" }[p]}</SelectItem>)}</SelectContent>
                </Select>
              </fieldset>
              <fieldset className="space-y-3">
                <legend className="text-headline font-semibold">系列（拖动排序）</legend>
                {panel.series.length === 0 && <p className="text-fg-2">该面板还没有数据。</p>}
                {panel.series.map((s, i) => (
                  <div key={`${s.source.run_id ?? s.name}-${s.y_axis}-${i}`} draggable
                    onDragStart={(e) => { setDragSeries(i); e.dataTransfer.effectAllowed = "move"; }}
                    onDragOver={(e) => { if (dragSeries !== null) e.preventDefault(); }}
                    onDrop={(e) => { e.preventDefault(); if (dragSeries !== null) moveSeries(dragSeries, i); setDragSeries(null); }}
                    onDragEnd={() => setDragSeries(null)}
                    className={cn("space-y-1.5 rounded-md border bg-content p-2", dragSeries === i && "opacity-50")}>
                    <div className="flex items-center gap-1.5">
                      <GripVertical className="size-4 shrink-0 cursor-grab text-fg-3" aria-hidden />
                      <input type="color" aria-label={`${s.name} 颜色`} value={s.color ?? (legacyPalette ? specColor(spec.style, i, panel.series.length) : undefined) ?? seriesColor(i, panel.series.length)} onChange={(e) => patchSeries(i, { color: e.target.value })} className="size-6 shrink-0 cursor-pointer rounded border" />
                      <Input aria-label="系列名称（图例）" className="h-7" value={s.name} onChange={(e) => patchSeries(i, { name: e.target.value })} />
                      <Switch checked={s.visible} onCheckedChange={(c) => patchSeries(i, { visible: c })} aria-label={`显示 ${s.name}`} />
                    </div>
                    {s.note && <p className="text-subhead text-fg-2">{s.note}</p>}
                    <div className="grid grid-cols-3 gap-1.5">
                      <Select value={s.kind} onValueChange={(v) => patchSeries(i, { kind: v as SeriesSpec["kind"], marker: v === "line" ? "none" : s.marker === "none" ? "circle" : s.marker })}>
                        <SelectTrigger aria-label={`${s.name} 图形`} className="h-7"><SelectValue /></SelectTrigger>
                        <SelectContent><SelectItem value="line">线</SelectItem><SelectItem value="scatter">散点</SelectItem><SelectItem value="line+markers">线+点</SelectItem></SelectContent>
                      </Select>
                      <Select value={s.line_style} onValueChange={(v) => patchSeries(i, { line_style: v as SeriesSpec["line_style"] })} disabled={s.kind === "scatter"}>
                        <SelectTrigger aria-label={`${s.name} 线型`} className="h-7"><SelectValue /></SelectTrigger>
                        <SelectContent><SelectItem value="solid">实线</SelectItem><SelectItem value="dash">虚线</SelectItem><SelectItem value="dot">点线</SelectItem><SelectItem value="dashdot">点划线</SelectItem></SelectContent>
                      </Select>
                      <Num label="线宽 pt" hideLabel value={s.line_width} min={0.25} step={0.25} onChange={(v) => patchSeries(i, { line_width: v })} />
                    </div>
                    {s.kind !== "line" && (
                      <div className="grid grid-cols-3 items-center gap-1.5">
                        <Select value={s.marker} onValueChange={(v) => patchSeries(i, { marker: v as Marker })}>
                          <SelectTrigger aria-label={`${s.name} 符号`} className="h-7"><SelectValue /></SelectTrigger>
                          <SelectContent>{(Object.keys(MARKER_LABELS) as Marker[]).filter((m) => m !== "none").map((m) => <SelectItem key={m} value={m}>{MARKER_LABELS[m]}</SelectItem>)}</SelectContent>
                        </Select>
                        <Num label="符号大小 pt" hideLabel value={s.marker_size} min={1} step={0.5} onChange={(v) => patchSeries(i, { marker_size: v })} />
                        <label className="flex items-center gap-1 text-callout"><Switch checked={s.marker_filled} onCheckedChange={(c) => patchSeries(i, { marker_filled: c })} aria-label={`${s.name} 实心符号`} />实心</label>
                      </div>
                    )}
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      {panel.y2 && (
                        <label className="flex items-center gap-1 text-callout"><Switch checked={s.y_axis === "y2"} onCheckedChange={(c) => patchSeries(i, { y_axis: c ? "y2" : "y" })} aria-label={`${s.name} 使用右轴`} />右轴</label>
                      )}
                      <label className={cn("flex items-center gap-1 text-callout", !hasErr(i) && "opacity-50")} title={hasErr(i) ? undefined : "该系列没有不确定度数据"}>
                        <Switch checked={s.error_bars} disabled={!hasErr(i)} onCheckedChange={(c) => patchSeries(i, { error_bars: c })} aria-label={`${s.name} 误差棒`} />误差棒
                      </label>
                      <span className="flex-1" />
                      <Button size="icon" variant="ghost" className="size-6" aria-label={`${s.name} 上移`} disabled={i === 0} onClick={() => moveSeries(i, i - 1)}><ArrowUp className="size-3.5" aria-hidden /></Button>
                      <Button size="icon" variant="ghost" className="size-6" aria-label={`${s.name} 下移`} disabled={i === panel.series.length - 1} onClick={() => moveSeries(i, i + 1)}><ArrowDown className="size-3.5" aria-hidden /></Button>
                      <Button size="icon" variant="ghost" className="size-6" aria-label={`移除 ${s.name}`} onClick={() => removeSeries(i)}><Trash2 className="size-3.5" aria-hidden /></Button>
                    </div>
                  </div>
                ))}
              </fieldset>
            </>
          )}
        </aside>
      </div>
    </>
  );
}

function Num({ label, value, onChange, min, step, hideLabel }: { label: string; value: number; onChange: (v: number) => void; min?: number; step?: number; hideLabel?: boolean }) {
  return (
    <label className="space-y-0.5 text-callout">
      {!hideLabel && <span className="block text-fg-2">{label}</span>}
      <Input aria-label={label} type="number" min={min} step={step} className="tnum h-7 text-right" value={value}
        onChange={(e) => { const v = Number(e.target.value); if (e.target.value !== "" && Number.isFinite(v) && (min === undefined || v >= min)) onChange(v); }} />
    </label>
  );
}

function axisTitle(a: Axis) {
  return a.unit ? `${a.label} (${a.unit})` : a.label;
}

/** Plot Studio → Origin: the current figure as editable Origin graphs (one per panel). */
function PlotOriginDialog({ spec, name, onClose }: { spec: PlotSpec; name: string; onClose: () => void }) {
  const status = useOriginStatus();
  const [formats, setFormats] = useState<Set<string>>(new Set(["png", "pdf"]));
  const [title, setTitle] = useState(name);
  const [jobId, setJobId] = useState<number | null>(null);
  const submit = useMutation({
    mutationFn: () => api.post<OriginJob>("/origin/plot-jobs", { spec, name: title, exports: [...formats] }),
    onSuccess: (j) => setJobId(j.id),
    onError: (e: Error) => toast.error(e.message),
  });
  const panels = spec.panels.filter((p) => p.series.some((s) => s.visible)).length;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>导出到 Origin</DialogTitle>
          <DialogDescription>
            在虚拟机中的 Origin 按当前图生成 {panels} 张图页（每个面板一张，论文图模板），曲线、颜色、线型、坐标轴与图例与预览一致；数据以完整分辨率写入工作簿并与图链接，可在 Origin 中继续编辑。保存 OPJU 后重新打开核验。
          </DialogDescription>
        </DialogHeader>
        {status.data && !status.data.reachable && <StatusLine severity="error">{status.data.error}</StatusLine>}
        {!jobId ? (
          <div className="space-y-3">
            <div className="space-y-1">
              <Label htmlFor="origin-name">文件名（英文、数字更稳妥）</Label>
              <Input id="origin-name" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="figure" className="h-7" />
            </div>
            <FormatPicker formats={formats} onChange={setFormats} />
          </div>
        ) : (
          <OriginJobProgress jobId={jobId} />
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{jobId ? "关闭" : "取消"}</Button>
          {!jobId && <Button disabled={formats.size === 0 || submit.isPending || !status.data?.reachable || panels === 0} onClick={() => submit.mutate()}>{submit.isPending ? "正在发送…" : "发送到 Origin"}</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
