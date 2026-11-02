import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { METHOD_LABELS } from "@/lib/units";
import { Toolbar } from "@/components/shell/AppShell";
import { Panel, StatusLine } from "@/components/common";

type Dash = {
  counts: { materials: number; literature_materials: number; experiments: number; analyses: number };
  recent_experiments: { id: number; test_type: string; specimen: string; created_at: string; n_runs: number }[];
  recent_analyses: { id: number; experiment_id: number; method: string; version: number; status: string; created_at: string }[];
  provisional_analyses: number;
  origin_jobs: { id: number; status: string; template_id: string; requested_at: string; opju_path: string | null }[];
};

const when = (s: string) => new Date(s).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });

export default function Dashboard() {
  const d = useQuery({ queryKey: ["dashboard"], queryFn: () => api.get<Dash>("/dashboard") });
  const origin = useQuery({ queryKey: ["origin-status"], queryFn: () => api.get<{ reachable: boolean; error?: string; capabilities?: { origin?: { version?: number } } }>("/origin/status") });
  return (
    <>
      <Toolbar title="概览" />
      <main className="min-h-0 flex-1 overflow-auto p-3">
        {d.isError && <StatusLine severity="error">{(d.error as Error).message}</StatusLine>}
        {d.data && (
          <div className="grid gap-3 lg:grid-cols-3">
            <Panel title="数据库">
              <dl className="grid grid-cols-2 gap-2 text-body">
                {[["材料", d.data.counts.materials], ["文献材料", d.data.counts.literature_materials], ["实验", d.data.counts.experiments], ["分析版本", d.data.counts.analyses]].map(([k, v]) => (
                  <div key={k}><dt className="text-fg-2">{k}</dt><dd className="tnum text-title2">{v}</dd></div>
                ))}
              </dl>
            </Panel>
            <Panel title="Origin">
              {origin.isPending ? <p className="text-fg-2">正在检测…</p> : origin.data?.reachable ? (
                <StatusLine severity="success">已连接 Windows Bridge{origin.data.capabilities?.origin?.version ? `（Origin ${origin.data.capabilities.origin.version}）` : ""}</StatusLine>
              ) : (
                <StatusLine severity="warning">{origin.data?.error ?? "未连接"}——数据处理与普通绘图不受影响</StatusLine>
              )}
              <ul className="mt-2 space-y-1 text-callout">
                {d.data.origin_jobs.map((j) => <li key={j.id} className="flex justify-between"><span>#{j.id} {j.template_id}</span><span className="text-fg-2">{j.status} · {when(j.requested_at)}</span></li>)}
              </ul>
            </Panel>
            <Panel title="待处理">
              {d.data.provisional_analyses > 0 ? (
                <StatusLine severity="warning">{d.data.provisional_analyses} 个临时分析结果（如 λc 未确认、未达稳态、阈值不可辨识）</StatusLine>
              ) : (
                <StatusLine severity="success">没有临时结果</StatusLine>
              )}
            </Panel>
            <Panel title="最近实验" className="lg:col-span-1">
              <ul className="space-y-1">
                {d.data.recent_experiments.map((e) => <li key={e.id}><Link className="hover:underline" to={`/analysis/${e.id}`}>#{e.id} {e.specimen}</Link> <span className="text-fg-2">· {when(e.created_at)}</span></li>)}
                {d.data.recent_experiments.length === 0 && <li className="text-fg-2">还没有实验。<Link className="text-accent-text underline" to="/experiments/import">导入数据…</Link></li>}
              </ul>
            </Panel>
            <Panel title="最近分析" className="lg:col-span-2">
              <ul className="space-y-1">
                {d.data.recent_analyses.map((r) => (
                  <li key={r.id} className="flex justify-between">
                    <Link className="hover:underline" to={`/analysis/${r.experiment_id}`}>{METHOD_LABELS[r.method] ?? r.method} v{r.version}（实验 #{r.experiment_id}）</Link>
                    <span className="text-fg-2">{r.status === "ok" ? "" : "临时 · "}{when(r.created_at)}</span>
                  </li>
                ))}
              </ul>
            </Panel>
          </div>
        )}
      </main>
    </>
  );
}
