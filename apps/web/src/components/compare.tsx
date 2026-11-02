/** Comparability verdicts (rules, SPEC §7.5) and AI literature benchmarking (SPEC §8.3). */
import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { toast } from "sonner";
import { api } from "@/lib/api";
import { PROPERTY_LABELS, fmt, show } from "@/lib/units";
import { cn } from "@/lib/utils";
import { StatusLine } from "@/components/common";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

export type Verdict = "direct" | "conditional" | "insufficient" | "not_recommended";
const VERDICT: Record<Verdict, [string, string]> = {
  direct: ["可直接比较", "text-success"],
  conditional: ["有条件比较", "text-fg-1"],
  insufficient: ["信息不足", "text-warning"],
  not_recommended: ["不建议直接比较", "text-danger"],
};

export function VerdictBadge({ v }: { v: Verdict }) {
  const [label, cls] = VERDICT[v];
  return <Badge variant="outline" className={cn("whitespace-nowrap", cls)}>{label}</Badge>;
}

const PERCENT = new Set(["elongation_at_break", "residual_strain"]);
export function propValue(quantity: string, unit: string, v: number | null, lo?: number | null, hi?: number | null): string {
  const one = (x: number) => (PERCENT.has(quantity) ? `${fmt(x * 100)} %` : show(x, unit));
  if (v !== null && v !== undefined) return one(v);
  return [lo != null ? `≥ ${one(lo)}` : "", hi != null ? `≤ ${one(hi)}` : ""].filter(Boolean).join("，") || "—";
}

type Row = { property_id: number; label: string; quantity: string; value: number | null; lower_bound: number | null; upper_bound: number | null; unit: string; verdict: Verdict; findings: { aspect: string; level: Verdict; message: string }[] };

/** Rule-based comparability of one stored value against every other value of the same kind. */
export function ComparabilityDialog({ refId, quantity, onClose }: { refId: number; quantity: string; onClose: () => void }) {
  const related = quantity === "ultimate_stretch" || quantity === "elongation_at_break" ? ["ultimate_stretch", "elongation_at_break"] : [quantity];
  const props = useQuery({
    queryKey: ["properties", related.join(",")],
    queryFn: async () => (await Promise.all(related.map((q) => api.get<{ id: number }[]>(`/properties?quantity=${q}`)))).flat(),
  });
  const ids = (props.data ?? []).map((p) => p.id).filter((i) => i !== refId);
  const cmp = useQuery({
    queryKey: ["comparability", refId, ids.join(",")],
    queryFn: () => api.post<{ reference: { label: string; quantity: string; value: number | null; unit: string }; rows: Row[] }>("/comparability", { reference_id: refId, property_ids: ids }),
    enabled: ids.length > 0,
  });
  const order: Verdict[] = ["direct", "conditional", "insufficient", "not_recommended"];
  const rows = [...(cmp.data?.rows ?? [])].sort((a, b) => order.indexOf(a.verdict) - order.indexOf(b.verdict));
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>可比性检查：{PROPERTY_LABELS[quantity] ?? quantity}</DialogTitle>
          <DialogDescription>
            {cmp.data ? `参照：${cmp.data.reference.label}，${propValue(quantity, cmp.data.reference.unit, cmp.data.reference.value)}。` : ""}
            单位相同不代表可以直接比较；逐项检查实验类型、几何、加载模式、应力定义、温度、频率、速率、预循环、计算与判定方法。
          </DialogDescription>
        </DialogHeader>
        {ids.length === 0 && props.isSuccess && <p className="text-fg-2">数据库中没有其他同类指标的数值。</p>}
        {cmp.isError && <StatusLine severity="error">{(cmp.error as Error).message}</StatusLine>}
        <div className="max-h-[60vh] overflow-auto">
          <table className="w-full text-body">
            <thead><tr className="border-b text-left text-fg-2">{["对象", "数值", "结论", "检查项"].map((h) => <th key={h} className="py-1 pr-3 font-medium">{h}</th>)}</tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.property_id} className="border-b align-top">
                  <td className="py-1 pr-3">{r.label}{r.quantity !== quantity && <span className="text-fg-2">（{PROPERTY_LABELS[r.quantity]}）</span>}</td>
                  <td className="tnum whitespace-nowrap py-1 pr-3">{propValue(r.quantity, r.unit, r.value, r.lower_bound, r.upper_bound)}</td>
                  <td className="py-1 pr-3"><VerdictBadge v={r.verdict} /></td>
                  <td className="py-1 pr-3 text-callout">
                    <ul className="space-y-0.5">{r.findings.map((f, i) => <li key={i} className={f.level === "direct" ? "text-fg-2" : VERDICT[f.level][1]}>{f.aspect}：{f.message}</li>)}</ul>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <DialogFooter><Button onClick={onClose}>完成</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

type Candidate = {
  record_id: number; quantity: string; material: string; value_si: number | null; lower_bound_si: number | null; upper_bound_si: number | null; unit_si: string; reported_text: string;
  source: { title: string; authors: string; year: number | null; page: string; figure: string; table: string; extraction_method: string };
  best_verdict: Verdict; comparisons: { own_definition: string; verdict: Verdict; findings: string[] }[];
};
type Rec = { material: string; key_metrics: string[]; reason: string; condition_differences: string[]; comparability_note: string; records: Candidate[]; rejected: boolean; problems: string[]; contains_values: boolean };
type BenchOut = {
  candidates: Candidate[]; note: string; payload?: unknown; fallback?: boolean; error?: string; message?: string;
  provider?: string; model?: string; elapsed_s?: number; recommendations?: Rec[]; limitations?: string[]; summary?: string; disclaimer?: string;
};

const cite = (c: Candidate) => `${c.source.authors} ${c.source.year ?? ""} p.${c.source.page}${c.source.figure ? `，${c.source.figure}` : ""}${c.source.table ? `，${c.source.table}` : ""}`;

/** Literature benchmarking for one analysis run: rule candidates always, AI only after preview. */
export function BenchmarkDialog({ runId, onClose }: { runId: number; onClose: () => void }) {
  const [withValues, setWithValues] = useState(false);
  const [showPayload, setShowPayload] = useState(false);
  const preview = useQuery({ queryKey: ["benchmark-preview", runId, withValues], queryFn: () => api.post<BenchOut>("/ai/benchmark", { run_id: runId, include_values: withValues, dry_run: true }) });
  const ai = useMutation({ mutationFn: () => api.post<BenchOut>("/ai/benchmark", { run_id: runId, include_values: withValues }), onError: (e: Error) => toast.error(e.message) });
  const cands = preview.data?.candidates ?? [];
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-5xl">
        <DialogHeader>
          <DialogTitle>文献对标</DialogTitle>
          <DialogDescription>候选记录由数据库按同类指标检索，可比性由规则判断；AI 只能在这些记录中推荐并解释，所有数值与来源均来自数据库。</DialogDescription>
        </DialogHeader>
        <div className="max-h-[65vh] space-y-3 overflow-auto">
          {preview.isError && <StatusLine severity="error">{(preview.error as Error).message}</StatusLine>}
          {preview.isSuccess && cands.length === 0 && <p className="text-fg-2">文献库中没有与该结果同类指标的记录。可在“材料数据库”页导入文献记录。</p>}
          {cands.length > 0 && (
            <table className="w-full text-body">
              <caption className="pb-1 text-left font-medium">规则检索结果（{cands.length} 条）</caption>
              <thead><tr className="border-b text-left text-fg-2">{["指标", "文献材料", "数值", "来源", "可比性（与本实验同类结果）"].map((h) => <th key={h} className="py-1 pr-3 font-medium">{h}</th>)}</tr></thead>
              <tbody>
                {cands.map((c) => (
                  <tr key={c.record_id} className="border-b align-top">
                    <td className="py-1 pr-3">{PROPERTY_LABELS[c.quantity] ?? c.quantity}</td>
                    <td className="py-1 pr-3">{c.material}</td>
                    <td className="tnum whitespace-nowrap py-1 pr-3">{propValue(c.quantity, c.unit_si, c.value_si, c.lower_bound_si, c.upper_bound_si)}</td>
                    <td className="py-1 pr-3 text-callout">{cite(c)}<div className="text-fg-2">原文：{c.reported_text}</div></td>
                    <td className="py-1 pr-3 text-callout">
                      {c.comparisons.map((x, i) => (
                        <details key={i} className="mb-0.5">
                          <summary className="cursor-pointer"><VerdictBadge v={x.verdict} />{x.own_definition && <span className="ml-1 text-fg-2">本实验 {x.own_definition}</span>}</summary>
                          <ul className="ml-4 list-disc text-fg-2">{x.findings.map((f, j) => <li key={j}>{f}</li>)}</ul>
                        </details>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {cands.length > 0 && (
            <section className="space-y-2 rounded-md border p-3" aria-label="AI 文献对标">
              <h3 className="font-medium">AI 推荐与说明（可选）</h3>
              <p className="text-callout text-fg-2">{preview.data?.note}。CLI Provider 同样会把内容发送到云端模型。</p>
              <label className="flex items-center gap-2">
                <Checkbox checked={withValues} onCheckedChange={(v) => setWithValues(v === true)} />同时发送本实验的性能数值（未公开数据，默认不发送）
              </label>
              <div className="flex gap-2">
                <Button size="sm" variant="ghost" onClick={() => setShowPayload((v) => !v)}>{showPayload ? "隐藏发送内容" : "预览发送内容"}</Button>
                <Button size="sm" disabled={ai.isPending || !preview.isSuccess} onClick={() => ai.mutate()}>{ai.isPending ? "AI 正在分析…" : "确认发送并请求 AI 对标"}</Button>
              </div>
              {showPayload && <pre className="max-h-60 overflow-auto rounded bg-inspector p-2 text-[11px] leading-tight">{JSON.stringify(preview.data?.payload, null, 1)}</pre>}
              {ai.data && <AIResult out={ai.data} />}
            </section>
          )}
        </div>
        <DialogFooter><Button onClick={onClose}>完成</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function AIResult({ out }: { out: BenchOut }) {
  if (out.fallback) return <StatusLine severity="warning">{out.message}{out.error ? `（${out.error}）` : ""}</StatusLine>;
  return (
    <div className="space-y-2" role="status" aria-live="polite">
      <p className="text-callout text-fg-2">{out.provider} · {out.model} · {out.elapsed_s} s。{out.disclaimer}</p>
      {out.summary && <p>{out.summary}</p>}
      {out.recommendations?.map((r, i) => (
        <div key={i} className={cn("rounded-md border p-2", r.rejected && "opacity-60")}>
          <div className="flex items-center gap-2 font-medium">
            {r.material}
            {r.rejected && <Badge variant="outline" className="text-danger">已拒绝：{r.problems.join("；")}</Badge>}
            {r.contains_values && <Badge variant="outline" className="text-warning">文字中含 AI 写出的带单位数值，以表格为准</Badge>}
          </div>
          <p className="mt-1">{r.reason}</p>
          {r.condition_differences.length > 0 && <ul className="ml-4 list-disc text-callout">{r.condition_differences.map((d, j) => <li key={j}>{d}</li>)}</ul>}
          <p className="mt-1 text-callout text-fg-2">可比性说明：{r.comparability_note}</p>
          <ul className="mt-1 text-callout">
            {r.records.map((c) => <li key={c.record_id}>{PROPERTY_LABELS[c.quantity]}：{propValue(c.quantity, c.unit_si, c.value_si, c.lower_bound_si, c.upper_bound_si)}（{cite(c)}，规则：<VerdictBadge v={c.best_verdict} />）</li>)}
          </ul>
        </div>
      ))}
      {out.limitations && out.limitations.length > 0 && (
        <div><p className="font-medium">局限</p><ul className="ml-4 list-disc text-callout">{out.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul></div>
      )}
    </div>
  );
}
