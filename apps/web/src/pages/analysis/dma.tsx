/** DMA results: E′/E″/tan δ curves per frequency, Tg candidates by definition, multi-sample comparison. */
import { useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Chart, PALETTE, type Series } from "@/components/Chart";
import { KeyValue, Panel, StatusLine } from "@/components/common";
import { api, type Run } from "@/lib/api";
import { fmt, show } from "@/lib/units";
import { Checkbox } from "@/components/ui/checkbox";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

type Tg = { definition: string; temperature_k: number; frequency_hz: number | null; value: number | null; ambiguous: boolean; other_peaks_k: number[] };
type DSeries = { frequency_hz: number | null; n_points: number; tg: Tg[]; reference_values: { temperature_k: number; frequency_hz: number | null; storage_modulus_pa: number; loss_modulus_pa: number | null; loss_factor: number | null }[] };

export const TG_LABEL: Record<string, string> = {
  tan_delta_peak: "tan δ 峰",
  loss_modulus_peak: "损耗模量峰",
  storage_modulus_onset: "储能模量下降起始",
};
const SOURCE: Record<string, string> = { measured: "测得", "loss / storage": "由 E″/E′ 计算", "tan_delta × storage": "由 tan δ·E′ 计算", absent: "无" };
const SPIKE = PALETTE[5];

const celsius = (k: number | null | undefined) => (k === null || k === undefined ? null : k - 273.15);
const freqName = (f: number | null) => (f === null ? "" : `${fmt(f)} Hz`);

/** Split per-point curves into one line per frequency series (rows are stored sorted by series, then x). */
function bySeries(run: Run, xKey: string, yKey: string, xf: (v: number) => number, yf: (v: number) => number, label: string): Series[] {
  const c = run.curves;
  const sidx = c.series_index ?? [];
  const series = run.result.series as DSeries[];
  return series.map((s, i) => {
    const xs: (number | null)[] = [];
    const ys: (number | null)[] = [];
    sidx.forEach((v, j) => {
      const x = c[xKey]?.[j];
      const y = c[yKey]?.[j];
      if (v === i && x !== null && x !== undefined && y !== null && y !== undefined) {
        xs.push(xf(x));
        ys.push(yf(y));
      }
    });
    return { name: series.length > 1 ? `${label} · ${freqName(s.frequency_hz)}` : label, x: xs, y: ys, color: PALETTE[i % PALETTE.length] };
  });
}

function spikes(run: Run, xKey: string, yKey: string, flagKey: string, xf: (v: number) => number, yf: (v: number) => number): Series[] {
  const c = run.curves;
  const xs: number[] = [];
  const ys: number[] = [];
  (c[flagKey] ?? []).forEach((f, j) => {
    const x = c[xKey]?.[j];
    const y = c[yKey]?.[j];
    if (f === 1 && x != null && y != null) {
      xs.push(xf(x));
      ys.push(yf(y));
    }
  });
  return xs.length ? [{ name: "异常点（不参与 Tg）", x: xs, y: ys, mode: "markers", marker: "circle-open", color: SPIKE }] : [];
}

function tgLines(run: Run, definition: string) {
  return (run.result.series as DSeries[]).flatMap((s) =>
    s.tg
      .filter((t) => t.definition === definition)
      .map((t) => ({ x: t.temperature_k - 273.15, label: `${TG_LABEL[definition]}${t.frequency_hz ? `（${fmt(t.frequency_hz)} Hz）` : ""} ${fmt(t.temperature_k - 273.15, 4)} °C${t.ambiguous ? "，多峰未选定" : ""}` })),
  );
}

export function DMAView({ run }: { run: Run }) {
  const r = run.result;
  const series = r.series as DSeries[];
  const shear = r.deformation_mode === "shear";
  const [e1, e2] = shear ? ["G′", "G″"] : ["E′", "E″"];
  const T = (v: number) => v - 273.15;
  const MPa = (v: number) => v * 1e-6;
  const one = (v: number) => v;
  const freqSweep = r.mode === "frequency_sweep";
  const xKey = freqSweep ? "frequency_hz" : "temperature_k";
  const xf = freqSweep ? one : T;
  const xTitle = freqSweep ? "频率 f (Hz)" : "温度 T (°C)";
  const hasLoss = r.loss_modulus_source !== "absent";

  return (
    <div className="space-y-3">
      <Panel>
        <Tabs defaultValue="storage">
          <TabsList>
            <TabsTrigger value="storage">储能模量 {e1}</TabsTrigger>
            {hasLoss && <TabsTrigger value="loss">损耗模量 {e2}</TabsTrigger>}
            {hasLoss && <TabsTrigger value="tan">tan δ</TabsTrigger>}
          </TabsList>
          <TabsContent value="storage">
            <Chart ariaLabel={`储能模量–${freqSweep ? "频率" : "温度"}曲线`} logY logX={freqSweep} xTitle={xTitle} yTitle={`储能模量 ${e1} (MPa)`}
              series={[...bySeries(run, xKey, "storage_modulus_pa", xf, MPa, e1), ...spikes(run, xKey, "storage_modulus_pa", "spike_storage", xf, MPa)]}
              vlines={freqSweep ? [] : tgLines(run, "storage_modulus_onset")} />
          </TabsContent>
          {hasLoss && (
            <TabsContent value="loss">
              <Chart ariaLabel={`损耗模量–${freqSweep ? "频率" : "温度"}曲线`} logY logX={freqSweep} xTitle={xTitle} yTitle={`损耗模量 ${e2} (MPa)`}
                series={[...bySeries(run, xKey, "loss_modulus_pa", xf, MPa, e2), ...spikes(run, xKey, "loss_modulus_pa", "spike_loss", xf, MPa)]}
                vlines={freqSweep ? [] : tgLines(run, "loss_modulus_peak")} />
            </TabsContent>
          )}
          {hasLoss && (
            <TabsContent value="tan">
              <Chart ariaLabel={`tan δ–${freqSweep ? "频率" : "温度"}曲线`} logX={freqSweep} xTitle={xTitle} yTitle="损耗因子 tan δ"
                series={[...bySeries(run, xKey, "loss_factor", xf, one, "tan δ"), ...spikes(run, xKey, "loss_factor", "spike_tan_delta", xf, one)]}
                vlines={freqSweep ? [] : tgLines(run, "tan_delta_peak")} />
            </TabsContent>
          )}
        </Tabs>
      </Panel>
      <div className="grid gap-3 lg:grid-cols-2">
        <Panel title="Tg 候选（按定义分别列出）">
          {freqSweep ? (
            <p className="text-fg-2">等温频率扫描不报告 Tg。</p>
          ) : (
            <table className="w-full text-body">
              <thead><tr className="border-b text-left text-fg-2">{["定义", "频率", "Tg", "峰值", "状态"].map((h) => <th key={h} className="py-1 pr-3 font-medium">{h}</th>)}</tr></thead>
              <tbody className="tnum">
                {series.flatMap((s) => s.tg).map((t, i) => (
                  <tr key={i} className="border-b">
                    <td className="py-1 pr-3">{TG_LABEL[t.definition]}</td>
                    <td className="py-1 pr-3">{t.frequency_hz === null ? "—" : `${fmt(t.frequency_hz)} Hz`}</td>
                    <td className="py-1 pr-3">{show(t.temperature_k, "K")}</td>
                    <td className="py-1 pr-3">{t.value === null ? "—" : t.definition === "loss_modulus_peak" ? show(t.value, "Pa") : fmt(t.value)}</td>
                    <td className="py-1 pr-3">
                      {t.ambiguous ? <span className="text-warning">多峰，未选定（其他峰 {t.other_peaks_k.map((k) => `${fmt(celsius(k), 4)} °C`).join("、")}）</span>
                        : t.definition === "storage_modulus_onset" ? "—"
                        : t.other_peaks_k.length ? `另有次峰 ${t.other_peaks_k.map((k) => `${fmt(celsius(k), 4)} °C`).join("、")}` : "单峰"}
                    </td>
                  </tr>
                ))}
                {series.every((s) => s.tg.length === 0) && <tr><td colSpan={5} className="py-1 text-fg-2">未识别到 Tg 候选（见下方说明）</td></tr>}
              </tbody>
            </table>
          )}
          <p className="mt-2 text-subhead text-fg-2">不同定义的 Tg 存在系统差异，不能直接比较；陈 p.70 采用 1 Hz 下 tan δ 峰温度。</p>
        </Panel>
        <Panel title="数据与参考温度">
          <KeyValue items={[
            ["模式", `${freqSweep ? "等温频率扫描" : "温度扫描"} · ${shear ? "剪切（G′/G″）" : r.deformation_mode === "tension" ? "拉伸（E′/E″）" : "形变模式未知"}`],
            ["tan δ 来源", SOURCE[r.loss_factor_source] ?? r.loss_factor_source],
            [`${e2} 来源`, SOURCE[r.loss_modulus_source] ?? r.loss_modulus_source],
            ["tan δ 与 E″/E′ 一致性", r.consistency_deviation === null ? "—" : `中位相对偏差 ${fmt(r.consistency_deviation * 100, 3)} %`],
            ["异常点", r.spikes.length ? `${r.spikes.length} 个（图中空心标记）` : "无"],
            ...series.flatMap((s) => s.reference_values.map((v): [string, string] => [
              `${show(v.temperature_k, "K")}${v.frequency_hz ? ` · ${fmt(v.frequency_hz)} Hz` : ""}`,
              `${e1} ${show(v.storage_modulus_pa, "Pa")} · ${e2} ${show(v.loss_modulus_pa, "Pa")} · tan δ ${fmt(v.loss_factor)}`,
            ])),
          ]} />
        </Panel>
      </div>
      {!freqSweep && <DMACompare run={run} />}
    </div>
  );
}

type CompareOut = {
  groups: { definition: string; definition_label: string; frequency_hz: number | null; deformation_mode: string; rows: { run_id: number; label: string; temperature_k: number; ambiguous: boolean }[]; summary: { n: number; mean: number; std: number } | null }[];
  notes: string[];
};

/** Overlay other DMA runs and tabulate Tg grouped by (definition, frequency, mode) — never pooled across groups. */
function DMACompare({ run }: { run: Run }) {
  const all = useQuery({ queryKey: ["analyses", "dma"], queryFn: () => api.get<{ id: number; version: number; specimen: string; material: number }[]>("/analyses?method=dma&limit=200") });
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const ids = [run.id, ...[...picked].filter((i) => i !== run.id)];
  const others = useQueries({ queries: [...picked].map((id) => ({ queryKey: ["run", id], queryFn: () => api.get<Run>(`/analyses/${id}`) })) });
  const cmp = useQuery({ queryKey: ["dma-compare", ids.join(",")], queryFn: () => api.post<CompareOut>("/dma/compare", { run_ids: ids }), enabled: ids.length > 1 });
  const candidates = (all.data ?? []).filter((a) => a.id !== run.id);
  const runs = [run, ...others.map((q) => q.data).filter((x): x is Run => !!x)];
  const overlay: Series[] = runs.flatMap((rr, i) =>
    bySeries(rr, "temperature_k", "loss_factor", (v) => v - 273.15, (v) => v, `#${rr.id}`).map((s) => ({ ...s, color: PALETTE[i % PALETTE.length] })),
  );
  return (
    <Panel title="多样品比较">
      {candidates.length === 0 ? (
        <p className="text-fg-2">还没有其他 DMA 分析结果。</p>
      ) : (
        <div className="space-y-3">
          <fieldset className="relative flex flex-wrap gap-x-4 gap-y-1">
            <legend className="sr-only">选择要比较的 DMA 结果</legend>
            {candidates.map((a) => (
              <label key={a.id} className="flex items-center gap-1.5">
                <Checkbox checked={picked.has(a.id)} onCheckedChange={(c) => { const s = new Set(picked); if (c === true) s.add(a.id); else s.delete(a.id); setPicked(s); }} />
                {a.specimen}（#{a.id} v{a.version}）
              </label>
            ))}
          </fieldset>
          {picked.size > 0 && (
            <>
              <Chart ariaLabel="多样品 tan δ–温度曲线叠加" height={300} xTitle="温度 T (°C)" yTitle="损耗因子 tan δ" series={overlay} />
              {cmp.isError && <StatusLine severity="error">{(cmp.error as Error).message}</StatusLine>}
              {cmp.data?.notes.map((n) => <StatusLine key={n} severity="info">{n}</StatusLine>)}
              {cmp.data?.groups.map((g) => (
                <table key={`${g.definition}-${g.frequency_hz}-${g.deformation_mode}`} className="w-full text-body">
                  <caption className="text-left font-medium">
                    {g.definition_label}{g.frequency_hz ? ` · ${fmt(g.frequency_hz)} Hz` : " · 频率未记录"} · {g.deformation_mode === "shear" ? "剪切" : g.deformation_mode === "tension" ? "拉伸" : "模式未知"}
                    {g.summary && g.summary.n > 1 && <span className="font-normal text-fg-2">　均值 {fmt(g.summary.mean - 273.15, 4)} °C，标准差 {fmt(g.summary.std, 3)} K（n = {g.summary.n}）</span>}
                  </caption>
                  <tbody className="tnum">
                    {g.rows.map((x) => (
                      <tr key={x.run_id} className="border-b">
                        <td className="py-0.5 pr-3">{x.label}</td>
                        <td className="py-0.5 pr-3">{show(x.temperature_k, "K")}</td>
                        <td className="py-0.5 text-warning">{x.ambiguous ? "多峰，不计入统计" : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ))}
            </>
          )}
        </div>
      )}
    </Panel>
  );
}
