import { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { BookOpen, Download, GitCompare, LineChart, Play, Send, Trash2 } from "lucide-react";
import { api, type ExperimentDetail, type ExperimentSummary, type Run, type Vocabulary } from "@/lib/api";
import { METHOD_LABELS, mm } from "@/lib/units";
import { cn } from "@/lib/utils";
import { hasPrimaryKey, shortcut } from "@/lib/platform";
import { Toolbar } from "@/components/shell/AppShell";
import { EmptyState, FlagList, KeyValue, Panel, StatusLine } from "@/components/common";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { FormatPicker, OriginJobProgress, useOriginStatus, type OriginJob } from "@/components/origin";
import { ConfirmDelete } from "@/components/confirm";
import { DMAView } from "./analysis/dma";
import { BenchmarkDialog } from "@/components/compare";
import { ALGORITHMS, CorrectionsPanel, describe as describeCorrection } from "./analysis/corrections";
import { CrackGrowthView, CyclicView, FatigueSteadyView, PureShearView, ThresholdView, UniaxialView } from "./analysis/views";
import { CrackGrowthParams, CyclicParams, DMAParams, FatigueSteadyParams, PureShearParams, ThresholdParams, UniaxialParams, type Body } from "./analysis/params";

/** Analyses available for each test type (first = default). */
const METHODS: Record<string, string[]> = {
  uniaxial: ["uniaxial"],
  cyclic: ["cyclic"],
  pure_shear_notched: ["pure_shear"],
  pure_shear_unnotched: [],
  fatigue_unnotched_cyclic: ["fatigue_steady"],
  fatigue_crack_growth: ["crack_growth", "fatigue_threshold"],
  dma: ["dma"],
  peel_t: [],
  peel_trouser: [],
};

const TEMPLATE_FOR: Record<string, string> = {
  uniaxial: "nominal_stress_stretch",
  cyclic: "cyclic_hysteresis",
  pure_shear: "nominal_stress_stretch",
  fatigue_steady: "nominal_stress_stretch",
  crack_growth: "crack_growth_vs_cycles",
  fatigue_threshold: "fatigue_dcdn_g",
  dma: "dma_storage_tan_delta",
};

function endpoint(method: string, expId: number): string {
  if (method === "pure_shear") return `/experiments/${expId}/pure-shear`;
  if (method === "crack_growth") return `/experiments/${expId}/crack-growth`;
  if (method === "fatigue_threshold") return "/fatigue/threshold";
  return `/experiments/${expId}/analyses/${method}`;
}

// last opened experiment / method / version, so “分析” reopens where the user left off
const LAST_KEY = "polymech.analysis.last";
type Last = { expId: number; method: string; runId: number | null };
function readLast(): Last | null {
  try {
    const v = JSON.parse(localStorage.getItem(LAST_KEY) ?? "null");
    return v && typeof v.expId === "number" ? v : null;
  } catch {
    return null;
  }
}
function writeLast(v: Last) {
  try {
    localStorage.setItem(LAST_KEY, JSON.stringify(v));
  } catch {
    /* storage unavailable: nothing to remember */
  }
}

export default function Analysis() {
  const { experimentId } = useParams();
  const [search] = useSearchParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const expId = experimentId ? Number(experimentId) : null;
  const list = useQuery({ queryKey: ["experiments"], queryFn: () => api.get<ExperimentSummary[]>("/experiments") });
  const vocab = useQuery({ queryKey: ["vocabulary"], queryFn: () => api.get<Vocabulary>("/vocabulary") });
  const exp = useQuery({ queryKey: ["experiment", expId], queryFn: () => api.get<ExperimentDetail>(`/experiments/${expId}`), enabled: expId !== null });
  const methods = exp.data ? (METHODS[exp.data.test_type] ?? []) : [];
  const [method, setMethod] = useState<string>("");
  const [runId, setRunId] = useState<number | null>(null);
  const [body, setBody] = useState<Body>({});
  const [compareOpen, setCompareOpen] = useState(false);
  const [originOpen, setOriginOpen] = useState(false);
  const [benchOpen, setBenchOpen] = useState(false);
  const [toDelete, setToDelete] = useState<{ kind: "run"; id: number; version: number } | { kind: "experiment" } | null>(null);
  const del = useMutation({
    mutationFn: () => (toDelete?.kind === "run" ? api.delete(`/analyses/${toDelete.id}`) : api.delete(`/experiments/${expId}`)),
    onSuccess: async () => {
      const t = toDelete;
      setToDelete(null);
      if (t?.kind === "run") {
        toast.success(`已删除 v${t.version}`);
        if (t.id === runId) setRunId([...(exp.data?.runs ?? [])].reverse().find((r) => r.method === method && r.id !== t.id)?.id ?? null);
        await qc.invalidateQueries();
      } else {
        toast.success(`已删除实验 #${expId}`);
        await qc.invalidateQueries();
        navigate("/analysis");
      }
    },
    onError: (e: Error) => { toast.error(e.message); setToDelete(null); },
  });

  // /analysis without an id: reopen the last experiment if it still exists
  useEffect(() => {
    if (expId !== null || !list.data) return;
    const last = readLast();
    if (last && list.data.some((e) => e.id === last.expId)) navigate(`/analysis/${last.expId}`, { replace: true });
  }, [expId, list.data]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!exp.data) return;
    const ms = METHODS[exp.data.test_type] ?? [];
    // ?run=<id> (from the materials database) opens that version; otherwise the last one used
    const linked = exp.data.runs.find((r) => r.id === Number(search.get("run")));
    const saved = linked ? { expId: exp.data.id, method: linked.method, runId: linked.id } : readLast();
    const restore = saved?.expId === exp.data.id && ms.includes(saved.method) ? saved : null;
    const m = restore?.method ?? ms[0] ?? "";
    setMethod(m);
    const kept = restore?.runId != null && exp.data.runs.some((r) => r.id === restore.runId && r.method === m);
    const last = [...exp.data.runs].reverse().find((r) => r.method === m);
    setRunId(kept ? restore!.runId : (last?.id ?? null));
  }, [exp.data?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (expId !== null && method && exp.data?.id === expId) writeLast({ expId, method, runId });
  }, [expId, method, runId, exp.data?.id]);

  const run = useQuery({ queryKey: ["run", runId], queryFn: () => api.get<Run>(`/analyses/${runId}`), enabled: runId !== null });
  const parametersReady = runId === null || (run.data?.id === runId && run.data.experiment_id === expId && run.data.method === method);

  const exec = useMutation({
    mutationFn: () => {
      const operator = "";
      if (["uniaxial", "cyclic", "fatigue_steady", "dma"].includes(method)) return api.post<Run>(endpoint(method, expId!), { params: body, operator });
      return api.post<Run>(endpoint(method, expId!), { ...body, operator });
    },
    onSuccess: (r) => {
      setRunId(r.id);
      qc.setQueryData(["run", r.id], r);
      qc.invalidateQueries({ queryKey: ["experiment", expId] });
      qc.invalidateQueries({ queryKey: ["experiments"] });
      toast.success(`${METHOD_LABELS[r.method]} v${r.version} 已保存${r.status === "provisional" ? "（临时结果）" : ""}`);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (hasPrimaryKey(e) && e.key.toLowerCase() === "r" && !e.shiftKey) {
        e.preventDefault();
        if (expId && method && parametersReady && exp.data?.id === expId && !exec.isPending) exec.mutate();
      }
    };
    // Native menu shortcuts arrive as events instead of keydown.
    const onMenu = (e: Event) => {
      if ((e as CustomEvent<string>).detail === "recalculate" && expId && method && parametersReady && exp.data?.id === expId && !exec.isPending) exec.mutate();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("polymech:menu", onMenu);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("polymech:menu", onMenu);
    };
  }, [expId, method, parametersReady, exp.data?.id, exec]);

  const label = (t: string) => vocab.data?.test_types.find((x) => x.id === t)?.label ?? t;
  const runs = (exp.data?.runs ?? []).filter((r) => r.method === method).reverse();

  return (
    <>
      <Toolbar title="分析" subtitle={exp.data ? `${exp.data.material.name} · ${exp.data.specimen.label} · ${label(exp.data.test_type)}` : undefined}>
        {run.data && (
          <>
            <Button size="sm" variant="ghost" asChild>
              <a href={`/api/analyses/${run.data.id}/curves.csv`} download>
                <Download className="size-4" aria-hidden />CSV
              </a>
            </Button>
            <Button size="sm" variant="ghost" onClick={() => navigate(`/plots?run=${run.data!.id}&template=${TEMPLATE_FOR[run.data!.method] ?? ""}`)}>
              <LineChart className="size-4" aria-hidden />绘图工作室
            </Button>
            <Button size="sm" variant="outline" onClick={() => setOriginOpen(true)}>
              <Send className="size-4" aria-hidden />导出到 Origin…
            </Button>
            <Button size="sm" variant="ghost" disabled={run.data.properties.length === 0} onClick={() => setBenchOpen(true)} title="与文献数据库中的同类指标比较">
              <BookOpen className="size-4" aria-hidden />文献对标…
            </Button>
            <Button size="sm" variant="ghost" disabled={runs.length < 2} onClick={() => setCompareOpen(true)}>
              <GitCompare className="size-4" aria-hidden />比较版本…
            </Button>
          </>
        )}
        <Button size="sm" disabled={!expId || !method || !parametersReady || exp.data?.id !== expId || exec.isPending} onClick={() => exec.mutate()} title={`重新计算（${shortcut("R")}）`}>
          <Play className="size-4" aria-hidden />
          {exec.isPending ? "正在计算…" : runs.length ? "按当前参数新建版本" : "计算"}
        </Button>
      </Toolbar>
      <div className="flex min-h-0 flex-1">
        <nav aria-label="实验与分析版本" className="w-60 shrink-0 overflow-auto border-r bg-inspector p-2">
          <Select value={expId ? String(expId) : ""} onValueChange={(v) => navigate(`/analysis/${v}`)}>
            <SelectTrigger aria-label="选择实验" className="mb-2 h-7 w-full"><SelectValue placeholder="选择实验" /></SelectTrigger>
            <SelectContent>
              {list.data?.map((e) => <SelectItem key={e.id} value={String(e.id)}>#{e.id} {e.material.name} · {e.specimen.label}</SelectItem>)}
            </SelectContent>
          </Select>
          {methods.length > 1 && (
            <div className="mb-2 flex gap-1" role="radiogroup" aria-label="分析方法">
              {methods.map((m) => (
                <Button key={m} size="sm" variant={m === method ? "secondary" : "ghost"} role="radio" aria-checked={m === method}
                  onClick={() => { setMethod(m); setRunId([...(exp.data?.runs ?? [])].reverse().find((r) => r.method === m)?.id ?? null); }}>
                  {METHOD_LABELS[m]}
                </Button>
              ))}
            </div>
          )}
          <p className="px-1 pb-1 text-subhead font-medium text-fg-2">分析版本（新版本不覆盖旧结果）</p>
          <ul className="space-y-0.5">
            {runs.map((r) => (
              <li key={r.id} className="group flex items-center gap-0.5">
                <button type="button" onClick={() => setRunId(r.id)} aria-current={r.id === runId}
                  className={cn("flex min-w-0 flex-1 items-center justify-between rounded-md px-2 py-1 text-left hover:bg-hover", r.id === runId && "bg-hover font-medium")}>
                  <span>v{r.version} · {new Date(r.created_at).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>
                  {r.status !== "ok" && <Badge variant="outline" className="text-warning">临时</Badge>}
                </button>
                <Button size="icon" variant="ghost" className="size-6 shrink-0 text-fg-2 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 hover:text-danger"
                  aria-label={`删除分析版本 v${r.version}`} title="删除此版本…" onClick={() => setToDelete({ kind: "run", id: r.id, version: r.version })}>
                  <Trash2 className="size-3.5" aria-hidden />
                </Button>
              </li>
            ))}
            {runs.length === 0 && exp.data && <li className="px-2 text-fg-2">尚未分析</li>}
          </ul>
          {exp.data && (
            <Button size="sm" variant="ghost" className="mt-3 w-full justify-start text-fg-2 hover:text-danger" onClick={() => setToDelete({ kind: "experiment" })}>
              <Trash2 className="size-4" aria-hidden />删除实验…
            </Button>
          )}
        </nav>

        <main className="min-w-0 flex-1 space-y-3 overflow-auto p-3">
          {!expId && <EmptyState title="选择一个实验开始分析">或从“实验”页双击一行。</EmptyState>}
          {exp.data && methods.length === 0 && (
            <EmptyState title={`${label(exp.data.test_type)}在本页没有独立分析`}>
              {exp.data.test_type === "pure_shear_unnotched" ? "无裂纹纯剪切样品作为 W(λ) 来源，请打开对应的有裂纹样品实验计算断裂韧性。" : "剥离分析暂未实现（按用户决定推迟）。"}
            </EmptyState>
          )}
          {exp.data && exp.data.missing_metadata.length > 0 && (
            <StatusLine severity="warning">缺少元数据：{exp.data.missing_metadata.map((m) => m.label).join("、")}。需要这些尺寸的计算会被拒绝，不会使用默认值。</StatusLine>
          )}
          {run.isError && <StatusLine severity="error">{(run.error as Error).message}</StatusLine>}
          {run.data && (
            <>
              {run.data.status === "provisional" && <StatusLine severity="warning">这是临时结果（见下方警告），不会进入材料性能统计。</StatusLine>}
              {run.data.method === "uniaxial" && <UniaxialView run={run.data} />}
              {run.data.method === "cyclic" && <CyclicView run={run.data} />}
              {run.data.method === "pure_shear" && <PureShearView run={run.data} />}
              {run.data.method === "fatigue_steady" && <FatigueSteadyView run={run.data} />}
              {run.data.method === "crack_growth" && <CrackGrowthView run={run.data} />}
              {run.data.method === "fatigue_threshold" && <ThresholdView run={run.data} />}
              {run.data.method === "dma" && <DMAView run={run.data} />}
              <div className="grid gap-3 lg:grid-cols-2">
                <Panel title="质量与适用性"><FlagList flags={run.data.flags} /></Panel>
                <Panel title="溯源">
                  <KeyValue items={[
                    ["版本", `v${run.data.version}${run.data.parent_run_id ? `（由 #${run.data.parent_run_id} 重新计算）` : ""}`],
                    ["软件版本", run.data.software_version],
                    ["输入哈希", <code className="text-subhead">{run.data.input_sha256.slice(0, 16)}…</code>],
                    ["结果哈希", <code className="text-subhead">{run.data.result_sha256.slice(0, 16)}…</code>],
                    ["原始文件 SHA-256", <code className="text-subhead">{String(run.data.inputs.raw_file_sha256 ?? "—").slice(0, 16)}…</code>],
                    ["数据修正", correctionsText(run.data.inputs.corrections)],
                    ["计算时间", new Date(run.data.created_at).toLocaleString("zh-CN")],
                  ]} />
                </Panel>
              </div>
            </>
          )}
        </main>

        <aside aria-label="分析参数" className="w-72 shrink-0 space-y-4 overflow-auto border-l bg-inspector p-3">
          {exp.data && method && !parametersReady && <p className="text-fg-2">正在加载此版本参数…</p>}
          {exp.data && method && parametersReady && (
            <>
              <h2 className="text-headline font-semibold">{METHOD_LABELS[method]}参数</h2>
              {method === "uniaxial" && <UniaxialParams key={`u${runId}`} initial={run.data?.method === "uniaxial" ? run.data.params : undefined} onChange={setBody} />}
              {method === "cyclic" && <CyclicParams key={`c${runId}`} initial={run.data?.method === "cyclic" ? run.data.params : undefined} onChange={setBody} />}
              {method === "pure_shear" && <PureShearParams exp={exp.data} onChange={setBody} />}
              {method === "fatigue_steady" && <FatigueSteadyParams onChange={setBody} />}
              {method === "crack_growth" && <CrackGrowthParams exp={exp.data} onChange={setBody} />}
              {method === "fatigue_threshold" && <ThresholdParams exp={exp.data} onChange={setBody} />}
              {method === "dma" && <DMAParams key={`d${runId}`} initial={run.data?.method === "dma" ? run.data.params : undefined} onChange={setBody} />}
              {exp.data.raw_files.length > 0 && <CorrectionsPanel experimentId={exp.data.id} />}
              <Panel title="样品尺寸">
                <KeyValue items={[
                  ["厚度", exp.data.specimen.thickness_m ? `${mm(exp.data.specimen.thickness_m)} mm` : "—"],
                  ["宽度", exp.data.specimen.width_m ? `${mm(exp.data.specimen.width_m)} mm` : "—"],
                  ["标距 L0", exp.data.specimen.gauge_length_m ? `${mm(exp.data.specimen.gauge_length_m)} mm` : "—"],
                  ["高度 H0", exp.data.specimen.height_m ? `${mm(exp.data.specimen.height_m)} mm` : "—"],
                  ["裂纹 c0", exp.data.specimen.notch_length_m ? `${mm(exp.data.specimen.notch_length_m)} mm` : "—"],
                ]} />
              </Panel>
            </>
          )}
        </aside>
      </div>
      {compareOpen && <CompareDialog runs={runs} onClose={() => setCompareOpen(false)} />}
      {originOpen && run.data && <OriginDialog run={run.data} onClose={() => setOriginOpen(false)} />}
      {toDelete?.kind === "run" && (
        <ConfirmDelete title={`删除分析版本 v${toDelete.version}？`} pending={del.isPending} onConfirm={() => del.mutate()} onClose={() => setToDelete(null)}>
          <p>将删除这个版本的结果、曲线和它在材料数据库中的性能数值；其他版本、原始数据和数据修正不变。</p>
          <p>由它重新计算出的版本会保留（只去掉来源链接）；若其他分析用它作为输入，删除会被拒绝。</p>
        </ConfirmDelete>
      )}
      {toDelete?.kind === "experiment" && exp.data && (
        <ConfirmDelete title={`删除实验 #${exp.data.id}？`} pending={del.isPending} onConfirm={() => del.mutate()} onClose={() => setToDelete(null)}>
          <p>{exp.data.material.name} · {exp.data.specimen.label} · {label(exp.data.test_type)}，共 {exp.data.runs.length} 个分析版本。</p>
          <p>将删除：这个实验、它的全部分析版本及其性能数值、列映射与数据修正、归档的原始文件（与其他导入共用的文件保留）。已导出的 Origin 工程和已保存的图不受影响。</p>
        </ConfirmDelete>
      )}
      {benchOpen && run.data && <BenchmarkDialog runId={run.data.id} onClose={() => setBenchOpen(false)} />}
    </>
  );
}

function CompareDialog({ runs, onClose }: { runs: { id: number; version: number }[]; onClose: () => void }) {
  const [a, setA] = useState(String(runs[1]?.id ?? ""));
  const [b, setB] = useState(String(runs[0]?.id ?? ""));
  const diff = useQuery({
    queryKey: ["compare", a, b],
    queryFn: () => api.get<{ params: Record<string, [unknown, unknown]>; result: Record<string, [unknown, unknown]>; same_input_data: boolean }>(`/analyses/compare?a=${a}&b=${b}`),
    enabled: !!a && !!b && a !== b,
  });
  const fmtv = (v: unknown) => (typeof v === "number" ? Number(v.toPrecision(6)).toString() : JSON.stringify(v));
  const rowsOf = (d: Record<string, [unknown, unknown]>) =>
    Object.entries(d).filter(([k]) => !k.includes("residuals")).slice(0, 60);
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>比较分析版本</DialogTitle>
          <DialogDescription>两个版本都保留在数据库中；这里只显示参数与结果的差异。</DialogDescription>
        </DialogHeader>
        <div className="flex gap-2">
          {[[a, setA], [b, setB]].map(([v, set], i) => (
            <Select key={i} value={v as string} onValueChange={set as (s: string) => void}>
              <SelectTrigger className="h-7 w-40"><SelectValue /></SelectTrigger>
              <SelectContent>{runs.map((r) => <SelectItem key={r.id} value={String(r.id)}>v{r.version}</SelectItem>)}</SelectContent>
            </Select>
          ))}
        </div>
        {diff.data && (
          <div className="max-h-96 space-y-2 overflow-auto">
            <p className="text-fg-2">{diff.data.same_input_data ? "两个版本使用同一份原始数据。" : "两个版本的原始数据不同。"}</p>
            {(["params", "result"] as const).map((k) => (
              <table key={k} className="w-full text-callout">
                <caption className="text-left font-medium">{k === "params" ? "参数" : "结果"}（{Object.keys(diff.data[k]).length} 项不同）</caption>
                <tbody className="tnum">
                  {rowsOf(diff.data[k]).map(([key, [x, y]]) => (
                    <tr key={key} className="border-b"><td className="py-0.5 pr-2 text-fg-2">{key}</td><td className="pr-2">{fmtv(x)}</td><td>{fmtv(y)}</td></tr>
                  ))}
                </tbody>
              </table>
            ))}
          </div>
        )}
        <DialogFooter><Button onClick={onClose}>完成</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function OriginDialog({ run, onClose }: { run: Run; onClose: () => void }) {
  const templates = useQuery({ queryKey: ["plot-templates"], queryFn: () => api.get<{ id: string; name: string; x_key: string | null; y_key: string | null }[]>("/plot-templates") });
  const status = useOriginStatus();
  const usable = (templates.data ?? []).filter((t) => t.x_key && t.y_key && (run.curves_total_points[t.x_key] ?? 0) > 0 && (run.curves_total_points[t.y_key] ?? 0) > 0);
  const [template, setTemplate] = useState(TEMPLATE_FOR[run.method] ?? "");
  const [formats, setFormats] = useState<Set<string>>(new Set(["png", "pdf"]));
  const [jobId, setJobId] = useState<number | null>(null);
  const submit = useMutation({
    mutationFn: () => api.post<OriginJob>("/origin/jobs", { run_id: run.id, template_id: template, exports: [...formats] }),
    onSuccess: (j) => setJobId(j.id),
    onError: (e: Error) => toast.error(e.message),
  });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>导出到 Origin</DialogTitle>
          <DialogDescription>在虚拟机中的 Origin 生成工作簿（原始数据、处理数据、汇总、元数据）与图页（论文图模板），保存 OPJU 并重新打开核验。</DialogDescription>
        </DialogHeader>
        {status.data && !status.data.reachable && <StatusLine severity="error">{status.data.error}</StatusLine>}
        {!jobId ? (
          <div className="space-y-3">
            <Select value={template} onValueChange={setTemplate}>
              <SelectTrigger aria-label="Origin 模板" className="h-7 w-full"><SelectValue placeholder="选择模板" /></SelectTrigger>
              <SelectContent>{usable.map((t) => <SelectItem key={t.id} value={t.id}>{t.name}</SelectItem>)}</SelectContent>
            </Select>
            <FormatPicker formats={formats} onChange={setFormats} />
          </div>
        ) : (
          <OriginJobProgress jobId={jobId} />
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{jobId ? "关闭" : "取消"}</Button>
          {!jobId && <Button disabled={!template || formats.size === 0 || submit.isPending || !status.data?.reachable} onClick={() => submit.mutate()}>{submit.isPending ? "正在发送…" : "发送到 Origin"}</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function correctionsText(list: unknown): string {
  if (!Array.isArray(list)) return "—";
  if (list.length === 0) return "无（原始数据）";
  return list.map((c: { quantity: string; algorithm: string; params: Record<string, unknown> }) => `${ALGORITHMS[c.algorithm] ?? c.algorithm}（${c.quantity}，${describeCorrection(c)}）`).join("；");
}
